"""On-disk CLIP reference-image vector index for vision recall.

The index is a derived artifact: ``manifest.json`` (managed by vision_gallery)
is the source of truth, and this module rebuilds vectors from it on demand.
N is small (a few hundred at most), so plain numpy cosine search is enough —
no FAISS dependency. The API process owns this index; the softcup CLIP service
only encodes images into vectors.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from . import config

log = logging.getLogger(__name__)


def _index_path() -> Path:
    return config.VISION_INDEX_PATH


def _empty() -> dict[str, Any]:
    return {"vectors": np.zeros((0, 0), dtype=np.float32), "files": [], "attraction_ids": [], "model": "", "dim": 0}


def _load() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return _empty()
    try:
        with np.load(path, allow_pickle=False) as data:
            vectors = data["vectors"]
            files = list(data["files"].tolist())
            attraction_ids = list(data["attraction_ids"].tolist())
            model = str(data["model"].item() if data["model"].shape == () else data["model"][0])
            dim = int(data["dim"].item() if data["dim"].shape == () else data["dim"][0])
        return {"vectors": vectors.astype(np.float32), "files": files, "attraction_ids": attraction_ids, "model": model, "dim": dim}
    except (OSError, ValueError, KeyError) as exc:
        log.warning("vision index load failed, treating as empty: %s", exc)
        return _empty()


def _save(state: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    vectors = state["vectors"].astype(np.float32)
    # np.savez appends .npz to path-like names, so write to an open temporary
    # file and atomically replace the index. Unicode arrays remain compatible
    # with allow_pickle=False during loading.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as output:
        np.savez(
            output,
            vectors=vectors,
            files=np.asarray(state["files"], dtype=np.str_),
            attraction_ids=np.asarray(state["attraction_ids"], dtype=np.str_),
            model=np.asarray(str(state["model"]), dtype=np.str_),
            dim=np.asarray(int(state["dim"]), dtype=np.int64),
        )
    tmp.replace(path)


def status() -> dict[str, Any]:
    state = _load()
    vectors = state["vectors"]
    count = int(vectors.shape[0]) if vectors.size else 0
    return {
        "healthy": True,
        "vectors": count,
        "dim": int(state["dim"]),
        "model": state["model"],
        "matches_manifest_model": state["model"] == config.CLIP_MODEL if count else True,
    }


def search(query_vec: np.ndarray, top_k: int) -> list[dict[str, Any]]:
    """Return Top-K cosine hits for a query vector (already L2-normalized)."""
    state = _load()
    vectors = state["vectors"]
    if vectors.size == 0 or vectors.shape[0] == 0:
        return []
    if query_vec is None:
        return []
    q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    if q.shape[0] != vectors.shape[1]:
        log.warning("vision index dim mismatch: query=%d index=%d", q.shape[0], vectors.shape[1])
        return []
    sims = vectors @ q  # both L2-normalized → cosine
    k = min(top_k, sims.shape[0])
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    from .attractions import attraction_by_id

    hits: list[dict[str, Any]] = []
    for idx in top:
        attraction_id = state["attraction_ids"][idx]
        attraction = attraction_by_id(attraction_id)
        hits.append(
            {
                "attraction_id": attraction_id,
                "name": attraction["name"] if attraction else attraction_id,
                "file": state["files"][idx],
                "sim": round(float(sims[idx]), 4),
            }
        )
    return hits


def upsert_vector(file: str, vec: np.ndarray, attraction_id: str) -> None:
    state = _load()
    vectors = state["vectors"]
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    dim = int(vec.shape[0])
    # Drop any existing row for the same file, then append.
    keep = [i for i, f in enumerate(state["files"]) if f != file]
    if keep:
        vectors = vectors[keep]
        files = [state["files"][i] for i in keep]
        attraction_ids = [state["attraction_ids"][i] for i in keep]
    else:
        vectors = np.zeros((0, dim), dtype=np.float32)
        files = []
        attraction_ids = []
    vectors = np.vstack([vectors, vec.reshape(1, -1)]) if vectors.size else vec.reshape(1, -1)
    files.append(file)
    attraction_ids.append(attraction_id)
    _save({"vectors": vectors, "files": files, "attraction_ids": attraction_ids, "model": config.CLIP_MODEL, "dim": dim})


def remove_vector(file: str) -> None:
    state = _load()
    if not state["files"]:
        return
    keep = [i for i, f in enumerate(state["files"]) if f != file]
    if len(keep) == len(state["files"]):
        return
    vectors = state["vectors"][keep] if keep else np.zeros((0, state["dim"]), dtype=np.float32)
    files = [state["files"][i] for i in keep]
    attraction_ids = [state["attraction_ids"][i] for i in keep]
    _save({"vectors": vectors, "files": files, "attraction_ids": attraction_ids, "model": state["model"], "dim": state["dim"]})


def build(*, force: bool = False, attraction_id: str | None = None) -> dict[str, Any]:
    """(Re)build the index from manifest.json by encoding every reference image."""
    from .vision_gallery import _load_manifest, _refs_dir  # type: ignore[attr-defined]
    from . import vision_clip_client

    manifest = _load_manifest()
    items = manifest["items"]
    if attraction_id:
        items = [it for it in items if str(it.get("attraction_id")) == attraction_id]

    state = _load()
    indexed: dict[str, str] = {f: aid for f, aid in zip(state["files"], state["attraction_ids"])}

    files: list[str] = []
    attraction_ids: list[str] = []
    vectors_list: list[np.ndarray] = []
    skipped = 0
    for item in items:
        file = str(item.get("file") or "")
        aid = str(item.get("attraction_id") or "")
        target = _refs_dir() / file
        if not target.is_file():
            skipped += 1
            continue
        if not force and file in indexed and state["model"] == config.CLIP_MODEL and state["dim"]:
            # Reuse existing vector.
            idx = state["files"].index(file)
            vectors_list.append(state["vectors"][idx])
        else:
            vec = vision_clip_client.encode_image(target.read_bytes())
            if vec is None:
                skipped += 1
                continue
            vectors_list.append(np.asarray(vec, dtype=np.float32).reshape(-1))
        files.append(file)
        attraction_ids.append(aid)

    if vectors_list:
        dim = int(vectors_list[0].shape[0])
        vectors = np.vstack([v.reshape(1, -1) for v in vectors_list]).astype(np.float32)
    else:
        vectors = np.zeros((0, 0), dtype=np.float32)
        dim = 0
    _save({"vectors": vectors, "files": files, "attraction_ids": attraction_ids, "model": config.CLIP_MODEL, "dim": dim})
    return {"indexed": len(files), "skipped": skipped, "total": len(files), "model": config.CLIP_MODEL, "dim": dim}
