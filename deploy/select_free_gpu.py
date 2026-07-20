#!/usr/bin/env python3
"""Select a physical GPU by free memory, with utilization as a tie-breaker."""

from __future__ import annotations

import argparse
import subprocess
from typing import Iterable


def parse_snapshot(output: str) -> list[dict[str, int]]:
    snapshot: list[dict[str, int]] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            index, free_mb, utilization = map(int, parts)
        except ValueError:
            continue
        snapshot.append(
            {"index": index, "free_mb": free_mb, "utilization": utilization}
        )
    return snapshot


def gpu_snapshot() -> list[dict[str, int]]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return parse_snapshot(completed.stdout)


def select_gpu(
    snapshot: Iterable[dict[str, int]],
    *,
    candidates: Iterable[int],
    min_free_mb: int,
    requested: int | None = None,
) -> dict[str, int]:
    allowed = set(candidates)
    available = [gpu for gpu in snapshot if gpu["index"] in allowed]
    if requested is not None:
        available = [gpu for gpu in available if gpu["index"] == requested]
        if not available:
            raise RuntimeError(
                f"Requested GPU {requested} is not present in candidates {sorted(allowed)}"
            )
    eligible = [gpu for gpu in available if gpu["free_mb"] >= min_free_mb]
    if not eligible:
        detail = ", ".join(
            f"GPU {gpu['index']}: {gpu['free_mb']} MiB free, {gpu['utilization']}% util"
            for gpu in available
        ) or "no candidate GPU detected"
        raise RuntimeError(
            f"No candidate GPU has at least {min_free_mb} MiB free ({detail})"
        )
    return max(
        eligible,
        key=lambda gpu: (gpu["free_mb"], -gpu["utilization"], -gpu["index"]),
    )


def parse_candidates(value: str) -> tuple[int, ...]:
    candidates = tuple(
        int(item.strip()) for item in value.split(",") if item.strip().isdigit()
    )
    if not candidates:
        raise ValueError("GPU candidate list is empty")
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="0,1,2,3")
    parser.add_argument("--min-free-mb", type=int, default=18000)
    parser.add_argument("--requested", default="auto")
    args = parser.parse_args()
    if args.min_free_mb <= 0:
        parser.error("--min-free-mb must be positive")
    requested_value = args.requested.strip().lower()
    requested = None if requested_value in {"", "auto"} else int(requested_value)
    selected = select_gpu(
        gpu_snapshot(),
        candidates=parse_candidates(args.candidates),
        min_free_mb=args.min_free_mb,
        requested=requested,
    )
    print(
        f"{selected['index']}\t{selected['free_mb']}\t{selected['utilization']}"
    )


if __name__ == "__main__":
    main()
