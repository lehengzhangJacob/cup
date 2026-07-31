from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from fastapi.responses import FileResponse

from .config import (
    MAP_TILE_CACHE_DIR,
    MAP_TILE_UPSTREAM_PROXY,
    MAP_TILE_UPSTREAM_URL,
    MAP_TILE_USER_AGENT,
    PUBLIC_APP_URL,
)


log = logging.getLogger(__name__)

DEFAULT_CACHE_SECONDS = 7 * 24 * 60 * 60
MAX_CACHE_SECONDS = 30 * 24 * 60 * 60
MAX_TILE_BYTES = 1_500_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CACHE_MAX_AGE = re.compile(r"(?:^|,)\s*max-age=(\d+)", re.IGNORECASE)
_tile_locks: dict[tuple[int, int, int], asyncio.Lock] = {}


class MapTileUnavailable(RuntimeError):
    pass


def validate_tile_coordinates(z: int, x: int, y: int) -> None:
    if z < 0 or z > 19:
        raise ValueError("地图缩放级别超出范围")
    limit = 1 << z
    if x < 0 or y < 0 or x >= limit or y >= limit:
        raise ValueError("地图瓦片坐标超出范围")


def _cache_seconds(headers: Mapping[str, str]) -> int:
    cache_control = str(headers.get("cache-control") or "")
    match = _CACHE_MAX_AGE.search(cache_control)
    if not match:
        return DEFAULT_CACHE_SECONDS
    return max(300, min(int(match.group(1)), MAX_CACHE_SECONDS))


def _paths(z: int, x: int, y: int) -> tuple[Path, Path]:
    tile_path = MAP_TILE_CACHE_DIR / str(z) / str(x) / f"{y}.png"
    return tile_path, tile_path.with_suffix(".json")


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _tile_response(
    tile_path: Path,
    metadata: Mapping[str, Any],
    *,
    cache_status: str,
    stale: bool = False,
) -> FileResponse:
    fetched_at = float(metadata.get("fetched_at") or 0)
    max_age = int(metadata.get("max_age") or DEFAULT_CACHE_SECONDS)
    remaining = 300 if stale else max(0, round(fetched_at + max_age - time.time()))
    return FileResponse(
        tile_path,
        media_type="image/png",
        headers={
            "Cache-Control": f"public, max-age={remaining}, stale-if-error=604800",
            "X-Map-Tile-Cache": cache_status,
            **({"X-Map-Tile-Stale": "1"} if stale else {}),
        },
    )


def _valid_referer(value: str | None) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return f"{PUBLIC_APP_URL or 'https://lingshanguide.de5.net'}/"


async def get_map_tile(z: int, x: int, y: int, *, referer: str | None) -> FileResponse:
    validate_tile_coordinates(z, x, y)
    tile_path, metadata_path = _paths(z, x, y)
    metadata = _load_metadata(metadata_path)
    if tile_path.is_file() and time.time() < (
        float(metadata.get("fetched_at") or 0)
        + int(metadata.get("max_age") or DEFAULT_CACHE_SECONDS)
    ):
        return _tile_response(tile_path, metadata, cache_status="HIT")

    lock = _tile_locks.setdefault((z, x, y), asyncio.Lock())
    async with lock:
        metadata = _load_metadata(metadata_path)
        if tile_path.is_file() and time.time() < (
            float(metadata.get("fetched_at") or 0)
            + int(metadata.get("max_age") or DEFAULT_CACHE_SECONDS)
        ):
            return _tile_response(tile_path, metadata, cache_status="HIT")

        request_headers = {
            "Accept": "image/png,image/*;q=0.9,*/*;q=0.5",
            "User-Agent": MAP_TILE_USER_AGENT,
            "Referer": _valid_referer(referer),
        }
        if metadata.get("etag"):
            request_headers["If-None-Match"] = str(metadata["etag"])
        if metadata.get("last_modified"):
            request_headers["If-Modified-Since"] = str(metadata["last_modified"])

        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(12.0, connect=8.0),
            "follow_redirects": True,
            "trust_env": False,
            "headers": request_headers,
        }
        if MAP_TILE_UPSTREAM_PROXY:
            client_options["proxy"] = MAP_TILE_UPSTREAM_PROXY

        upstream_url = MAP_TILE_UPSTREAM_URL.format(z=z, x=x, y=y)
        try:
            async with httpx.AsyncClient(**client_options) as client:
                response = await client.get(upstream_url)
            if response.status_code == 304 and tile_path.is_file():
                metadata = {
                    **metadata,
                    "fetched_at": time.time(),
                    "max_age": _cache_seconds(response.headers) if response.headers else int(
                        metadata.get("max_age") or DEFAULT_CACHE_SECONDS
                    ),
                }
                _write_atomic(
                    metadata_path,
                    json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
                )
                return _tile_response(tile_path, metadata, cache_status="REVALIDATED")

            response.raise_for_status()
            if response.headers.get("x-blocked"):
                raise MapTileUnavailable("OSM 拒绝了当前瓦片出口")
            if len(response.content) > MAX_TILE_BYTES or not response.content.startswith(PNG_SIGNATURE):
                raise MapTileUnavailable("上游未返回有效 PNG 瓦片")

            metadata = {
                "fetched_at": time.time(),
                "max_age": _cache_seconds(response.headers),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "upstream": urlparse(upstream_url).netloc,
            }
            _write_atomic(tile_path, response.content)
            _write_atomic(
                metadata_path,
                json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            )
            return _tile_response(tile_path, metadata, cache_status="MISS")
        except (httpx.HTTPError, OSError, MapTileUnavailable) as exc:
            if tile_path.is_file():
                log.warning("map tile refresh failed; serving stale tile %s: %s", tile_path, exc)
                return _tile_response(tile_path, metadata, cache_status="STALE", stale=True)
            raise MapTileUnavailable("地图瓦片上游暂不可用") from exc
