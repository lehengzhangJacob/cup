"""Regression tests for the on-disk CLIP reference index."""
from __future__ import annotations

import numpy as np

from app import config, vision_index


def test_index_round_trip_uses_atomic_npz_file(tmp_path, monkeypatch):
    index_path = tmp_path / "vision_index.npz"
    monkeypatch.setattr(config, "VISION_INDEX_PATH", index_path)
    monkeypatch.setattr(config, "CLIP_MODEL", "test-clip")

    vector = np.asarray([0.6, 0.8], dtype=np.float32)
    vision_index.upsert_vector("LS-011/front.jpg", vector, "LS-011")

    assert index_path.is_file()
    assert not index_path.with_suffix(".npz.tmp").exists()
    assert not index_path.with_suffix(".tmp.npz").exists()
    assert vision_index.status() == {
        "healthy": True,
        "vectors": 1,
        "dim": 2,
        "model": "test-clip",
        "matches_manifest_model": True,
    }

    hits = vision_index.search(vector, top_k=3)
    assert hits[0]["attraction_id"] == "LS-011"
    assert hits[0]["name"] == "灵山大佛"
    assert hits[0]["file"] == "LS-011/front.jpg"

    vision_index.remove_vector("LS-011/front.jpg")
    assert vision_index.status()["vectors"] == 0
