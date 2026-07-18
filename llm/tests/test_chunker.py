# tests/test_chunker.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

WHITELIST = Path("data/whitelist.json")

def test_whitelist_exists():
    assert WHITELIST.exists()

def test_whitelist_has_key_attractions():
    data = json.loads(WHITELIST.read_text(encoding="utf-8"))
    names = data["names"]
    for expected in ["灵山大佛", "灵山梵宫", "九龙灌浴"]:
        assert expected in names, f"{expected} missing from whitelist"

def test_whitelist_has_aliases():
    data = json.loads(WHITELIST.read_text(encoding="utf-8"))
    assert "大佛" in data["aliases"]
    assert data["aliases"]["大佛"] == "灵山大佛"

from rag.chunker import chunk_guideline, chunk_dataset, chunk_xlsx

def test_chunk_guideline_returns_list():
    chunks = chunk_guideline()
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_chunk_guideline_metadata():
    chunks = chunk_guideline()
    for c in chunks:
        assert "text" in c and "metadata" in c
        assert "source" in c["metadata"]
        assert c["metadata"]["source"] == "guideline"

def test_chunk_dataset_returns_list():
    chunks = chunk_dataset()
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_chunk_xlsx_filtered():
    chunks = chunk_xlsx()
    for c in chunks:
        meta = c["metadata"]
        assert meta.get("attraction_name") is not None
        assert meta["attraction_name"] in _load_whitelist()

def _load_whitelist():
    import json
    from rag.config import WHITELIST_JSON
    return json.loads(WHITELIST_JSON.read_text(encoding="utf-8"))["names"]
