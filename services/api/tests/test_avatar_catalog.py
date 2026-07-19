from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.avatar_catalog import find_avatar_preview, list_avatar_ids


class AvatarCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.avatar_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_lists_avatar_directories_in_stable_order(self):
        (self.avatar_root / "guide_b").mkdir()
        (self.avatar_root / "guide_a").mkdir()
        (self.avatar_root / "ignored.txt").write_text("not an avatar", encoding="utf-8")

        self.assertEqual(
            list_avatar_ids(self.avatar_root, "fallback"),
            ["guide_a", "guide_b"],
        )

    def test_prefers_explicit_preview_over_generated_frames(self):
        avatar_dir = self.avatar_root / "guide"
        frame_dir = avatar_dir / "full_imgs"
        frame_dir.mkdir(parents=True)
        (frame_dir / "0001.png").write_bytes(b"frame")
        preview = avatar_dir / "preview.png"
        preview.write_bytes(b"preview")

        self.assertEqual(find_avatar_preview(self.avatar_root, "guide"), preview)

    def test_uses_middle_full_frame_and_rejects_path_traversal(self):
        frame_dir = self.avatar_root / "guide" / "full_imgs"
        frame_dir.mkdir(parents=True)
        for name in ("0001.png", "0002.png", "0003.png"):
            (frame_dir / name).write_bytes(name.encode())

        self.assertEqual(
            find_avatar_preview(self.avatar_root, "guide"),
            frame_dir / "0002.png",
        )
        self.assertIsNone(find_avatar_preview(self.avatar_root, "../guide"))
