"""Turn a vision-model observation into verified scenic-attraction choices."""
from __future__ import annotations

import json
import re
from typing import Any

from .attractions import attraction_catalog


def scenic_candidates() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for area in attraction_catalog():
        for item in area["children"]:
            if item["is_overall"]:
                continue
            rows.append(
                {
                    "id": str(item["id"]),
                    "name": str(item["name"]),
                    "scenic_area": str(area["name"]),
                }
            )
    return rows


def vision_prompt() -> str:
    landmarks = "、".join(item["name"] for item in scenic_candidates())
    return (
        "你是景区视觉识别助手。仅根据图片可见内容，识别可能的景点；"
        "不要把不确定的猜测说成事实。候选名称只能从以下名单选择："
        f"{landmarks}。"
        "只返回 JSON，不要 Markdown，格式为："
        '{"summary":"可见特征的简短描述","candidates":['
        '{"name":"候选景点名","confidence":0.0,"evidence":"图中依据"}'
        "]}。最多给出三个候选；没有把握时 candidates 为空。"
    )


def _json_object(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    candidates = [text, *re.findall(r"\{[\s\S]*\}", text)]
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _confidence(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value or "").strip().lower()
    if text in {"高", "high"}:
        return 0.85
    if text in {"中", "medium"}:
        return 0.62
    if text in {"低", "low"}:
        return 0.35
    return fallback


def parse_vision_observation(raw: str) -> dict[str, Any]:
    """Validate model-proposed names against the local attraction registry."""
    parsed = _json_object(raw)
    known = {item["name"]: item for item in scenic_candidates()}
    source_candidates = parsed.get("candidates", []) if parsed else []
    if not isinstance(source_candidates, list):
        source_candidates = []

    selected: dict[str, dict[str, Any]] = {}
    for proposed in source_candidates:
        if isinstance(proposed, str):
            name, confidence, evidence = proposed, 0.58, "视觉模型候选"
        elif isinstance(proposed, dict):
            name = str(proposed.get("name") or proposed.get("landmark") or "").strip()
            confidence = _confidence(proposed.get("confidence"), 0.58)
            evidence = str(proposed.get("evidence") or proposed.get("reason") or "视觉模型候选").strip()
        else:
            continue
        if name in known:
            selected[name] = {
                **known[name],
                "confidence": round(confidence, 2),
                "evidence": evidence[:180],
            }

    # Some providers still return prose despite being asked for JSON.  A name
    # appearing in prose is useful but deliberately remains a medium candidate.
    if not selected:
        for name, item in known.items():
            if name in str(raw):
                selected[name] = {
                    **item,
                    "confidence": 0.6,
                    "evidence": "模型描述中提及该景点，待游客确认",
                }

    candidates = sorted(selected.values(), key=lambda item: item["confidence"], reverse=True)[:3]
    top = candidates[0] if candidates else None
    high_confidence = bool(top and top["confidence"] >= 0.82 and len(candidates) == 1)
    summary = str((parsed or {}).get("summary") or raw or "未获得可用的视觉描述").strip()
    return {
        "summary": summary[:800],
        "candidates": candidates,
        "confidence": "high" if high_confidence else ("medium" if candidates else "low"),
        "requires_confirmation": not high_confidence,
    }
