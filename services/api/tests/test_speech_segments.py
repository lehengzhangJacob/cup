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

    def test_keeps_short_first_clause_for_natural_prosody(self):
        segmenter = SpeechSegmenter()
        self.assertEqual(segmenter.feed("灵山大佛高88米，"), [])
        self.assertEqual(
            segmenter.feed("含台基总高101.5米。"),
            ["灵山大佛高88米，含台基总高101.5米。"],
        )

    def test_keeps_later_short_clauses_together_for_natural_prosody(self):
        segmenter = SpeechSegmenter()
        self.assertEqual(segmenter.feed("先为您介绍灵山胜境。"), ["先为您介绍灵山胜境。"])
        self.assertEqual(segmenter.feed("这里很美，"), [])
        self.assertEqual(
            segmenter.feed("也很适合慢慢游览。"),
            ["这里很美，也很适合慢慢游览。"],
        )

    def test_waits_for_punctuation_before_splitting_long_text(self):
        segmenter = SpeechSegmenter()
        text = "这是一段超过十二个字但还没有表达完整的话"

        self.assertGreater(len(text), 12)
        self.assertEqual(segmenter.feed(text), [])
        self.assertEqual(
            segmenter.feed("，现在才说完。"),
            [text + "，现在才说完。"],
        )

    def test_splits_a_very_long_clause_at_comma_for_bounded_latency(self):
        segmenter = SpeechSegmenter()
        clause = "这是一段为了验证超长内容仍然可以及时开始播报而准备的完整测试文本"

        self.assertGreaterEqual(len(clause), 24)
        self.assertEqual(segmenter.feed(clause + "，"), [clause + "，"])

    def test_does_not_split_inside_streamed_clock_time(self):
        segmenter = SpeechSegmenter()

        self.assertEqual(segmenter.feed("开放时间为19:"), [])
        self.assertEqual(
            segmenter.feed("00，请合理安排。"),
            ["开放时间为19:00，请合理安排。"],
        )
