from __future__ import annotations

from pathlib import Path


IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".webp"}


def list_avatar_ids(avatar_root: Path, fallback: str) -> list[str]:
    if not avatar_root.exists():
        return [fallback]
    avatar_ids = sorted(path.name for path in avatar_root.iterdir() if path.is_dir())
    return avatar_ids or [fallback]


def find_avatar_preview(avatar_root: Path, avatar_id: str) -> Path | None:
    avatar_dir = avatar_root / avatar_id
    if avatar_dir.resolve().parent != avatar_root.resolve() or not avatar_dir.is_dir():
        return None

    root_images = sorted(
        path
        for path in avatar_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    for preferred_name in ("preview.png", "preview.jpg", "preview.jpeg", "preview.webp"):
        preferred = avatar_dir / preferred_name
        if preferred in root_images:
            return preferred
    if root_images:
        return root_images[0]

    for frame_dir_name in ("full_imgs", "face_imgs"):
        frame_dir = avatar_dir / frame_dir_name
        if not frame_dir.is_dir():
            continue
        frames = sorted(
            path
            for path in frame_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        if frames:
            return frames[len(frames) // 2]
    return None
