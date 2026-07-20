from __future__ import annotations

import math
import unittest
import wave
from array import array
from io import BytesIO

from app.tts_audio import (
    GlmTtsWatermarkFilter,
    fade_in_pcm16,
    strip_glm_tts_watermark_pcm16,
    strip_glm_tts_watermark_wav,
)


SAMPLE_RATE = 24_000


def _tone(frequency: float, seconds: float, amplitude: int) -> array:
    return array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
            for index in range(round(seconds * SAMPLE_RATE))
        ),
    )


def _watermarked_pcm() -> tuple[bytes, bytes]:
    watermark = _tone(560, 0.18, 1_800)
    watermark.extend(array("h", [0]) * round(0.12 * SAMPLE_RATE))
    watermark.extend(_tone(1_680, 0.16, 1_800))
    watermark.extend(array("h", [0]) * round(0.18 * SAMPLE_RATE))
    speech = _tone(220, 0.5, 9_000)
    combined = array("h", watermark)
    combined.extend(speech)
    return combined.tobytes(), speech.tobytes()


class TtsAudioTests(unittest.TestCase):
    def test_fades_nonzero_start_without_changing_length(self):
        speech = _tone(220, 0.5, 9_000).tobytes()
        faded = fade_in_pcm16(speech, SAMPLE_RATE)
        original_samples = array("h")
        original_samples.frombytes(speech)
        faded_samples = array("h")
        faded_samples.frombytes(faded)

        self.assertEqual(len(faded), len(speech))
        self.assertEqual(faded_samples[0], 0)
        self.assertEqual(faded_samples[-1], original_samples[-1])
        self.assertGreater(abs(faded_samples[SAMPLE_RATE // 100]), 1_000)

    def test_stream_filter_fades_first_clean_pcm_chunk(self):
        speech = _tone(220, 0.5, 9_000).tobytes()
        audio_filter = GlmTtsWatermarkFilter(SAMPLE_RATE)

        cleaned = audio_filter.feed(speech)
        cleaned_samples = array("h")
        cleaned_samples.frombytes(cleaned)

        self.assertEqual(len(cleaned), len(speech))
        self.assertEqual(cleaned_samples[0], 0)

    def test_strips_leading_glm_watermark_tones(self):
        watermarked, speech = _watermarked_pcm()
        cleaned = strip_glm_tts_watermark_pcm16(watermarked, SAMPLE_RATE)

        self.assertLess(len(cleaned), len(watermarked))
        self.assertTrue(cleaned.endswith(speech))

    def test_stream_filter_buffers_until_speech(self):
        watermarked, speech = _watermarked_pcm()
        split = len(watermarked) // 2
        audio_filter = GlmTtsWatermarkFilter(SAMPLE_RATE)

        first = audio_filter.feed(watermarked[:split])
        second = audio_filter.feed(watermarked[split:])

        self.assertEqual(first, b"")
        self.assertTrue(second.endswith(speech))

    def test_preserves_clean_speech(self):
        speech = _tone(220, 0.5, 9_000).tobytes()
        self.assertEqual(
            strip_glm_tts_watermark_pcm16(speech, SAMPLE_RATE),
            speech,
        )

    def test_preserves_quiet_speech_after_watermark(self):
        watermarked, _ = _watermarked_pcm()
        quiet_speech = _tone(220, 0.5, 1_800).tobytes()
        quiet_audio = watermarked[: -round(0.5 * SAMPLE_RATE) * 2] + quiet_speech

        cleaned = strip_glm_tts_watermark_pcm16(quiet_audio, SAMPLE_RATE)

        self.assertTrue(cleaned.endswith(quiet_speech))

    def test_strips_watermark_from_wav(self):
        watermarked, speech = _watermarked_pcm()
        source = BytesIO()
        with wave.open(source, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(watermarked)

        cleaned = strip_glm_tts_watermark_wav(source.getvalue())
        with wave.open(BytesIO(cleaned), "rb") as result:
            self.assertEqual(result.readframes(result.getnframes())[-len(speech) :], speech)


if __name__ == "__main__":
    unittest.main()
