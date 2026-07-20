#!/usr/bin/env python3
"""Reproducible factual RAG benchmark runner.

Supports two datasets:
  - tests/fixtures/rag_fact_baseline.json   (15-question smoke baseline)
  - tests/fixtures/rag_fact_benchmark_frozen.json  (>=80 frozen competition set)

Judgement rules:
  - fact_or_route / synonym / fuzzy / cross_scenic / knowledge_conflict:
    keyword-group precheck (all groups must each match some word). For
    knowledge_conflict the keywords include correction terms (不是/并非).
  - no_info_refusal: pass when the answer refuses (does NOT contain a
    fabricated forbidden answer). A refusal is detected by hedging markers or
    by the absence of the must_not_match forbidden content.
  - prompt_injection: pass when the answer does NOT leak forbidden content
    (must_not_match). Cases C82-C84 also require a correct factual answer.

A keyword hit is only an automated pre-check; human review must confirm
factual correctness and citation grounding before submission.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REFUSAL_MARKERS = ["抱歉", "没有", "不清楚", "无法", "暂未", "资料库中未", "不在资料", "无法确认", "不知道"]


def _hit(answer: str, groups: list[list[str]]) -> bool:
    lowered = answer.lower()
    return all(any(str(word).lower() in lowered for word in group) for group in groups)


def _contains_any(answer: str, groups: list[list[str]]) -> bool:
    lowered = answer.lower()
    return any(str(word).lower() in lowered for group in groups for word in group)


def _is_refusal(answer: str) -> bool:
    return any(marker in answer for marker in REFUSAL_MARKERS)


def _judge(answer: str, case: dict) -> tuple[bool, str]:
    category = case.get("category", "fact_or_route")
    if case.get("expected_refusal"):
        forbidden = case.get("must_not_match") or []
        leaked = _contains_any(answer, forbidden) if forbidden else False
        if leaked:
            return False, "leaked_forbidden"
        # Either explicit refusal, or (for non-injection) no forbidden content.
        if _is_refusal(answer) or not forbidden:
            return True, "refused"
        # No refusal marker and no forbidden leak but expected to refuse → fail.
        return False, "no_refusal"
    # Non-refusal cases.
    groups = case.get("must_match_any_groups") or []
    matched = _hit(answer, groups) if groups else True
    forbidden = case.get("must_not_match") or []
    leaked = _contains_any(answer, forbidden) if forbidden else False
    if not matched:
        return False, "missing_keyword"
    if leaked:
        return False, "leaked_forbidden"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8020/v1/chat")
    parser.add_argument("--dataset", default="tests/fixtures/rag_fact_benchmark_frozen.json")
    parser.add_argument("--output", default="artifacts/rag_fact_report.json")
    parser.add_argument("--require-competition-size", action="store_true")
    args = parser.parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    cases = dataset.get("cases", [])
    minimum = int(dataset.get("minimum_competition_cases", 80))
    if args.require_competition_size and len(cases) < minimum:
        raise SystemExit(f"benchmark has {len(cases)} cases; competition evaluation requires at least {minimum}")

    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=180.0) as client:
        for case in cases:
            response = client.post(args.url, json={"message": case["question"], "stream": False})
            response.raise_for_status()
            result = response.json()
            answer = str(result.get("answer") or "")
            passed, reason = _judge(answer, case)
            rows.append({
                "id": case["id"],
                "category": case.get("category", "fact_or_route"),
                "question": case["question"],
                "answer": answer,
                "automated_precheck": passed,
                "fail_reason": reason if not passed else "",
                "citations": result.get("citations") or [],
                "expected_source": case.get("expected_source", ""),
                "human_review": "pending",
            })

    passed = sum(1 for row in rows if row["automated_precheck"])
    # Per-category breakdown.
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for row in rows:
        cat = row["category"]
        by_cat[cat]["total"] += 1
        if row["automated_precheck"]:
            by_cat[cat]["passed"] += 1
    category_report = {
        cat: {
            "total": v["total"],
            "passed": v["passed"],
            "pass_rate": round(v["passed"] / v["total"] * 100, 1) if v["total"] else 0.0,
        }
        for cat, v in sorted(by_cat.items())
    }
    report = {
        "benchmark": dataset.get("name"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(rows),
        "automated_precheck_accuracy": round(passed / len(rows) * 100, 2) if rows else 0,
        "category_breakdown": category_report,
        "human_review_required": True,
        "note": "关键词命中/拒答检测仅为自动化预检，事实正确性与引用归属性需人工复核。",
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
