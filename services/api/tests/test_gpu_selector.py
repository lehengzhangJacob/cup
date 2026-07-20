from __future__ import annotations

import importlib.util
from pathlib import Path


SELECTOR_PATH = Path(__file__).resolve().parents[3] / "deploy" / "select_free_gpu.py"
SPEC = importlib.util.spec_from_file_location("select_free_gpu", SELECTOR_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_selects_gpu_with_most_free_memory():
    selected = MODULE.select_gpu(
        [
            {"index": 0, "free_mb": 22000, "utilization": 70},
            {"index": 1, "free_mb": 19000, "utilization": 0},
            {"index": 2, "free_mb": 23500, "utilization": 25},
            {"index": 3, "free_mb": 17000, "utilization": 0},
        ],
        candidates=(0, 1, 2, 3),
        min_free_mb=18000,
    )
    assert selected["index"] == 2


def test_utilization_breaks_equal_free_memory_tie():
    selected = MODULE.select_gpu(
        [
            {"index": 2, "free_mb": 23000, "utilization": 40},
            {"index": 3, "free_mb": 23000, "utilization": 5},
        ],
        candidates=(2, 3),
        min_free_mb=18000,
    )
    assert selected["index"] == 3


def test_rejects_candidates_below_memory_threshold():
    try:
        MODULE.select_gpu(
            [{"index": 0, "free_mb": 12000, "utilization": 0}],
            candidates=(0,),
            min_free_mb=18000,
        )
    except RuntimeError as exc:
        assert "18000 MiB" in str(exc)
    else:
        raise AssertionError("low-memory GPU should not be selected")


def test_explicit_gpu_override_still_checks_free_memory():
    selected = MODULE.select_gpu(
        [
            {"index": 1, "free_mb": 21000, "utilization": 80},
            {"index": 2, "free_mb": 24000, "utilization": 0},
        ],
        candidates=(0, 1, 2, 3),
        min_free_mb=18000,
        requested=1,
    )
    assert selected["index"] == 1
