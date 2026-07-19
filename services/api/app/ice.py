from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from .config import (
    CLOUDFLARE_TURN_API_TOKEN,
    CLOUDFLARE_TURN_KEY_ID,
    CLOUDFLARE_TURN_TTL_SECONDS,
)

_credentials_lock = asyncio.Lock()
_credentials_expires_at = 0.0
_cached_ice_servers: list[dict[str, Any]] = []
_BROWSER_BLOCKED_PORT = re.compile(
    r"^(?:stun|stuns|turn|turns):(?:[^@/?#]+@)?(?:\[[^\]]+\]|[^:/?#]+):53(?:[/?#]|$)",
    re.IGNORECASE,
)


def _configured(value: str) -> bool:
    return bool(value and value != "CHANGE_ME")


def cloudflare_turn_configured() -> bool:
    return _configured(CLOUDFLARE_TURN_KEY_ID) and _configured(CLOUDFLARE_TURN_API_TOKEN)


def cloudflare_turn_config_error() -> str | None:
    if _configured(CLOUDFLARE_TURN_KEY_ID) == _configured(CLOUDFLARE_TURN_API_TOKEN):
        return None
    return "CLOUDFLARE_TURN_KEY_ID and CLOUDFLARE_TURN_API_TOKEN must be set together"


def _without_browser_blocked_port_53(servers: list[Any]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for raw_server in servers:
        if not isinstance(raw_server, dict):
            continue
        raw_urls = raw_server.get("urls")
        urls = [raw_urls] if isinstance(raw_urls, str) else raw_urls
        if not isinstance(urls, list):
            continue
        safe_urls = [
            url
            for url in urls
            if isinstance(url, str) and not _BROWSER_BLOCKED_PORT.match(url)
        ]
        if not safe_urls:
            continue
        server = {"urls": safe_urls}
        for field in ("username", "credential", "credentialType"):
            if raw_server.get(field) is not None:
                server[field] = raw_server[field]
        filtered.append(server)
    return filtered


async def cloudflare_ice_servers() -> list[dict[str, Any]]:
    """Return cached short-lived Cloudflare TURN credentials."""
    global _credentials_expires_at, _cached_ice_servers

    if not cloudflare_turn_configured():
        return []
    now = time.monotonic()
    if _cached_ice_servers and now < _credentials_expires_at:
        return _cached_ice_servers

    async with _credentials_lock:
        now = time.monotonic()
        if _cached_ice_servers and now < _credentials_expires_at:
            return _cached_ice_servers
        url = (
            "https://rtc.live.cloudflare.com/v1/turn/keys/"
            f"{CLOUDFLARE_TURN_KEY_ID}/credentials/generate-ice-servers"
        )
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_TURN_API_TOKEN}"},
                json={"ttl": CLOUDFLARE_TURN_TTL_SECONDS},
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Cloudflare TURN response was not an object")
        servers = _without_browser_blocked_port_53(payload.get("iceServers", []))
        if not any(
            str(url).lower().startswith(("turn:", "turns:"))
            for server in servers
            for url in server.get("urls", [])
        ):
            raise RuntimeError("Cloudflare TURN response did not contain a usable TURN URL")

        refresh_margin = min(300, CLOUDFLARE_TURN_TTL_SECONDS // 5)
        _cached_ice_servers = servers
        _credentials_expires_at = time.monotonic() + CLOUDFLARE_TURN_TTL_SECONDS - refresh_margin
        return _cached_ice_servers
