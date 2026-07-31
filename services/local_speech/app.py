from __future__ import annotations

import asyncio
import io
import os
import re
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import httpx
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from funasr import AutoModel
from piper import PiperVoice, SynthesisConfig
from pydantic import BaseModel, Field

from services.api.app.speech_text import normalize_asr_text
from services.api.app.voice_profiles import DEFAULT_VOICE_PROFILE, normalize_voice_profile


FUNASR_MODEL = Path(
    os.getenv("LOCAL_FUNASR_MODEL", "/home/huggingface/funasr/paraformer-zh")
).expanduser()
FUNASR_VAD_MODEL = Path(
    os.getenv("LOCAL_FUNASR_VAD_MODEL", "/home/huggingface/funasr/fsmn-vad")
).expanduser()
FUNASR_PUNC_MODEL = Path(
    os.getenv("LOCAL_FUNASR_PUNC_MODEL", "/home/huggingface/funasr/ct-punc")
).expanduser()
FUNASR_HOTWORDS = os.getenv(
    "LOCAL_FUNASR_HOTWORDS",
    (
        "灵山 灵灵 灵山胜境 灵山大佛 灵山梵宫 祥符禅寺 五印坛城 "
        "拈花湾 拈花湾禅意小镇 梵天花海 香月花街 天下第一掌"
    ),
).strip()

# Normalize paragraph pauses before passing text to the configured local
# acoustic backend. Actual waveform generation is performed by GLM-TTS.
PIPER_MODEL = Path(
    os.getenv(
        "LOCAL_PIPER_MODEL",
        "/home/huggingface/piper-voices/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
    )
).expanduser()
PIPER_CONFIG = Path(os.getenv("LOCAL_PIPER_CONFIG", f"{PIPER_MODEL}.json")).expanduser()
PIPER_RESOURCE_DIR = Path(
    os.getenv("LOCAL_PIPER_RESOURCE_DIR", "/home/gmn/codes/cup")
).expanduser()
MAX_AUDIO_BYTES = int(os.getenv("LOCAL_SPEECH_MAX_AUDIO_MB", "12")) * 1024 * 1024
LOCAL_TTS_BACKEND = os.getenv("LOCAL_TTS_BACKEND", "piper").strip().lower()
LOCAL_GLM_TTS_URL = os.getenv("LOCAL_GLM_TTS_URL", "http://127.0.0.1:8031").rstrip("/")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    speed: float = Field(1.0, ge=0.75, le=1.3)
    voice: str = Field(DEFAULT_VOICE_PROFILE, min_length=1, max_length=80)


def paragraph_prosody_text(text: str) -> str:
    """Turn display-oriented output into one coherent spoken paragraph.

    The whole result is sent to the acoustic model in a single call so it can
    preserve pitch and rhythm across sentences.  Strong stops remain between
    route stages while arrows and markdown do not get pronounced literally.
    """

    value = str(text or "")
    value = re.sub(r"```[\s\S]*?```", "", value)
    value = re.sub(r"[#*_`]+", "", value)
    value = re.sub(r"\s*(?:→|->|=>|➡️?|➜|➝)\s*", "，接着前往", value)
    value = re.sub(r"(?m)^\s*[-•·]+\s*", "", value)
    value = re.sub(r"[\r\n]+", "。", value)
    value = re.sub(r"[，,]{2,}", "，", value)
    value = re.sub(r"[。；;]{2,}", "。", value)
    value = re.sub(r"\s+", "", value).strip("，。；; ")
    if value and value[-1] not in "。！？!?":
        value += "。"
    return value


class SpeechRuntime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.funasr: Any = None
        self.piper: PiperVoice | None = None

    def load(self) -> None:
        for label, path in (
            ("FunASR Paraformer", FUNASR_MODEL),
            ("FunASR VAD", FUNASR_VAD_MODEL),
            ("FunASR punctuation", FUNASR_PUNC_MODEL),
        ):
            if not (path / "config.yaml").is_file() or not (path / "model.pt").is_file():
                raise RuntimeError(f"{label} model is incomplete: {path}")
        if not PIPER_MODEL.is_file() or not PIPER_CONFIG.is_file():
            raise RuntimeError(f"local TTS voice files are incomplete: {PIPER_MODEL}")

        # Keeping FunASR resident on CPU avoids competing with Qwen, the
        # digital human and emotion model for GPU memory.
        self.funasr = AutoModel(
            model=str(FUNASR_MODEL),
            vad_model=str(FUNASR_VAD_MODEL),
            punc_model=str(FUNASR_PUNC_MODEL),
            device="cpu",
            ncpu=max(1, min(8, os.cpu_count() or 4)),
            disable_update=True,
            disable_pbar=True,
        )
        self.piper = PiperVoice.load(
            PIPER_MODEL,
            config_path=PIPER_CONFIG,
            use_cuda=False,
            download_dir=PIPER_RESOURCE_DIR,
        )
        list(self.piper.synthesize("您好", SynthesisConfig(length_scale=1.0)))

    def transcribe(self, audio_bytes: bytes) -> dict[str, str]:
        with self.lock:
            if self.funasr is None:
                raise RuntimeError("FunASR is not loaded")
            samples, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if sample_rate != 16000:
                import librosa

                samples = librosa.resample(samples, orig_sr=sample_rate, target_sr=16000)
            result = self.funasr.generate(
                input=np.asarray(samples, dtype=np.float32),
                batch_size_s=60,
                hotword=FUNASR_HOTWORDS,
            )
            first = result[0] if isinstance(result, list) and result else result
            text = normalize_asr_text((first or {}).get("text"))
            return {"text": text}

    def _synthesize_glm_pcm(
        self, text: str, speed: float, voice: str
    ) -> tuple[bytes, int, str]:
        try:
            with httpx.Client(timeout=180.0, trust_env=False) as client:
                response = client.post(
                    f"{LOCAL_GLM_TTS_URL}/tts/pcm",
                    json={
                        "text": text,
                        "speed": speed,
                        "voice": normalize_voice_profile(voice),
                    },
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:600]
            raise RuntimeError(f"本地 GLM-TTS 推理失败：{detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"本地 GLM-TTS 服务不可用：{exc}") from exc
        sample_rate = int(response.headers.get("X-Sample-Rate") or 24000)
        provider = response.headers.get("X-Speech-Provider") or "local-glm-tts"
        if not response.content:
            raise RuntimeError("本地 GLM-TTS 未返回音频")
        return response.content, sample_rate, provider

    def synthesize_pcm(
        self, text: str, speed: float, voice: str
    ) -> tuple[bytes, int, str]:
        spoken = paragraph_prosody_text(text)
        if not spoken:
            raise RuntimeError("no speakable text")
        if LOCAL_TTS_BACKEND == "glm-tts":
            return self._synthesize_glm_pcm(spoken, speed, voice)
        with self.lock:
            if self.piper is None:
                raise RuntimeError("local TTS backend is not loaded")
            config = SynthesisConfig(length_scale=max(0.65, min(1.5, 1.0 / speed)))
            chunks = list(self.piper.synthesize(spoken, config))
            if not chunks:
                raise RuntimeError("local TTS backend returned no audio")
            sample_rate = int(chunks[0].sample_rate)
            return (
                b"".join(chunk.audio_int16_bytes for chunk in chunks),
                sample_rate,
                "paragraph-prosody+piper",
            )

    def synthesize_wav(self, text: str, speed: float, voice: str) -> tuple[bytes, str]:
        pcm, sample_rate, provider = self.synthesize_pcm(text, speed, voice)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue(), provider

    @staticmethod
    def glm_tts_status() -> dict[str, Any]:
        if LOCAL_TTS_BACKEND != "glm-tts":
            return {"configured": False, "ok": False}
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                response = client.get(f"{LOCAL_GLM_TTS_URL}/health")
            response.raise_for_status()
            return {"configured": True, **response.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"configured": True, "ok": False, "detail": str(exc)}

    def status(self) -> dict[str, Any]:
        return {
            "ok": self.funasr is not None and self.piper is not None,
            "runtime": "/home/gmn/.conda/envs/ccc/bin/python",
            "asr": {
                "provider": "local-funasr",
                "model": str(FUNASR_MODEL),
                "vad_model": str(FUNASR_VAD_MODEL),
                "punc_model": str(FUNASR_PUNC_MODEL),
                "device": "cpu",
                "hotwords": FUNASR_HOTWORDS,
            },
            "tts": {
                "provider": (
                    "local-glm-tts" if LOCAL_TTS_BACKEND == "glm-tts"
                    else "paragraph-prosody+piper"
                ),
                "prosody": "paragraph-aware pause normalization",
                "acoustic_backend": (
                    "GLM-TTS open-source zero-shot voice cloning"
                    if LOCAL_TTS_BACKEND == "glm-tts"
                    else "Piper"
                ),
                "voice_profile": normalize_voice_profile(DEFAULT_VOICE_PROFILE),
                "model": (
                    os.getenv("GLM_TTS_MODEL_DIR", "/home/huggingface/GLM-TTS")
                    if LOCAL_TTS_BACKEND == "glm-tts"
                    else str(PIPER_MODEL)
                ),
                "sample_rate": 24000 if LOCAL_TTS_BACKEND == "glm-tts" else (
                    self.piper.config.sample_rate if self.piper else None
                ),
                "engine": self.glm_tts_status(),
            },
        }


runtime = SpeechRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(runtime.load)
    yield


app = FastAPI(title="CUP Local Speech", lifespan=lifespan)


@app.get("/health")
async def health():
    return runtime.status()


@app.post("/asr")
async def asr(file: UploadFile = File(...)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(400, "audio too large")
    try:
        result = await asyncio.to_thread(runtime.transcribe, audio)
    except Exception as exc:
        raise HTTPException(503, f"local FunASR failed: {exc}") from exc
    return {
        **result,
        "provider": "local-funasr",
        "model": str(FUNASR_MODEL),
    }


@app.post("/tts")
async def tts(req: TTSRequest):
    try:
        audio, provider = await asyncio.to_thread(
            runtime.synthesize_wav, req.text, req.speed, req.voice
        )
    except Exception as exc:
        raise HTTPException(503, f"local paragraph TTS failed: {exc}") from exc
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"X-Speech-Provider": provider},
    )


@app.post("/tts/pcm")
async def tts_pcm(req: TTSRequest):
    try:
        pcm, sample_rate, provider = await asyncio.to_thread(
            runtime.synthesize_pcm, req.text, req.speed, req.voice
        )
    except Exception as exc:
        raise HTTPException(503, f"local paragraph TTS failed: {exc}") from exc
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={
            "X-Speech-Provider": provider,
            "X-Sample-Rate": str(sample_rate),
        },
    )
