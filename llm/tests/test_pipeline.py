# tests/test_pipeline.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from rag.pipeline import RAGPipeline


@pytest.fixture(scope="module")
def pipeline():
    return RAGPipeline()


def test_pipeline_returns_string(pipeline):
    answer = pipeline.query("灵山大佛是用什么材料建造的？")
    assert isinstance(answer, str)
    assert len(answer) > 10


def test_pipeline_factual_bronze(pipeline):
    answer = pipeline.query("灵山大佛是用什么材料建造的？")
    assert "青铜" in answer


def test_pipeline_opening_hours(pipeline):
    answer = pipeline.query("景区几点开门？")
    assert isinstance(answer, str)
    assert len(answer) > 5


def test_pipeline_route_recommendation(pipeline):
    answer = pipeline.query("我对历史文化感兴趣，推荐什么游览路线？")
    assert isinstance(answer, str)
    assert len(answer) > 20
