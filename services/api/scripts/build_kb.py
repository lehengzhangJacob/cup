#!/usr/bin/env python3
"""Build knowledge chunks from official docx (no embeddings)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.kb import kb  # noqa: E402


def main() -> None:
    n = kb.rebuild_from_docs()
    print(f"built {n} chunks -> {kb}")
    from app.config import KB_PATH

    print(KB_PATH)


if __name__ == "__main__":
    main()
