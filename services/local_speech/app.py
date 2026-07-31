from __future__ import annotations

import asyncio
import contextlib
import io
import os
import subprocess
import threading
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from opencc import OpenCC
from piper import PiperVoice, SynthesisConfig
from pydantic import BaseModel, Field
from transformers import pipeline


WHISPER_MODEL = Path(
    os.getenv("LOCAL_WHISPER_MODEL", "/home/huggingface/whisper-large-v3")
).expanduser()
PIPER_MODEL = Path(
    os.getenv(
        "LOCAL_PIPER_MODEL",
        "/home/huggingface/piper-voices/zh_CN-chaowen-medium/zh_CN-chaowen-medium.onnx",
    )
).expanduser()
PIPER_CONFIG = Path(
    os.getenv("LOCAL_PIPER_CONFIG", f"{PIPER_MODEL}.json")
).expanduser()
PIPER_RESOURCE_DIR = Path(
    os.getenv("LOCAL_PIPER_RESOURCE_DIR", "/home/gmn/codes/cup")
).expanduser()
GPU_CANDIDATES = tuple(
    int(item.strip())
    for item in os.getenv("LOCAL_SPEECH_GPU_CANDIDATES", "0,1,2,3").split(",")
    if item.strip()
)
GPU_MIN_FREE_MB = int(os.getenv("LOCAL_SPEECH_GPU_MIN_FREE_MB", "6000"))
GPU_IDLE_SECONDS = float(os.getenv("LOCAL_SPEECH_GPU_IDLE_SECONDS", "180"))
MAX_AUDIO_BYTES = int(os.getenv("LOCAL_SPEECH_MAX_AUDIO_MB", "12")) * 1024 * 1024

DOMAIN_CORRECTIONS = {
    "泥山": "灵山",
    "尼山": "灵山",
    "林山": "灵山",
    "靈山": "灵山",
    "年花湾": "拈花湾",
    "粘花湾": "拈花湾",
    "拈花彎": "拈花湾",
    "梵工": "梵宫",
    "梵公": "梵宫",
    "無印壇城": "五印坛城",
    "无印坛城": "五印坛城",
}


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    speed: float = Field(1.0, ge=0.75, le=1.3)


def _gpu_snapshot() -> list[dict[str, int]]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    rows: list[dict[str, int]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3:
            rows.append(
                {"index": int(parts[0]), "free_mb": int(parts[1]), "utilization": int(parts[2])}
            )
    return rows


def _select_gpu() -> dict[str, int]:
    allowed = [row for row in _gpu_snapshot() if row["index"] in GPU_CANDIDATES]
    eligible = [row for row in allowed if row["free_mb"] >= GPU_MIN_FREE_MB]
    if not eligible:
        detail = ", ".join(
            f"GPU {row['index']}: {row['free_mb']} MiB free" for row in allowed
        ) or "no candidate GPU detected"
        raise RuntimeError(
            f"No GPU has the required {GPU_MIN_FREE_MB} MiB free for Whisper ({detail})"
        )
    return max(eligible, key=lambda row: (row["free_mb"], -row["utilization"]))


class SpeechRuntime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.piper: PiperVoice | None = None
        self.whisper: Any = None
        self.whisper_device = "cpu"
        self.whisper_gpu: int | None = None
        self.last_asr_at = 0.0
        self.opencc = OpenCC("t2s")

    def load(self) -> None:
        if not PIPER_MODEL.is_file() or not PIPER_CONFIG.is_file():
            raise RuntimeError(f"Piper voice files are incomplete: {PIPER_MODEL}")
        if not (WHISPER_MODEL / "config.json").is_file():
            raise RuntimeError(f"Whisper model is incomplete: {WHISPER_MODEL}")

        self.piper = PiperVoice.load(
            PIPER_MODEL,
            config_path=PIPER_CONFIG,
            use_cuda=False,
            download_dir=PIPER_RESOURCE_DIR,
        )
        # Prime ONNX and Chinese G2P before reporting the service as ready.
        list(self.piper.synthesize("您好", SynthesisConfig(length_scale=1.0)))

        self.whisper = pipeline(
            "automatic-speech-recognition",
            model=str(WHISPER_MODEL),
            dtype=torch.float16,
            device=-1,
        )
        self.whisper_device = "cpu"

    def _activate_whisper(self) -> int:
        if self.whisper is None:
            raise RuntimeError("Whisper is not loaded")
        if self.whisper_gpu is not None:
            self.last_asr_at = time.monotonic()
            return self.whisper_gpu

        selected = _select_gpu()
        gpu = selected["index"]
        device = torch.device(f"cuda:{gpu}")
        self.whisper.model.to(device)
        self.whisper.device = device
        self.whisper_device = str(device)
        self.whisper_gpu = gpu
        self.last_asr_at = time.monotonic()
        return gpu

    def offload_whisper_if_idle(self) -> bool:
        with self.lock:
            if self.whisper is None or self.whisper_gpu is None:
                return False
            if time.monotonic() - self.last_asr_at < GPU_IDLE_SECONDS:
                return False
            self.whisper.model.to(torch.device("cpu"))
            self.whisper.device = torch.device("cpu")
            self.whisper_device = "cpu"
            self.whisper_gpu = None
            torch.cuda.empty_cache()
            return True

    def transcribe(self, audio_bytes: bytes) -> dict[str, Any]:
        with self.lock:
            gpu = self._activate_whisper()
            samples, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if sample_rate != 16000:
                import librosa

                samples = librosa.resample(samples, orig_sr=sample_rate, target_sr=16000)
                sample_rate = 16000
            result = self.whisper(
                {"array": np.asarray(samples, dtype=np.float32), "sampling_rate": sample_rate},
                generate_kwargs={"language": "zh", "task": "transcribe"},
            )
            text = self.opencc.convert(str(result.get("text") or "").strip())
            for source, target in DOMAIN_CORRECTIONS.items():
                text = text.replace(source, target)
            self.last_asr_at = time.monotonic()
            return {"text": text, "gpu_index": gpu}

    def synthesize_pcm(self, text: str, speed: float) -> tuple[bytes, int]:
        with self.lock:
            if self.piper is None:
                raise RuntimeError("Piper is not loaded")
            config = SynthesisConfig(length_scale=max(0.65, min(1.5, 1.0 / speed)))
            chunks = list(self.piper.synthesize(text, config))
            if not chunks:
                raise RuntimeError("Piper returned no audio")
            sample_rate = int(chunks[0].sample_rate)
            return b"".join(chunk.audio_int16_bytes for chunk in chunks), sample_rate

    def synthesize_wav(self, text: str, speed: float) -> bytes:
        pcm, sample_rate = self.synthesize_pcm(text, speed)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()

    def status(self) -> dict[str, Any]:
        return {
            "ok": self.piper is not None and self.whisper is not None,
            "asr": {
                "provider": "local-whisper",
                "model": str(WHISPER_MODEL),
                "device": self.whisper_device,
                "gpu_index": self.whisper_gpu,
                "idle_seconds": GPU_IDLE_SECONDS,
            },
            "tts": {
                "provider": "local-piper",
                "model": str(PIPER_MODEL),
                "sample_rate": self.piper.config.sample_rate if self.piper else None,
            },
        }


runtime = SpeechRuntime()


async def _idle_reaper() -> None:
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(runtime.offload_whisper_if_idle)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(runtime.load)
    reaper = asyncio.create_task(_idle_reaper())
    try:
        yield
    finally:
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper


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
        raise HTTPException(503, f"local Whisper failed: {exc}") from exc
    return {
        **result,
        "provider": "local-whisper",
        "model": str(WHISPER_MODEL),
    }


@app.post("/tts")
async def tts(req: TTSRequest):
    try:
        audio = await asyncio.to_thread(runtime.synthesize_wav, req.text, req.speed)
    except Exception as exc:
        raise HTTPException(503, f"local Piper TTS failed: {exc}") from exc
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"X-Speech-Provider": "local-piper"},
    )


@app.post("/tts/pcm")
async def tts_pcm(req: TTSRequest):
    try:
        pcm, sample_rate = await asyncio.to_thread(
            runtime.synthesize_pcm, req.text, req.speed
        )
    except Exception as exc:
        raise HTTPException(503, f"local Piper TTS failed: {exc}") from exc
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={
            "X-Speech-Provider": "local-piper",
            "X-Sample-Rate": str(sample_rate),
        },
    )
