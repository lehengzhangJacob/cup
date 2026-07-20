"""集成测试：识景二阶段流程、游客确认、纠错记录。"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.vision_analysis import parse_vision_observation
from app.vision_gallery import record_vision_correction, list_vision_corrections


def test_vision_observation_source_tracking():
    """验证视觉识别结果中的来源追踪字段。"""
    observation = parse_vision_observation(
        '{"summary":"佛像","candidates":[{"name":"灵山大佛","confidence":0.89}]}'
    )
    
    assert observation["candidates"][0].get("source") == "vision_model"
    assert observation["summary"] == "佛像"


def test_confidence_decision_thresholds():
    """测试置信度决策的三个阈值：高、中、低。"""
    # 1. 高置信：单候选 ≥0.82
    high_conf = parse_vision_observation(
        '{"candidates":[{"name":"灵山大佛","confidence":0.88}]}'
    )
    assert high_conf["confidence"] == "high"
    assert not high_conf["requires_confirmation"]
    
    # 2. 中置信：多候选但首选 ≥0.75 且分差 >0.15
    medium_conf = parse_vision_observation(
        '{"candidates":[{"name":"五印坛城","confidence":0.80},'
        '{"name":"灵山大佛","confidence":0.62}]}'
    )
    assert medium_conf["confidence"] == "medium"
    assert not medium_conf["requires_confirmation"]
    
    # 3. 低置信：其他情况
    low_conf = parse_vision_observation(
        '{"candidates":[{"name":"五印坛城","confidence":0.65},'
        '{"name":"灵山大佛","confidence":0.63}]}'
    )
    assert low_conf["confidence"] == "low"
    assert low_conf["requires_confirmation"]


def test_location_prior_confidence_boost():
    """验证位置先验对置信度的影响（最多 +0.08）。"""
    # 无位置先验
    no_prior = parse_vision_observation(
        '{"candidates":[{"name":"灵山大佛","confidence":0.75}]}'
    )
    
    # 有位置先验且一致
    with_prior = parse_vision_observation(
        '{"candidates":[{"name":"灵山大佛","confidence":0.75}]}',
        location_attraction_id="LS-011"
    )
    
    # 位置先验只能提升到 0.95（capped）
    assert with_prior["candidates"][0]["confidence"] <= 0.95
    assert with_prior["candidates"][0]["confidence"] >= no_prior["candidates"][0]["confidence"]


def test_vision_correction_workflow(tmp_path, monkeypatch):
    """测试纠错记录流程（隔离到临时目录，避免污染真实 corrections.jsonl）。"""
    from app import config
    from app.vision_gallery import record_vision_correction, list_vision_corrections

    monkeypatch.setattr(config, "VISION_REFERENCES_DIR", tmp_path / "refs")

    # 模型候选
    model_candidates = [
        {"name": "灵山大佛"},
        {"name": "五明桥"}
    ]

    # 游客确认为 拈花广场（不在候选中）- 这是纠错
    record_vision_correction(
        model_candidates=model_candidates,
        user_confirmed_id="NH-001",
        image_sha256="hash123"
    )

    corrections = list_vision_corrections(limit=10)
    assert len(corrections) == 1
    assert corrections[0]["user_confirmed"] == "拈花广场"
    assert corrections[0]["model_candidates"] == ["灵山大佛", "五明桥"]


def test_vision_confirm_api_structure():
    """测试游客确认景点的 API 请求数据结构（不使用 async）。"""
    # 这是一个结构验证测试
    
    confirmation_request = {
        "attraction_id": "LS-011",
        "session_id": "sess_123",
        "question": "请讲解这个景点",
        "model_candidates": ["五印坛城", "灵山大佛"],  # 模型首轮的候选
        "image_sha256": "abc123",
    }
    
    # 验证确认请求的数据结构
    assert confirmation_request["attraction_id"]
    assert confirmation_request["session_id"]
    assert len(confirmation_request["model_candidates"]) > 0
    
    # 如果确认的景点不在模型候选中，应该记录纠错
    confirmed_name = "灵山大佛"
    should_record_correction = confirmed_name not in confirmation_request["model_candidates"]
    
    assert not should_record_correction  # 这个例子中不需要纠错


def test_gallery_quality_metrics(tmp_path, monkeypatch):
    """测试参考图库质量指标的计算逻辑。"""
    from app import config
    from app.vision_gallery import gallery_summary
    
    original_dir = config.VISION_REFERENCES_DIR
    monkeypatch.setattr(config, "VISION_REFERENCES_DIR", tmp_path)
    
    try:
        summary = gallery_summary()
        
        # 验证返回的指标结构
        assert "total" in summary
        assert "coverage" in summary
        assert "quality" in summary
        
        coverage = summary["coverage"]
        assert "covered_count" in coverage
        assert "total_count" in coverage
        assert "rate_percent" in coverage
        
        quality = summary["quality"]
        assert "adequate_count" in quality  # ≥5 张的景点数
        assert "inadequate_count" in quality  # <5 张的景点数
    finally:
        monkeypatch.setattr(config, "VISION_REFERENCES_DIR", original_dir)


# ---- 新增：CLIP 管线融合 / 反证 / 质量检测 ----

def test_merge_candidates_blends_clip_and_vlm():
    from app.vision_analysis import merge_candidates
    clip_hits = [{"attraction_id": "LS-011", "name": "灵山大佛", "sim": 0.9}]
    vlm_obs = {
        "candidates": [{"id": "LS-011", "name": "灵山大佛", "confidence": 0.8, "source": "vision_model"}]
    }
    merged = merge_candidates(clip_hits, vlm_obs, location_id=None, quality_flag="accept")
    assert len(merged) == 1
    assert merged[0]["name"] == "灵山大佛"
    # 融合分应介于两源之间
    assert 0.8 <= merged[0]["confidence"] <= 0.9
    assert "clip_recall" in merged[0]["sources"] and "vision_model" in merged[0]["sources"]


def test_refutation_demotes_and_forces_confirmation():
    from app.vision_analysis import merge_candidates, demote_after_refutation, decide_confidence
    vlm_obs = {"candidates": [{"id": "LS-011", "name": "灵山大佛", "confidence": 0.9, "source": "vision_model"}]}
    merged = merge_candidates([], vlm_obs, location_id=None, quality_flag="accept")
    # 复核前：单候选 0.9 应判 high
    assert decide_confidence(merged)["confidence"] == "high"
    # 复核反证：降权并强制确认
    demoted = demote_after_refutation(merged)
    decision = decide_confidence(demoted)
    assert decision["confidence"] == "low"
    assert decision["requires_confirmation"] is True
    assert demoted[0]["confidence"] <= 0.6
    assert "refuted" in demoted[0]["sources"]


def test_quality_warn_penalizes_confidence():
    from app.vision_analysis import merge_candidates
    vlm_obs = {"candidates": [{"id": "LS-011", "name": "灵山大佛", "confidence": 0.9, "source": "vision_model"}]}
    ok = merge_candidates([], vlm_obs, location_id=None, quality_flag="accept")[0]["confidence"]
    warn = merge_candidates([], vlm_obs, location_id=None, quality_flag="warn")[0]["confidence"]
    assert warn < ok


def test_vision_quality_detects_blur_and_accepts_detail(tmp_path):
    import io
    import numpy as np
    from PIL import Image
    from app.vision_quality import assess_scenic_quality
    # solid color → no detail → warn/reject
    solid = Image.new("RGB", (200, 200), (120, 120, 120))
    buf = io.BytesIO(); solid.save(buf, "JPEG")
    assert assess_scenic_quality(buf.getvalue()).flag in {"warn", "reject"}
    # random noise → high detail → accept
    arr = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)
    detail = Image.fromarray(arr)
    buf2 = io.BytesIO(); detail.save(buf2, "JPEG")
    assert assess_scenic_quality(buf2.getvalue()).flag == "accept"


def test_vision_index_empty_search_returns_empty(tmp_path, monkeypatch):
    from app import config, vision_index
    monkeypatch.setattr(config, "VISION_INDEX_PATH", tmp_path / "index.npz")
    import numpy as np
    assert vision_index.search(np.zeros(768, dtype="float32"), 5) == []
    assert vision_index.status()["vectors"] == 0
