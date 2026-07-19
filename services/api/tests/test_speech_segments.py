from __future__ import annotations

import unittest

from app.speech_segments import SpeechSegmenter


class SpeechSegmenterTests(unittest.TestCase):
    def test_emits_complete_sentences_without_metadata(self):
        segmenter = SpeechSegmenter()

        self.assertEqual(segmenter.feed("灵山大佛高八十"), [])
        self.assertEqual(
            segmenter.feed("八米。欢迎来到灵山！"),
            ["灵山大佛高八十八米。", "欢迎来到灵山！"],
        )
        self.assertEqual(
            segmenter.feed(
                '\n{"emotion":"calm","citations":["dataset-1"]}'
            ),
            [],
        )

    def test_flushes_short_final_segment(self):
        segmenter = SpeechSegmenter()
        self.assertEqual(segmenter.feed("祝您游览愉快"), [])
        self.assertEqual(segmenter.finish(), ["祝您游览愉快"])

    def test_emits_complete_opening_clause(self):
        segmenter = SpeechSegmenter()
        self.assertEqual(segmenter.feed("灵山大佛高88米，"), ["灵山大佛高88米，"])
        self.assertEqual(segmenter.feed("含台基总高101.5米。"), ["含台基总高101.5米。"])
