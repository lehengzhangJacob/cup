from __future__ import annotations

import math
import sys
import wave
from array import array
from io import BytesIO


class GlmTtsWatermarkFilter:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.pending = bytearray()
        self.decided = False

    def feed(self, pcm: bytes) -> bytes:
        if self.decided:
            return pcm
        self.pending.extend(pcm)
        cleaned, decided = _filter_pcm16(
            bytes(self.pending),
            self.sample_rate,
            final=False,
        )
        if not decided:
            return b""
        self.pending.clear()
        self.decided = True
        return cleaned

    def finish(self) -> bytes:
        if self.decided:
            return b""
        cleaned, _ = _filter_pcm16(
            bytes(self.pending),
            self.sample_rate,
            final=True,
        )
        self.pending.clear()
        self.decided = True
        return cleaned


def strip_glm_tts_watermark_pcm16(pcm: bytes, sample_rate: int) -> bytes:
    cleaned, _ = _filter_pcm16(pcm, sample_rate, final=True)
    return cleaned


def strip_glm_tts_watermark_wav(audio: bytes) -> bytes:
    with wave.open(BytesIO(audio), "rb") as source:
        params = source.getparams()
        if params.nchannels != 1 or params.sampwidth != 2:
            return audio
        pcm = source.readframes(params.nframes)

    cleaned = strip_glm_tts_watermark_pcm16(pcm, params.framerate)
    if len(cleaned) == len(pcm):
        return audio

    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams(params)
        target.writeframes(cleaned)
    return output.getvalue()


def _filter_pcm16(
    pcm: bytes,
    sample_rate: int,
    *,
    final: bool,
) -> tuple[bytes, bool]:
    if not pcm or len(pcm) % 2 or not 8_000 <= sample_rate <= 96_000:
        return pcm, True

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    frame_samples = max(1, sample_rate // 100)
    frame_count = len(samples) // frame_samples
    minimum_probe_frames = 15
    if frame_count < minimum_probe_frames and not final:
        return b"", False

    rms_values: list[float] = []
    zero_crossing_rates: list[float] = []
    for frame_index in range(frame_count):
        start = frame_index * frame_samples
        frame = samples[start : start + frame_samples]
        if not frame:
            break
        square_sum = sum(sample * sample for sample in frame)
        rms_values.append(math.sqrt(square_sum / len(frame)))
        crossings = sum(
            (frame[index] < 0) != (frame[index - 1] < 0)
            for index in range(1, len(frame))
        )
        zero_crossing_rates.append(crossings / max(1, len(frame) - 1))

    watermark_run = 0
    maximum_watermark_run = 0
    for rms, crossing_rate in zip(rms_values[:100], zero_crossing_rates[:100]):
        tone_frame = 1_050 <= rms <= 1_450 and 0.03 <= crossing_rate <= 0.16
        watermark_run = watermark_run + 1 if tone_frame else 0
        maximum_watermark_run = max(maximum_watermark_run, watermark_run)

    if maximum_watermark_run < 3:
        return pcm, True

    speech_frame = None
    for frame_index in range(1, len(rms_values)):
        if rms_values[frame_index - 1] >= 2_200 and rms_values[frame_index] >= 2_200:
            speech_frame = frame_index - 1
            break

    if speech_frame is None:
        if not final and len(samples) < sample_rate * 4:
            return b"", False

    last_watermark_frame = 0
    watermark_search_end = speech_frame if speech_frame is not None else len(rms_values)
    for frame_index in range(watermark_search_end):
        rms = rms_values[frame_index]
        crossing_rate = zero_crossing_rates[frame_index]
        if 1_050 <= rms <= 1_450 and 0.03 <= crossing_rate <= 0.16:
            last_watermark_frame = frame_index

    trim_samples = min(len(samples), (last_watermark_frame + 1) * frame_samples)
    return pcm[trim_samples * 2 :], True
