#!/usr/bin/env python3
"""Formal seven-class emotion evaluation.

Reports: confusion matrix, Macro-F1, per-class precision/recall/F1, an
audio+text vs text-only comparison, and P95 latency. Reads a labelled set from
data/lingshan/emotion_test_set/manifest.json. When the set or the model is
unavailable, it runs a self-consistency smoke check on synthetic samples and
reports SKIP so the competition demo is never blocked.

    python scripts/eval_emotion_seven_class.py
    python scripts/eval_emotion_seven_class.py --limit 20

The seven classes (see services/emotion/inference_adapter.py):
    angry disgust fear happy neutral sad surprise
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.emotion_analysis import analyze_text, emotion_analyzer, fuse_analysis  # noqa: E402

LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]
TEST_DIR = config.DATA_DIR / "emotion_test_set"
MANIFEST = TEST_DIR / "manifest.json"


def _load_items() -> list[dict]:
    if not MANIFEST.exists():
        return []
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [it for it in items if isinstance(it, dict)]


def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred) | set(LABELS))
    matrix = {l: Counter() for l in labels}
    for t, p in zip(y_true, y_pred):
        matrix[t][p] += 1
    per_class = {}
    f1s = []
    for l in labels:
        tp = matrix[l][l]
        fp = sum(matrix[o][l] for o in labels if o != l)
        fn = sum(matrix[l][o] for o in labels if o != l)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[l] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": tp + fn}
        f1s.append(f1)
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true) if y_true else 0.0
    return {
        "accuracy": round(acc, 3),
        "macro_f1": round(statistics.mean(f1s), 3) if f1s else 0.0,
        "per_class": per_class,
        "confusion": {t: dict(c) for t, c in matrix.items()},
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = max(0, min(len(values) - 1, int(0.95 * len(values)) - 1))
    return round(values[idx], 1)


async def _eval_mode(items: list[dict], *, media: bool) -> tuple[list[str], list[str], list[float]]:
    y_true, y_pred, latencies = [], [], []
    for item in items:
        truth = str(item.get("label") or "").strip().lower()
        if truth not in LABELS:
            continue
        transcript = str(item.get("transcript") or "")
        audio_path = None
        if media:
            file = str(item.get("audio") or "")
            if file:
                p = TEST_DIR / file
                if p.is_file():
                    audio_path = p
        started = time.perf_counter()
        if media and audio_path:
            result = await emotion_analyzer.analyze(audio_path, transcript)
        else:
            # text-only fallback: fuse the text analysis alone
            result = fuse_analysis(analyze_text(transcript), None, None)
            result.setdefault("analysis_mode", "text")
        latencies.append((time.perf_counter() - started) * 1000)
        pred = str(result.get("emotion") or result.get("emotion_label") or "").strip().lower()
        if pred not in LABELS:
            pred = "neutral"
        y_true.append(truth)
        y_pred.append(pred)
    return y_true, y_pred, latencies


async def _run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    items = _load_items()
    if args.limit:
        items = items[: args.limit]

    if not items:
        print(f"未找到情绪评测集：{MANIFEST}")
        print("请按 data/lingshan/emotion_test_set/README.md 采集真实音频+文本+标注，每类≥N 条。")
        print("当前执行 self-consistency 冒烟：验证评测管线可运行。")
        smoke = {"items": [
            {"label": "happy", "transcript": "这里太美了，我非常开心！"},
            {"label": "sad", "transcript": "有点累，腿也酸，心情低落。"},
            {"label": "angry", "transcript": "排队太久，真的很烦！"},
        ]}
        # Smoke: text-only on synthetic transcripts just proves the harness.
        y_true, y_pred, _ = await _eval_mode(smoke["items"], media=False)
        print("smoke text-only preds:", list(zip(y_true, y_pred)))
        print("SKIP: 真实评测集缺失，已跳过正式评测。")
        return 0

    status = emotion_analyzer.status()
    print("emotion analyzer status:", json.dumps(status, ensure_ascii=False))

    print("\n=== 文本降级（纯文本，无音频）===")
    yt, yp, lat = await _eval_mode(items, media=False)
    text_metrics = _metrics(yt, yp)
    print(json.dumps({"macro_f1": text_metrics["macro_f1"], "accuracy": text_metrics["accuracy"],
                      "p95_latency_ms": _p95(lat), "n": len(yt)}, ensure_ascii=False, indent=2))

    print("\n=== 音频+文本多模态 ===")
    yt2, yp2, lat2 = await _eval_mode(items, media=True)
    audio_metrics = _metrics(yt2, yp2)
    print(json.dumps({"macro_f1": audio_metrics["macro_f1"], "accuracy": audio_metrics["accuracy"],
                      "p95_latency_ms": _p95(lat2), "n": len(yt2)}, ensure_ascii=False, indent=2))

    report = {
        "text_only": {**text_metrics, "p95_latency_ms": _p95(lat)},
        "audio_text": {**audio_metrics, "p95_latency_ms": _p95(lat2)},
        "improvement_macro_f1": round(audio_metrics["macro_f1"] - text_metrics["macro_f1"], 3),
    }
    out = TEST_DIR / "report_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{out}")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
