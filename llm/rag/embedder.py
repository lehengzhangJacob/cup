import json
import os
import threading
import time
from multiprocessing.connection import Client

import numpy as np
from sentence_transformers import SentenceTransformer
from rag.config import (
    EMBED_DEVICE,
    EMBED_MODEL,
    EMBED_REQUEST_TIMEOUT_SECONDS,
    EMBED_SOCKET,
    EMBED_STATUS_FILE,
)


_CONNECT_RETRY_ATTEMPTS = 21
_CONNECT_RETRY_INTERVAL_SECONDS = 0.1


class Embedder:
    def __init__(self, model=None):
        self._remote = model is None and EMBED_DEVICE == "on-demand"
        self._model = model
        if self._model is None and not self._remote:
            self._model = SentenceTransformer(
                EMBED_MODEL,
                device=EMBED_DEVICE,
            )
        self._lock = threading.Lock()

    def encode_batch(self, texts: list) -> np.ndarray:
        if not texts:
            raise ValueError("texts must not be empty")
        with self._lock:
            if self._remote:
                vectors = self._remote_encode(texts)
            else:
                vectors = self._model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
        return np.asarray(vectors, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode_batch([text])[0]

    def status(self) -> dict:
        if not self._remote:
            device = str(getattr(self._model, "device", EMBED_DEVICE or "cpu"))
            return {
                "ready": True,
                "mode": "local",
                "device": device,
                "gpu_index": None,
            }
        try:
            status = json.loads(EMBED_STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "ready": False,
                "mode": "unavailable",
                "device": "none",
                "gpu_index": None,
            }
        coordinator_pid = int(status.get("coordinator_pid") or 0)
        if not self._process_alive(coordinator_pid):
            status.update(
                ready=False,
                mode="unavailable",
                device="none",
                gpu_index=None,
            )
        elif status.get("mode") == "cpu-standby":
            status = self._refresh_remote_status(status)
        return status

    def close(self) -> None:
        return None

    def _remote_encode(self, texts: list) -> np.ndarray:
        connection = self._connect_remote()
        try:
            connection.send({"command": "encode", "texts": list(texts)})
            if not connection.poll(EMBED_REQUEST_TIMEOUT_SECONDS):
                raise TimeoutError(
                    "RAG GPU embedding timed out after "
                    f"{EMBED_REQUEST_TIMEOUT_SECONDS:g} seconds"
                )
            response = connection.recv()
        except (EOFError, OSError) as exc:
            raise RuntimeError("RAG embedding coordinator disconnected") from exc
        finally:
            connection.close()
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "RAG embedding failed")
        return np.asarray(response["vectors"], dtype=np.float32)

    @staticmethod
    def _connect_remote():
        last_error: OSError | None = None
        for attempt in range(_CONNECT_RETRY_ATTEMPTS):
            try:
                return Client(str(EMBED_SOCKET), family="AF_UNIX")
            except OSError as exc:
                last_error = exc
                if attempt + 1 < _CONNECT_RETRY_ATTEMPTS:
                    time.sleep(_CONNECT_RETRY_INTERVAL_SECONDS)
        raise RuntimeError("RAG embedding coordinator is unavailable") from last_error

    def _refresh_remote_status(self, fallback: dict) -> dict:
        try:
            connection = Client(str(EMBED_SOCKET), family="AF_UNIX")
            connection.send({"command": "health"})
            if not connection.poll(0.5):
                return fallback
            response = connection.recv()
            if response.get("ok"):
                return {
                    key: value
                    for key, value in response.items()
                    if key != "ok"
                }
            return fallback
        except (EOFError, OSError):
            return fallback
        finally:
            if "connection" in locals():
                connection.close()

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
