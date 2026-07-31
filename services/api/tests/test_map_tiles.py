from __future__ import annotations

import pytest

from app.map_tiles import DEFAULT_CACHE_SECONDS, _cache_seconds, validate_tile_coordinates


def test_tile_coordinates_are_bounded_by_zoom_level():
    validate_tile_coordinates(0, 0, 0)
    validate_tile_coordinates(19, (1 << 19) - 1, (1 << 19) - 1)

    with pytest.raises(ValueError):
        validate_tile_coordinates(20, 0, 0)
    with pytest.raises(ValueError):
        validate_tile_coordinates(4, 16, 0)
    with pytest.raises(ValueError):
        validate_tile_coordinates(4, 0, -1)


def test_cache_lifetime_honours_upstream_max_age():
    assert _cache_seconds({"cache-control": "public, max-age=86400"}) == 86400
    assert _cache_seconds({"cache-control": "public"}) == DEFAULT_CACHE_SECONDS
    assert _cache_seconds({"cache-control": "max-age=10"}) == 300
