from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import subprocess
import time
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTORCH_NVML_BASED_CUDA_CHECK", "1")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from rag.config import (
    EMBED_GPU_CANDIDATES,
    EMBED_GPU_IDLE_SECONDS,
    EMBED_GPU_MIN_FREE_MB,
    EMBED_MODEL,
    EMBED_REQUEST_TIMEOUT_SECONDS,
    EMBED_SOCKET,
    EMBED_STATUS_FILE,
)


def _write_status(status_file: Path, payload: dict[str, Any]) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = status_file.with_name(
        f"{status_file.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, status_file)


def _gpu_snapshot() -> list[dict[str, int]]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    allowed = set(EMBED_GPU_CANDIDATES)
    snapshot: list[dict[str, int]] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        index, free_mb, utilization = map(int, parts)
        if index in allowed:
            snapshot.append(
                {
                    "index": index,
                    "free_mb": free_mb,
                    "utilization": utilization,
                }
            )
    return snapshot


def _select_gpu() -> tuple[int, list[dict[str, int]]]:
    snapshot = _gpu_snapshot()
    eligible = [
        gpu for gpu in snapshot if gpu["free_mb"] >= EMBED_GPU_MIN_FREE_MB
    ]
    if not eligible:
        raise RuntimeError(
            f"No GPU has at least {EMBED_GPU_MIN_FREE_MB} MiB free"
        )
    selected = min(
        eligible,
        key=lambda gpu: (gpu["utilization"], -gpu["free_mb"], gpu["index"]),
    )
    return selected["index"], snapshot


def _gpu_worker(
    model: SentenceTransformer,
    connection: Connection,
    coordinator_pid: int,
) -> None:
    gpu_index: int | None = None
    try:
        gpu_index, snapshot = _select_gpu()
        target = torch.device(f"cuda:{gpu_index}")
        model.to(device=target, dtype=torch.float16)
        torch.cuda.synchronize(target)
        _write_status(
            EMBED_STATUS_FILE,
            {
                "ready": True,
                "mode": "gpu-active",
                "device": str(target),
                "gpu_index": gpu_index,
                "coordinator_pid": coordinator_pid,
                "worker_pid": os.getpid(),
                "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                "last_selection": snapshot,
                "updated_at": time.time(),
            },
        )
        connection.send({"ok": True, "gpu_index": gpu_index})
        while connection.poll(EMBED_GPU_IDLE_SECONDS):
            request = connection.recv()
            if request.get("command") == "stop":
                break
            texts = request.get("texts") or []
            if not texts:
                connection.send({"ok": False, "error": "texts must not be empty"})
                continue
            started = time.perf_counter()
            with torch.inference_mode():
                vectors = model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            connection.send(
                {
                    "ok": True,
                    "vectors": np.asarray(vectors, dtype=np.float32),
                    "gpu_index": gpu_index,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            _write_status(
                EMBED_STATUS_FILE,
                {
                    "ready": True,
                    "mode": "gpu-active",
                    "device": str(target),
                    "gpu_index": gpu_index,
                    "coordinator_pid": coordinator_pid,
                    "worker_pid": os.getpid(),
                    "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                    "last_selection": snapshot,
                    "updated_at": time.time(),
                },
            )
    except BaseException as exc:
        try:
            connection.send({"ok": False, "error": str(exc)})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        _write_status(
            EMBED_STATUS_FILE,
            {
                "ready": True,
                "mode": "cpu-standby",
                "device": "cpu",
                "gpu_index": None,
                "coordinator_pid": coordinator_pid,
                "worker_pid": None,
                "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                "updated_at": time.time(),
            },
        )
        connection.close()


class EmbeddingCoordinator:
    def __init__(self) -> None:
        _write_status(
            EMBED_STATUS_FILE,
            {
                "ready": False,
                "mode": "loading",
                "device": "cpu",
                "gpu_index": None,
                "coordinator_pid": os.getpid(),
                "worker_pid": None,
                "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                "updated_at": time.time(),
            },
        )
        self.model = SentenceTransformer(EMBED_MODEL, device="cpu")
        self.context = mp.get_context("fork")
        self.worker: mp.Process | None = None
        self.worker_connection: Connection | None = None
        self.listener: Listener | None = None
        self._write_standby_status()

    def serve(self) -> None:
        EMBED_SOCKET.parent.mkdir(parents=True, exist_ok=True)
        EMBED_SOCKET.unlink(missing_ok=True)
        self.listener = Listener(str(EMBED_SOCKET), family="AF_UNIX")
        os.chmod(EMBED_SOCKET, 0o600)
        while True:
            client = self.listener.accept()
            try:
                request = client.recv()
                command = request.get("command")
                if command == "health":
                    client.send({"ok": True, **self.status()})
                elif command == "encode":
                    client.send(self.encode(request.get("texts") or []))
                else:
                    client.send({"ok": False, "error": "unknown command"})
            except (EOFError, OSError):
                pass
            except Exception as exc:
                try:
                    client.send({"ok": False, "error": str(exc)})
                except (BrokenPipeError, EOFError, OSError):
                    pass
            finally:
                client.close()

    def encode(self, texts: list[str]) -> dict[str, Any]:
        if not texts:
            return {"ok": False, "error": "texts must not be empty"}
        for attempt in range(2):
            try:
                connection = self._ensure_worker()
                connection.send({"command": "encode", "texts": texts})
                if not connection.poll(EMBED_REQUEST_TIMEOUT_SECONDS):
                    raise TimeoutError("GPU embedding worker timed out")
                return connection.recv()
            except (BrokenPipeError, EOFError, OSError, TimeoutError):
                self._stop_worker()
                if attempt == 1:
                    raise
        raise RuntimeError("GPU embedding worker failed")

    def status(self) -> dict[str, Any]:
        self._cleanup_worker()
        return {
            "ready": True,
            "mode": "gpu-active" if self.worker is not None else "cpu-standby",
            "device": "gpu" if self.worker is not None else "cpu",
            "gpu_index": None,
            "coordinator_pid": os.getpid(),
            "worker_pid": self.worker.pid if self.worker is not None else None,
            "idle_seconds": EMBED_GPU_IDLE_SECONDS,
        }

    def close(self) -> None:
        self._stop_worker()
        if self.listener is not None:
            self.listener.close()
        EMBED_SOCKET.unlink(missing_ok=True)
        _write_status(
            EMBED_STATUS_FILE,
            {
                "ready": False,
                "mode": "stopped",
                "device": "none",
                "gpu_index": None,
                "coordinator_pid": os.getpid(),
                "worker_pid": None,
                "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                "updated_at": time.time(),
            },
        )

    def _ensure_worker(self) -> Connection:
        self._cleanup_worker()
        if self.worker is not None and self.worker_connection is not None:
            return self.worker_connection
        parent_connection, child_connection = self.context.Pipe()
        worker = self.context.Process(
            target=_gpu_worker,
            args=(self.model, child_connection, os.getpid()),
            daemon=True,
        )
        worker.start()
        child_connection.close()
        self.worker = worker
        self.worker_connection = parent_connection
        if not parent_connection.poll(EMBED_REQUEST_TIMEOUT_SECONDS):
            self._stop_worker()
            raise TimeoutError("GPU embedding worker startup timed out")
        ready = parent_connection.recv()
        if not ready.get("ok"):
            self._stop_worker()
            raise RuntimeError(ready.get("error") or "GPU worker failed to start")
        return parent_connection

    def _cleanup_worker(self) -> None:
        if self.worker is not None and not self.worker.is_alive():
            self.worker.join(timeout=0.1)
            if self.worker_connection is not None:
                self.worker_connection.close()
            self.worker = None
            self.worker_connection = None
            self._write_standby_status()

    def _stop_worker(self) -> None:
        if self.worker_connection is not None:
            try:
                self.worker_connection.send({"command": "stop"})
            except (BrokenPipeError, EOFError, OSError):
                pass
            self.worker_connection.close()
        if self.worker is not None:
            self.worker.join(timeout=2)
            if self.worker.is_alive():
                self.worker.terminate()
                self.worker.join(timeout=3)
        self.worker = None
        self.worker_connection = None
        self._write_standby_status()

    def _write_standby_status(self) -> None:
        _write_status(
            EMBED_STATUS_FILE,
            {
                "ready": True,
                "mode": "cpu-standby",
                "device": "cpu",
                "gpu_index": None,
                "coordinator_pid": os.getpid(),
                "worker_pid": None,
                "idle_seconds": EMBED_GPU_IDLE_SECONDS,
                "updated_at": time.time(),
            },
        )


def main() -> None:
    coordinator = EmbeddingCoordinator()

    def shutdown(_signum, _frame) -> None:
        coordinator.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        coordinator.serve()
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
