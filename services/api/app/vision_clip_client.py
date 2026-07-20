"""Thin Unix-socket client for the softcup-side CLIP encoding service.

Everything here degrades gracefully: if the socket is down, the model is not
ready, or numpy is unavailable, ``encode_image`` returns ``None`` and the vision
pipeline falls back to the glm-4v-flash single-stage flow. No torch dependency
is ever imported in the API process.
"""
from __future__ import annotations

import logging
from typing import Any

from . import config

log = logging.getLogger(__name__)

try:
    import numpy as np  # noqa: F401
    _HAS_NUMPY = True
except Exception:  # noqa: BLE001
    _HAS_NUMPY = False


def _disabled() -> bool:
    return config.CLIP_MODE == "disabled"


def is_available() -> bool:
    """Cheap readiness check used to decide whether to attempt CLIP recall."""
    if _disabled() or not _HAS_NUMPY:
        return False
    if config.CLIP_MODE == "inproc":
        # In-process mode would load torch here; treat as unavailable unless the
        # caller opts in via env. Keeps the API process torch-free by default.
        return False
    return config.CLIP_SOCKET.exists()


def health() -> dict[str, Any]:
    if _disabled() or not _HAS_NUMPY:
        return {"ready": False, "reason": "disabled"}
    if config.CLIP_MODE == "inproc":
        return {"ready": False, "reason": "inproc not supported in API process"}
    if not config.CLIP_SOCKET.exists():
        return {"ready": False, "reason": "socket missing"}
    try:
        from multiprocessing.connection import Client

        with Client(str(config.CLIP_SOCKET), family="AF_UNIX") as conn:
            conn.send({"command": "health"})
            resp = conn.recv()
        return resp if isinstance(resp, dict) else {"ready": False, "reason": "bad response"}
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "reason": str(exc)}


def encode_image(jpeg_bytes: bytes):
    """Encode one image to an L2-normalized vector, or ``None`` on any failure."""
    if _disabled() or not _HAS_NUMPY or not jpeg_bytes:
        return None
    if config.CLIP_MODE == "inproc":
        return None
    if not config.CLIP_SOCKET.exists():
        return None
    try:
        import numpy as np
        from multiprocessing.connection import Client

        with Client(str(config.CLIP_SOCKET), family="AF_UNIX") as conn:
            conn.send({"command": "encode", "images": [jpeg_bytes]})
            resp = conn.recv()
        if not isinstance(resp, dict) or not resp.get("ok"):
            log.warning("clip encode failed: %s", (resp or {}).get("error") if isinstance(resp, dict) else resp)
            return None
        vec = resp["vectors"]
        return np.frombuffer(vec, dtype=np.float32).reshape(-1)
    except Exception as exc:  # noqa: BLE001
        log.warning("clip encode unavailable, degrading: %s", exc)
        return None


def encode_images(jpeg_bytes_list: list[bytes]):
    """Batch encode. Returns a list aligned with the input (None where failed)."""
    if _disabled() or not _HAS_NUMPY or not jpeg_bytes_list:
        return [None] * len(jpeg_bytes_list)
    if config.CLIP_MODE == "inproc" or not config.CLIP_SOCKET.exists():
        return [None] * len(jpeg_bytes_list)
    try:
        import numpy as np
        from multiprocessing.connection import Client

        with Client(str(config.CLIP_SOCKET), family="AF_UNIX") as conn:
            conn.send({"command": "encode", "images": jpeg_bytes_list})
            resp = conn.recv()
        if not isinstance(resp, dict) or not resp.get("ok"):
            return [None] * len(jpeg_bytes_list)
        arr = np.frombuffer(resp["vectors"], dtype=np.float32).reshape(len(jpeg_bytes_list), -1)
        return [arr[i] for i in range(len(jpeg_bytes_list))]
    except Exception as exc:  # noqa: BLE001
        log.warning("clip batch encode unavailable, degrading: %s", exc)
        return [None] * len(jpeg_bytes_list)
