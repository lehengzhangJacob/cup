#!/usr/bin/env python3
"""(Re)build the CLIP reference-image vector index from manifest.json.

Run from the softcup env so the CLIP socket service can be reached, or set
CLIP_MODE=disabled to just clear the index. Examples:

    python scripts/build_vision_index.py            # incremental (reuse existing vectors)
    python scripts/build_vision_index.py --force    # full rebuild
    python scripts/build_vision_index.py --attraction LS-011
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the app package importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import vision_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-encode every reference image")
    parser.add_argument("--attraction", default="", help="limit to one attraction_id")
    args = parser.parse_args()

    result = vision_index.build(force=args.force, attraction_id=args.attraction or None)
    print("vision index build result:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    if result.get("indexed", 0) == 0:
        print("提示：尚无参考图。请按 data/lingshan/vision_eval/README.md 采集后重跑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
