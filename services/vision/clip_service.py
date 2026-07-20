"""SigLIP/CLIP image-encoding socket service (softcup environment).

Mirrors the RAG embed_service pattern but simplified for images: a
CPU-resident model answers encode requests over a Unix socket, with an optional
on-demand GPU path via CLIP_DEVICE=cuda. The API process never imports torch;
it only connects here to encode a query image, then runs cosine search locally
against the on-disk reference index.

Protocol (multiprocessing.connection over AF_UNIX):
    request  -> {"command": "health"} | {"command": "encode", "images": [bytes, ...]}
    response -> {"ok": True, "vectors": np.ndarray} | {"ok": False, "error": str}
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from multiprocessing.connection import Listener
from pathlib import Path

os.environ.setdefault("PYTORCH_NVML_BASED_CUDA_CHECK", "1")

import numpy as np

# Allow running as a script from either the repo root or services/vision.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import clip_runner  # noqa: E402

CLIP_MODEL = os.getenv("CLIP_MODEL", str(_HERE.parents[1] / "model" / "siglip-base-patch16-224"))
CLIP_DEVICE = os.getenv("CLIP_DEVICE", "cpu").strip()
CLIP_SOCKET = Path(os.getenv("CLIP_SOCKET", str(_HERE.parents[1] / "deploy" / "vision-clip.sock")))
CLIP_STATUS_FILE = Path(
    os.getenv("CLIP_STATUS_FILE", str(_HERE.parents[1] / "deploy" / "vision-clip-status.json"))
)
CLIP_GPU = os.getenv("CLIP_GPU", "3").strip()


def _write_status(payload: dict) -> None:
    CLIP_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CLIP_STATUS_FILE.with_name(f"{CLIP_STATUS_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CLIP_STATUS_FILE)


class ClipCoordinator:
    def __init__(self) -> None:
        self.model = None
        self.processor = None
        self.device = CLIP_DEVICE
        if CLIP_DEVICE.startswith("cuda"):
            self.device = f"cuda:{CLIP_GPU}" if CLIP_DEVICE == "cuda" else CLIP_DEVICE
        _write_status(
            {
                "ready": False,
                "mode": "loading",
                "device": self.device,
                "model": CLIP_MODEL,
                "pid": os.getpid(),
                "updated_at": time.time(),
            }
        )
        try:
            self.model, self.processor, _ = clip_runner.load_model(CLIP_MODEL, self.device)
        except Exception as exc:  # noqa: BLE001
            _write_status(
                {
                    "ready": False,
                    "mode": "error",
                    "device": self.device,
                    "model": CLIP_MODEL,
                    "pid": os.getpid(),
                    "reason": str(exc),
                    "updated_at": time.time(),
                }
            )
            raise
        _write_status(
            {
                "ready": True,
                "mode": "ready",
                "device": self.device,
                "model": CLIP_MODEL,
                "pid": os.getpid(),
                "updated_at": time.time(),
            }
        )

    def encode(self, images: list[bytes]) -> dict:
        if not images:
            return {"ok": False, "error": "images must not be empty"}
        started = time.perf_counter()
        vectors = clip_runner.encode_bytes(self.model, self.processor, self.device, images)
        return {
            "ok": True,
            "vectors": vectors,
            "device": self.device,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    def status(self) -> dict:
        return {
            "ready": True,
            "mode": "ready",
            "device": self.device,
            "model": CLIP_MODEL,
            "pid": os.getpid(),
        }

    def close(self) -> None:
        _write_status(
            {
                "ready": False,
                "mode": "stopped",
                "device": "none",
                "model": CLIP_MODEL,
                "pid": os.getpid(),
                "updated_at": time.time(),
            }
        )


def serve() -> None:
    coordinator = ClipCoordinator()
    CLIP_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    CLIP_SOCKET.unlink(missing_ok=True)
    listener = Listener(str(CLIP_SOCKET), family="AF_UNIX")
    os.chmod(CLIP_SOCKET, 0o600)

    def shutdown(_signum, _frame) -> None:
        coordinator.close()
        try:
            listener.close()
        except (OSError, ValueError):
            pass
        CLIP_SOCKET.unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        client = listener.accept()
        try:
            request = client.recv()
            command = request.get("command")
            if command == "health":
                client.send({"ok": True, **coordinator.status()})
            elif command == "encode":
                client.send(coordinator.encode(request.get("images") or []))
            else:
                client.send({"ok": False, "error": "unknown command"})
        except (EOFError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                client.send({"ok": False, "error": str(exc)})
            except (BrokenPipeError, EOFError, OSError):
                pass
        finally:
            client.close()


def main() -> None:
    # Single-image CLI mode for offline scripts: --encode-image <path>
    if "--encode-image" in sys.argv:
        idx = sys.argv.index("--encode-image")
        path = sys.argv[idx + 1]
        device = os.getenv("CLIP_DEVICE", "cpu")
        model, processor, _ = clip_runner.load_model(CLIP_MODEL, device)
        with open(path, "rb") as f:
            vec = clip_runner.encode_bytes(model, processor, device, [f.read()])[0]
        # Print as comma-separated floats so any language can consume it.
        print(",".join(f"{x:.6f}" for x in vec.tolist()))
        return
    serve()


if __name__ == "__main__":
    main()
