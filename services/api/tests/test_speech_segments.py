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

    def test_keeps_short_clauses_together_for_natural_prosody(self):
        segmenter = SpeechSegmenter()
        self.assertEqual(segmenter.feed("灵山大佛高88米，"), [])
        self.assertEqual(
            segmenter.feed("含台基总高101.5米。"),
            ["灵山大佛高88米，含台基总高101.5米。"],
        )

    def test_does_not_split_unpunctuated_text_at_twelve_characters(self):
        segmenter = SpeechSegmenter()
        text = "这是一段超过十二个字但还没有表达完整的话"

        self.assertGreater(len(text), 12)
        self.assertEqual(segmenter.feed(text), [])
        self.assertEqual(
            segmenter.feed("，现在才说完。"),
            [text + "，现在才说完。"],
        )
