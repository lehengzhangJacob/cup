#!/usr/bin/env python3
"""Top-K recall evaluation for the CLIP vision-recognition pipeline.

Reads a labelled test set from data/lingshan/vision_eval/, encodes each image
via the CLIP socket service, searches the reference index, and reports
Recall@1/3/5 plus per-attraction, per-weather and per-angle breakdowns and a
confusion matrix. Images or index missing → skip with a clear warning.

    python scripts/eval_vision_recall.py
    python scripts/eval_vision_recall.py --top-k 5 --bucket weather
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config, vision_clip_client, vision_index  # noqa: E402
from app.attractions import attraction_catalog  # noqa: E402

EVAL_DIR = config.DATA_DIR / "vision_eval"
MANIFEST = EVAL_DIR / "manifest.json"


def _load_items() -> list[dict]:
    if not MANIFEST.exists():
        return []
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [it for it in items if isinstance(it, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bucket", default="", choices=["", "weather", "angle", "season"])
    args = parser.parse_args()

    index_status = vision_index.status()
    if not index_status["vectors"]:
        print("图集为空（index.npz 无向量），跳过召回评测。请先采集参考图并运行 build_vision_index.py。")
        return 0
    if not vision_clip_client.is_available():
        print("CLIP 编码服务不可用，跳过召回评测。请先启动 deploy/start_clip_embedder.sh。")
        return 0

    items = _load_items()
    if not items:
        print(f"未找到测试集 manifest：{MANIFEST}。请按 {EVAL_DIR}/README.md 采集测试图片。")
        return 0

    top_k = args.top_k
    total = 0
    skipped = 0
    hit_at = {1: 0, 3: 0, 5: 0}
    per_attraction = defaultdict(lambda: {"total": 0, "hit1": 0})
    per_bucket = defaultdict(lambda: {"total": 0, "hit1": 0})
    confusion = defaultdict(int)

    for item in items:
        file = str(item.get("file") or "")
        truth = str(item.get("attraction_id") or "")
        path = EVAL_DIR / file
        if not path.is_file() or not truth:
            skipped += 1
            continue
        vec = vision_clip_client.encode_image(path.read_bytes())
        if vec is None:
            skipped += 1
            continue
        hits = vision_index.search(vec, top_k)
        total += 1
        predicted = hits[0]["attraction_id"] if hits else ""
        for k in (1, 3, 5):
            if any(h["attraction_id"] == truth for h in hits[:k]):
                hit_at[k] += 1
        per_attraction[truth]["total"] += 1
        if any(h["attraction_id"] == truth for h in hits[:1]):
            per_attraction[truth]["hit1"] += 1
        if args.bucket:
            key = str(item.get(args.bucket) or "unknown")
            per_bucket[key]["total"] += 1
            if any(h["attraction_id"] == truth for h in hits[:1]):
                per_bucket[key]["hit1"] += 1
        if predicted and predicted != truth:
            confusion[f"{truth} -> {predicted}"] += 1

    def rate(num, den):
        return round(100 * num / den, 1) if den else 0.0

    report = {
        "total": total,
        "skipped": skipped,
        "recall_at_1": rate(hit_at[1], total),
        "recall_at_3": rate(hit_at[3], total),
        "recall_at_5": rate(hit_at[5], total),
        "per_attraction": {
            aid: {"total": v["total"], "recall1": rate(v["hit1"], v["total"])}
            for aid, v in sorted(per_attraction.items())
        },
        "confusion_top": dict(sorted(confusion.items(), key=lambda kv: -kv[1])[:10]),
    }
    if args.bucket:
        report[f"per_{args.bucket}"] = {
            k: {"total": v["total"], "recall1": rate(v["hit1"], v["total"])}
            for k, v in sorted(per_bucket.items())
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out = EVAL_DIR / "report_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
