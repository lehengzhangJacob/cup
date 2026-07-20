"""Turn a vision-model observation into verified scenic-attraction choices."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from . import config
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


def vision_prompt(narrow_names: Iterable[str] | None = None) -> str:
    """Build the first-pass vision prompt.

    When CLIP recall returns candidate names, narrow the allow-list to them so
    the VLM chooses among visually plausible options instead of all landmarks.
    """
    all_names = "、".join(item["name"] for item in scenic_candidates())
    if narrow_names:
        names = [str(n).strip() for n in narrow_names if str(n).strip()]
        if names:
            landmarks = "、".join(names)
            allow_hint = (
                "根据参考图召回，候选范围已缩小为以下最可能的景点。"
                f"候选名称只能从以下名单选择：{landmarks}。"
            )
        else:
            landmarks = all_names
            allow_hint = f"候选名称只能从以下名单选择：{landmarks}。"
    else:
        allow_hint = f"候选名称只能从以下名单选择：{all_names}。"
    return (
        "你是景区视觉识别助手。仅根据图片可见内容，识别可能的景点；"
        "不要把不确定的猜测说成事实。"
        + allow_hint
        + "只返回 JSON，不要 Markdown，格式为："
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


def parse_vision_observation(
    raw: str, *, location_attraction_id: str | None = None
) -> dict[str, Any]:
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
                "source": "vision_model",  # 标记来源便于二阶追踪
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
                    "source": "vision_prose",
                }

    # A QR/manual/GPS-confirmed point is only a prior, never a substitute for
    # visual evidence. It can surface the correct local candidate but still
    # requires confirmation unless the image itself is decisive.
    if location_attraction_id:
        location_item = next(
            (item for item in known.values() if item["id"] == location_attraction_id),
            None,
        )
        if location_item:
            current = selected.get(location_item["name"])
            if current:
                boost = config.VISION_LOCATION_PRIOR_BOOST
                cap = config.VISION_LOCATION_PRIOR_CAP
                current["confidence"] = round(min(cap, current["confidence"] + boost), 2)
                current["evidence"] = (current["evidence"] + "；与当前位置一致")[:180]
                current["source"] = current.get("source", "vision_model") + "+location"
            elif not selected:
                selected[location_item["name"]] = {
                    **location_item,
                    "confidence": 0.45,
                    "evidence": "来自当前位置先验，尚需图片或游客确认",
                    "source": "location_prior",
                }

    candidates = sorted(selected.values(), key=lambda item: item["confidence"], reverse=True)[:3]
    summary = str((parsed or {}).get("summary") or raw or "未获得可用的视觉描述").strip()
    decision = decide_confidence(candidates)
    return {
        "summary": summary[:800],
        "candidates": candidates,
        "confidence": decision["confidence"],
        "requires_confirmation": decision["requires_confirmation"],
    }


def decide_confidence(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply config-driven thresholds to a merged candidate list.

    - 单候选 >= VISION_HIGH_CONFIDENCE：high
    - 多候选且首选 >= VISION_MEDIUM_CONFIDENCE 且与次选分差 > VISION_MARGIN：medium
    - 其他：low，需游客确认
    """
    if not candidates:
        return {"confidence": "low", "requires_confirmation": True}
    top = candidates[0]
    high = bool(
        top["confidence"] >= config.VISION_HIGH_CONFIDENCE and len(candidates) == 1
    )
    medium = bool(
        len(candidates) > 1
        and top["confidence"] >= config.VISION_MEDIUM_CONFIDENCE
        and candidates[1]["confidence"] < top["confidence"] - config.VISION_MARGIN
    )
    level = "high" if high else ("medium" if medium else "low")
    return {"confidence": level, "requires_confirmation": not (high or medium)}


def _clip_hits_as_candidates(clip_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize CLIP recall hits (attraction_id/sim/name) into candidates."""
    known_by_id = {item["id"]: item for item in scenic_candidates()}
    out: dict[str, dict[str, Any]] = {}
    for hit in clip_hits or []:
        attraction_id = str(hit.get("attraction_id") or hit.get("id") or "").strip()
        if not attraction_id:
            continue
        item = known_by_id.get(attraction_id)
        if not item:
            continue
        sim = max(0.0, min(1.0, float(hit.get("sim") or hit.get("score") or 0.0)))
        if sim < config.CLIP_MIN_SIM:
            continue
        # Map cosine similarity (~0.2-1.0) into a comparable confidence band.
        conf = round(0.35 + 0.6 * max(0.0, (sim - config.CLIP_MIN_SIM) / max(1e-6, 1.0 - config.CLIP_MIN_SIM)), 2)
        out[item["name"]] = {
            **item,
            "confidence": conf,
            "evidence": f"参考图召回相似度 {sim:.2f}",
            "source": "clip_recall",
            "sim": round(sim, 3),
        }
    return list(out.values())


def merge_candidates(
    clip_hits: list[dict[str, Any]],
    vlm_obs: dict[str, Any],
    *,
    location_id: str | None = None,
    quality_flag: str = "accept",
    prior_merge: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fuse CLIP recall and VLM candidates with a prior-prior/location boost.

    Same-name candidates are de-duplicated by taking the max fused confidence
    and recording the contributing sources. When ``prior_merge`` is supplied
    (the pre-verification merged list) the verification candidates are merged
    on top of it so CLIP side-evidence is never lost.
    """
    blend_clip = config.CLIP_BLEND_CLIP
    blend_vlm = config.CLIP_BLEND_VLM
    total = blend_clip + blend_vlm
    if total <= 0:
        blend_clip, blend_vlm, total = 0.4, 0.6, 1.0

    merged: dict[str, dict[str, Any]] = {}

    def _upsert(cand: dict[str, Any], source: str) -> None:
        name = cand["name"]
        existing = merged.get(name)
        if existing is None:
            merged[name] = {**cand, "sources": [source]}
        else:
            existing["sources"] = sorted(set(existing.get("sources", []) + [source]))

    # Seed with prior merge (pre-verification state) when re-merging.
    if prior_merge:
        for cand in prior_merge:
            _upsert(cand, str(cand.get("source") or "prior"))

    # CLIP recall candidates.
    for cand in _clip_hits_as_candidates(clip_hits):
        _upsert(cand, "clip_recall")

    # VLM candidates.
    for cand in vlm_obs.get("candidates", []) or []:
        _upsert(cand, str(cand.get("source") or "vision_model"))

    # Fuse: if a name has both CLIP and VLM evidence, blend; else keep its own.
    fused: list[dict[str, Any]] = []
    for name, cand in merged.items():
        sources = cand.get("sources", [])
        clip_c = next((c for c in _clip_hits_as_candidates(clip_hits) if c["name"] == name), None)
        vlm_c = next((c for c in (vlm_obs.get("candidates", []) or []) if c.get("name") == name), None)
        prior_c = None
        if prior_merge:
            prior_c = next((c for c in prior_merge if c.get("name") == name), None)

        if clip_c and vlm_c:
            conf = round((clip_c["confidence"] * blend_clip + vlm_c["confidence"] * blend_vlm) / total, 2)
        elif clip_c:
            conf = clip_c["confidence"]
        elif vlm_c:
            conf = vlm_c["confidence"]
        elif prior_c:
            conf = prior_c["confidence"]
        else:
            conf = cand["confidence"]

        # Location prior boost (only when the location actually matches).
        if location_id and cand.get("id") == location_id:
            conf = round(min(config.VISION_LOCATION_PRIOR_CAP, conf + config.VISION_LOCATION_PRIOR_BOOST), 2)

        # Quality penalty.
        if quality_flag == "warn":
            conf = round(conf * config.VISION_QUALITY_WARN_FACTOR, 2)
        elif quality_flag == "reject":
            conf = round(conf * config.VISION_QUALITY_WARN_FACTOR, 2)

        fused.append({**cand, "confidence": conf, "sources": sources})

    fused.sort(key=lambda item: item["confidence"], reverse=True)
    return fused[:3]


def demote_after_refutation(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the refutation penalty when reference verification returns empty.

    A legally-empty verification result means the VLM looked at the local
    reference images and could not match any of them to the upload. That is a
    negative signal: demote all candidates and force confirmation.
    """
    factor = config.VISION_REFUTATION_FACTOR
    demoted: list[dict[str, Any]] = []
    for cand in candidates:
        new = dict(cand)
        new["confidence"] = round(min(0.6, cand["confidence"] * factor), 2)
        new["sources"] = sorted(set(new.get("sources", []) + ["refuted"]))
        new["evidence"] = (str(new.get("evidence", "")) + "；参考图复核未通过").strip("；")[:180]
        demoted.append(new)
    return demoted


def demote_after_error(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply a softer penalty when verification errored (uncertain, not refuted)."""
    factor = config.VISION_ERROR_FACTOR
    out: list[dict[str, Any]] = []
    for cand in candidates:
        new = dict(cand)
        new["confidence"] = round(cand["confidence"] * factor, 2)
        out.append(new)
    return out
