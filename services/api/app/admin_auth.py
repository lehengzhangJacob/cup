from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Optional

from .config import ADMIN_SESSION_SECRET, ADMIN_SESSION_TTL_SECONDS, ADMIN_USERNAME, DATA_DIR


ADMIN_COOKIE_NAME = "lingshan_admin_session"
_secret_cache: Optional[bytes] = None


def _session_secret() -> bytes:
    """Load a stable local signing key without committing it to source control."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    if ADMIN_SESSION_SECRET:
        _secret_cache = ADMIN_SESSION_SECRET.encode("utf-8")
        return _secret_cache

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_path = Path(DATA_DIR) / ".admin_session_secret"
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        secret = secrets.token_urlsafe(48)
        try:
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(secret)
        except FileExistsError:
            secret = secret_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError("admin session secret is empty")
    _secret_cache = secret.encode("utf-8")
    return _secret_cache


def _encode_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(encoded: str) -> dict[str, Any]:
    padding = "=" * (-len(encoded) % 4)
    raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid session payload")
    return value


def create_admin_token(username: str = ADMIN_USERNAME) -> str:
    now = int(time.time())
    payload = _encode_payload(
        {
            "sub": username,
            "iat": now,
            "exp": now + ADMIN_SESSION_TTL_SECONDS,
            "nonce": secrets.token_hex(8),
        }
    )
    signature = hmac.new(_session_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_admin_token(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(_session_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        data = _decode_payload(payload)
        return (
            data.get("sub") == ADMIN_USERNAME
            and int(data.get("iat", 0)) <= int(time.time()) + 30
            and int(data.get("exp", 0)) > int(time.time())
        )
    except (ValueError, TypeError, binascii.Error):
        return False
