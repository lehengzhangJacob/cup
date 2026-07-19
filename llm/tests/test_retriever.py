# tests/test_retriever.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from rag.embedder import Embedder
from rag.retriever import Retriever


@pytest.fixture(scope="module")
def embedder():
    return Embedder()


@pytest.fixture(scope="module")
def retriever(embedder):
    return Retriever(embedder=embedder)


def test_embedder_encode_query(embedder):
    vec = embedder.encode_query("灵山大佛多高？")
    assert vec.shape == (1024,)


def test_embedder_encode_batch(embedder):
    vecs = embedder.encode_batch(["灵山大佛", "九龙灌浴"])
    assert vecs.shape == (2, 1024)


def test_retriever_returns_chunks(retriever):
    results = retriever.retrieve("灵山大佛是用什么材料建造的？")
    assert isinstance(results, list)
    assert len(results) > 0


def test_retriever_attraction_filter(retriever):
    results = retriever.retrieve("灵山大佛有多高？")
    # 单子景点命中后，结果应聚焦到该子景点或其父景区（灵山胜境）
    for chunk in results:
        m = chunk["metadata"]
        assert m["attraction_name"] in {"灵山大佛", "灵山胜境"}


def test_retriever_scenic_area_expands_to_subattractions(retriever):
    results = retriever.retrieve("拈花湾有哪些景点？")
    # 命中景区应能召回其子景点
    areas = {c["metadata"].get("scenic_area") for c in results}
    assert "拈花湾禅意小镇" in areas



def test_retriever_full_search_on_no_match(retriever):
    results = retriever.retrieve("景区几点开门？")
    assert len(results) > 0
