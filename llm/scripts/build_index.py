import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.index_builder import build_index


def main():
    result = build_index()
    print(
        "Index saved: "
        f"{result['chunk_count']} vectors, dimension={result['embedding_dimension']}"
    )


if __name__ == "__main__":
    main()
