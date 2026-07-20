"""Admin-managed, attribution-preserving landmark reference gallery."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config
from .attractions import attraction_by_id, attraction_catalog
from .image_processing import PreparedImage, normalize_scenic_image

log = logging.getLogger(__name__)

_MANIFEST = "manifest.json"
_CORRECTIONS = "corrections.jsonl"  # 纠错样本记录


def _refs_dir() -> Path:
    # Read dynamically so tests that monkeypatch config.VISION_REFERENCES_DIR
    # are honored (the previous module-level import leaked writes into the real
    # data directory and polluted corrections.jsonl / manifest.json).
    return config.VISION_REFERENCES_DIR


def _manifest_path() -> Path:
    return _refs_dir() / _MANIFEST


def _load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"version": 1, "items": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": []}
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else {"version": 1, "items": []}


def _save_manifest(payload: dict[str, Any]) -> None:
    _refs_dir().mkdir(parents=True, exist_ok=True)
    temporary = _manifest_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(_manifest_path())


def _index_status() -> dict[str, Any]:
    """Best-effort read of the CLIP vector index status (may not exist)."""
    try:
        from . import vision_index  # local import: torch/numpy isolated
        return vision_index.status()
    except Exception as exc:  # noqa: BLE001 - index is optional
        return {"healthy": False, "reason": str(exc), "vectors": 0}


def _upsert_index_vector(relative: str, data: bytes, attraction_id: str) -> dict[str, Any]:
    try:
        from . import vision_clip_client, vision_index
        vec = vision_clip_client.encode_image(data)
        if vec is None:
            return {
                "ok": False,
                "reason": "CLIP 编码服务当前不可用，参考图已保存但尚未写入召回索引",
            }
        vision_index.upsert_vector(relative, vec, attraction_id)
        return {"ok": True, "file": relative, "index": vision_index.status()}
    except Exception as exc:  # noqa: BLE001 - index update must never block the gallery
        log.warning("clip index upsert failed for %s: %s", relative, exc)
        return {
            "ok": False,
            "reason": f"参考图已保存，但召回索引更新失败：{exc}",
        }


def _remove_index_vector(relative: str) -> None:
    try:
        from . import vision_index
        vision_index.remove_vector(relative)
    except Exception as exc:  # noqa: BLE001
        log.warning("clip index remove failed for %s: %s", relative, exc)


def gallery_summary() -> dict[str, Any]:
    items = _load_manifest()["items"]
    counts: dict[str, int] = {}
    coverage: dict[str, int] = {}

    for item in items:
        attraction_id = str(item.get("attraction_id") or "")
        if attraction_id and (_refs_dir() / str(item.get("file") or "")).is_file():
            counts[attraction_id] = counts.get(attraction_id, 0) + 1

    # 计算覆盖率：有参考图的景点数 / 总景点数
    total_attractions = 0
    for area in attraction_catalog():
        for item in area.get("children", []):
            if not item.get("is_overall"):
                total_attractions += 1
                attraction_id = str(item.get("id") or "")
                if attraction_id in counts:
                    coverage[attraction_id] = counts[attraction_id]

    covered = len(coverage)
    coverage_rate = round(100 * covered / total_attractions, 1) if total_attractions > 0 else 0

    # 统计参考图质量（建议 ≥5 张/景点）
    adequate = sum(1 for count in counts.values() if count >= 5)

    index_status = _index_status()
    return {
        "total": sum(counts.values()),
        "by_attraction": counts,
        "coverage": {
            "covered_count": covered,
            "total_count": total_attractions,
            "rate_percent": coverage_rate,
        },
        "quality": {
            "adequate_count": adequate,  # ≥5 张
            "inadequate_count": covered - adequate,  # <5 张
        },
        "clip_index": {
            "healthy": bool(index_status.get("healthy")),
            "indexed_vectors": int(index_status.get("vectors", 0)),
            "model": index_status.get("model", ""),
        },
    }


def add_reference(
    attraction_id: str,
    raw: bytes,
    *,
    source_url: str = "",
    note: str = "",
) -> dict[str, Any]:
    attraction = attraction_by_id(attraction_id)
    if not attraction or attraction_id.endswith("-ALL"):
        raise ValueError("请选择具体子景点")
    prepared: PreparedImage = normalize_scenic_image(raw)
    relative = Path(attraction_id) / f"{prepared.sha256[:20]}.jpg"
    target = _refs_dir() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(prepared.data)
    manifest = _load_manifest()
    items = [item for item in manifest["items"] if str(item.get("file")) != str(relative)]
    items.append({
        "attraction_id": attraction_id,
        "attraction_name": attraction["name"],
        "file": str(relative),
        "source_url": source_url.strip()[:500],
        "note": note.strip()[:300],
        "width": prepared.width,
        "height": prepared.height,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    manifest["items"] = items
    _save_manifest(manifest)
    index_update = _upsert_index_vector(str(relative), prepared.data, attraction_id)
    return {
        "ok": True,
        "reference": items[-1],
        "index_update": index_update,
        "gallery": gallery_summary(),
    }


def remove_reference(file_name: str) -> bool:
    safe = Path(file_name)
    if safe.is_absolute() or ".." in safe.parts or safe.suffix.lower() != ".jpg":
        return False
    manifest = _load_manifest()
    items = manifest["items"]
    kept = [item for item in items if str(item.get("file")) != str(safe)]
    if len(kept) == len(items):
        return False
    target = _refs_dir() / safe
    target.unlink(missing_ok=True)
    manifest["items"] = kept
    _save_manifest(manifest)
    _remove_index_vector(str(safe))
    return True


def references_for(attraction_ids: Iterable[str], *, per_attraction: int = 2) -> list[dict[str, Any]]:
    wanted = {str(value) for value in attraction_ids if value}
    if not wanted:
        return []
    selected: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for item in reversed(_load_manifest()["items"]):
        attraction_id = str(item.get("attraction_id") or "")
        target = _refs_dir() / str(item.get("file") or "")
        if attraction_id not in wanted or used.get(attraction_id, 0) >= per_attraction or not target.is_file():
            continue
        used[attraction_id] = used.get(attraction_id, 0) + 1
        selected.append({
            "attraction_id": attraction_id,
            "attraction_name": str(item.get("attraction_name") or attraction_id),
            "data": target.read_bytes(),
        })
    return selected


def list_references() -> list[dict[str, Any]]:
    result = []
    for item in _load_manifest()["items"]:
        file_name = str(item.get("file") or "")
        if (_refs_dir() / file_name).is_file():
            result.append({key: value for key, value in item.items() if key != "data"})
    return result


def record_vision_correction(
    model_candidates: list[dict[str, Any]],
    user_confirmed_id: str,
    image_sha256: str = "",
) -> None:
    """记录游客纠正视觉模型的案例，用于后续评估和微调。

    当游客确认的景点与模型首轮候选不一致时调用。
    """
    candidate_names = [c.get("name", "") for c in model_candidates]
    confirmed_name = next(
        (item["name"] for area in attraction_catalog() for item in area.get("children", [])
         if str(item.get("id")) == user_confirmed_id),
        user_confirmed_id
    )

    if confirmed_name not in candidate_names:
        # 候选为空也是一次“漏识别”，需要进入纠错样本。
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_candidates": candidate_names,
            "user_confirmed": confirmed_name,
            "image_sha256": image_sha256[:20] if image_sha256 else "",
        }
        corrections_path = _refs_dir() / _CORRECTIONS
        try:
            corrections_path.parent.mkdir(parents=True, exist_ok=True)
            with open(corrections_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except (OSError, IOError):
            pass  # 纠错记录失败不影响业务


def list_vision_corrections(limit: int = 100) -> list[dict[str, Any]]:
    """列出最近的纠错样本，用于质量评估。"""
    corrections_path = _refs_dir() / _CORRECTIONS
    if not corrections_path.exists():
        return []

    records = []
    try:
        with open(corrections_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    records.append(record)
                except json.JSONDecodeError:
                    pass
    except (OSError, IOError):
        return []

    return sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
