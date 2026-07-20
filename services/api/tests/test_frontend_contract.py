"""Fast, dependency-free contracts for the visitor demo page."""
from __future__ import annotations

import re
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def _visitor_html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_visitor_script_does_not_reference_missing_elements():
    html = _visitor_html()
    live_markup = re.sub(r"<!--[\s\S]*?-->", "", html)
    ids = set(re.findall(r'\bid=["\']([^"\']+)', live_markup))
    helper_refs = set(re.findall(r'\$\(["\']([^"\']+)["\']\)', html))
    dom_refs = set(
        re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', html)
    )

    assert (helper_refs | dom_refs) - ids == set()


def test_vision_confirmation_is_wired_to_the_backend_contract():
    html = _visitor_html()

    assert '"/v1/vision/confirm"' in html
    assert "model_candidates:" in html
    assert "image_sha256:" in html
    assert "confirmVisionAttraction" in html
    assert "确认并纠错" in html


def test_visitor_name_comes_from_public_avatar_profile():
    html = _visitor_html()

    assert '"/v1/avatar"' in html
    assert "applyGuideName(data.display_name)" in html
    assert 'id="guideTitle"' in html


def test_visitor_exposes_lightweight_local_model_and_visible_gpu_errors():
    html = _visitor_html()

    assert '<option value="local_lite">轻量本地 Qwen3-1.7B</option>' in html
    assert "模型显存不足" in html
    assert '["cloud", "local_lite", "local"]' in html


def test_admin_avatar_form_only_exposes_runtime_backed_settings():
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")

    assert 'id="displayName"' in html
    assert 'id="voiceName"' in html
    assert 'id="avatarId"' in html
    assert 'id="costume"' not in html
    assert 'id="expression"' not in html
    assert "服装风格" not in html
    assert "默认表情" not in html
    assert 'costume:$("costume")' not in html
    assert 'expression:$("expression")' not in html


def test_admin_demo_data_is_labeled_and_reversible():
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")

    assert 'id="seedDemoData"' in html
    assert 'id="clearDemoData"' in html
    assert 'id="demoDataBadge"' in html
    assert 'api("/v1/admin/demo-data",{method:"POST"})' in html
    assert 'api("/v1/admin/demo-data",{method:"DELETE"})' in html
    assert "均为合成数据" in html
