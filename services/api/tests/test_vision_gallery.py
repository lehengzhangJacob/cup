import json
import tempfile
from pathlib import Path

from app.vision_analysis import parse_vision_observation
from app.vision_gallery import (
    add_reference,
    gallery_summary,
    list_references,
    list_vision_corrections,
    record_vision_correction,
)
from app.image_processing import normalize_scenic_image


def test_location_prior_never_becomes_a_false_high_confidence_result():
    parsed = parse_vision_observation(
        "画面模糊，无法判断建筑", location_attraction_id="LS-011"
    )

    assert parsed["candidates"][0]["name"] == "灵山大佛"
    assert parsed["requires_confirmation"] is True
    assert parsed["confidence"] != "high"


def test_parse_vision_observation_high_confidence_single_candidate():
    """单候选高置信度（≥0.82）情况。"""
    parsed = parse_vision_observation(
        '{"summary":"大佛正面","candidates":[{"name":"灵山大佛","confidence":0.95,"evidence":"明显的佛像轮廓"}]}'
    )
    
    assert len(parsed["candidates"]) == 1
    assert parsed["candidates"][0]["name"] == "灵山大佛"
    assert parsed["confidence"] == "high"
    assert parsed["requires_confirmation"] is False


def test_parse_vision_observation_medium_confidence_with_clear_leader():
    """多候选但首选明显领先（>0.15 分差）且 ≥0.75 的中置信度。"""
    parsed = parse_vision_observation(
        '{"summary":"宝塔建筑","candidates":[{"name":"五印坛城","confidence":0.82,"evidence":"金色塔尖"},{"name":"灵山大佛","confidence":0.64,"evidence":"模糊判断"}]}'
    )
    
    assert len(parsed["candidates"]) >= 1
    assert parsed["candidates"][0]["confidence"] >= 0.75
    assert parsed["confidence"] == "medium"
    assert parsed["requires_confirmation"] is False


def test_parse_vision_observation_low_confidence_needs_confirmation():
    """多候选分差不明显或首选 <0.75 的低置信度。"""
    parsed = parse_vision_observation(
        '{"summary":"某个景点","candidates":[{"name":"五音殿","confidence":0.65,"evidence":"可能是塔"},{"name":"拈花湾禅意小镇","confidence":0.62,"evidence":"可能是建筑"}]}'
    )
    
    assert parsed["confidence"] == "low"
    assert parsed["requires_confirmation"] is True


def test_vision_correction_record_and_retrieval(tmp_path, monkeypatch):
    """测试纠错样本的记录和检索。"""
    # 临时设置 VISION_REFERENCES_DIR
    from app import config
    original_dir = config.VISION_REFERENCES_DIR
    monkeypatch.setattr(config, "VISION_REFERENCES_DIR", tmp_path / "refs")
    
    try:
        model_candidates = [{"name": "灵山大佛"}, {"name": "五印坛城"}]
        user_confirmed_id = "NH-001"  # 拈花广场（有效景点 ID）
        
        # 记录纠错
        record_vision_correction(
            model_candidates=model_candidates,
            user_confirmed_id=user_confirmed_id,
            image_sha256="abc123def456abc123def456abc123",
        )
        
        # 检索纠错记录
        corrections = list_vision_corrections(limit=10)
        assert len(corrections) > 0
        assert corrections[0]["model_candidates"] == ["灵山大佛", "五印坛城"]
        assert corrections[0]["user_confirmed"] == "拈花广场"
        # SHA256 被截断到前 20 位
        assert corrections[0]["image_sha256"] == "abc123def456abc123de"
    finally:
        monkeypatch.setattr(config, "VISION_REFERENCES_DIR", original_dir)


def test_empty_candidates_are_recorded_as_missed_recognition(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "VISION_REFERENCES_DIR", tmp_path / "refs")
    record_vision_correction(
        model_candidates=[],
        user_confirmed_id="LS-011",
        image_sha256="f" * 64,
    )

    corrections = list_vision_corrections(limit=10)
    assert len(corrections) == 1
    assert corrections[0]["model_candidates"] == []
    assert corrections[0]["user_confirmed"] == "灵山大佛"
    assert corrections[0]["image_sha256"] == "f" * 20


def test_gallery_summary_coverage_metrics(tmp_path, monkeypatch):
    """测试参考图库覆盖率和质量指标计算。"""
    from app import config
    original_dir = config.VISION_REFERENCES_DIR
    monkeypatch.setattr(config, "VISION_REFERENCES_DIR", tmp_path / "refs")
    
    try:
        # 创建测试图片
        from PIL import Image
        
        # 生成两张不同的 JPEG（不同颜色）
        for color_idx, color in enumerate(["red", "blue"]):
            img = Image.new("RGB", (100, 100), color=color)
            sample_jpg = tmp_path / f"sample_{color_idx}.jpg"
            img.save(sample_jpg)
            
            with open(sample_jpg, "rb") as f:
                raw_image = f.read()
            
            # 添加参考图
            add_reference(
                "LS-011",
                raw_image,
                source_url="https://example.com/vr",
                note=f"大佛{['正面', '侧面'][color_idx]}，{'晴天' if color_idx == 0 else '阴天'}",
            )
        
        # 检查覆盖率指标
        summary = gallery_summary()
        assert summary["total"] >= 2, f"Expected ≥2 references, got {summary['total']}"
        assert summary["coverage"]["rate_percent"] > 0
        assert summary["quality"]["adequate_count"] >= 0
    finally:
        monkeypatch.setattr(config, "VISION_REFERENCES_DIR", original_dir)
