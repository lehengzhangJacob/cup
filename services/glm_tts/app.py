from __future__ import annotations

import asyncio
import gc
import io
import os
import sys
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLM_TTS_REPO = Path(
    os.getenv("GLM_TTS_REPO", PROJECT_ROOT / "third_party/GLM-TTS")
).expanduser().resolve()
GLM_TTS_MODEL_DIR = Path(
    os.getenv("GLM_TTS_MODEL_DIR", "/home/huggingface/GLM-TTS")
).expanduser().resolve()
SAMPLE_RATE = int(os.getenv("GLM_TTS_SAMPLE_RATE", "24000"))

# Upstream shares one CUDA/NPU frontend and calls torch.npu unconditionally in
# one prompt-embedding branch.  CUDA-only PyTorch does not define that
# namespace, so provide the same false capability check without modifying the
# vendored model code.
if not hasattr(torch, "npu"):
    class _NoNpu:
        @staticmethod
        def is_available() -> bool:
            return False

    torch.npu = _NoNpu()  # type: ignore[attr-defined]

# The upstream inference module resolves ckpt/, frontend/ and configs/ from
# its working directory.  This service is intentionally isolated in its own
# process, so changing cwd does not affect the rest of the application.
os.chdir(GLM_TTS_REPO)
sys.path.insert(0, str(GLM_TTS_REPO))
sys.path.insert(0, str(PROJECT_ROOT))

from glmtts_inference import DEVICE, generate_long, load_models  # noqa: E402
from services.api.app.voice_profiles import (  # noqa: E402
    normalize_voice_profile,
    voice_profile,
)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    speed: float = Field(1.0, ge=0.75, le=1.3)
    voice: str = Field(..., min_length=1, max_length=80)


class GlmTtsRuntime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.components: tuple[Any, ...] | None = None
        self.prompt_cache: dict[str, dict[str, Any]] = {}
        self.load_error: str | None = None
        self.loading = False

    @staticmethod
    def _required_model_files() -> list[Path]:
        return [
            GLM_TTS_MODEL_DIR / "llm/config.json",
            GLM_TTS_MODEL_DIR / "llm/model.safetensors.index.json",
            GLM_TTS_MODEL_DIR / "llm/model-00001-of-00002.safetensors",
            GLM_TTS_MODEL_DIR / "llm/model-00002-of-00002.safetensors",
            GLM_TTS_MODEL_DIR / "flow/flow.pt",
            GLM_TTS_MODEL_DIR / "speech_tokenizer/config.json",
            GLM_TTS_MODEL_DIR / "speech_tokenizer/model.safetensors",
            GLM_TTS_MODEL_DIR / "hift/hift.pt",
            GLM_TTS_MODEL_DIR / "vq32k-phoneme-tokenizer/tokenizer.model",
        ]

    def _ensure_model_link(self) -> None:
        target = GLM_TTS_REPO / "ckpt"
        if target.is_symlink() and target.resolve() == GLM_TTS_MODEL_DIR:
            return
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"GLM-TTS ckpt path conflicts with deployment: {target}")
        target.symlink_to(GLM_TTS_MODEL_DIR, target_is_directory=True)

    def model_complete(self) -> bool:
        return all(path.is_file() and path.stat().st_size > 0 for path in self._required_model_files())

    def ensure_loaded(self) -> None:
        with self.lock:
            if self.components is not None:
                return
            self.loading = True
            self.load_error = None
            try:
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA 不可用，GLM-TTS 需要 GPU")
                if not self.model_complete():
                    missing = [str(path) for path in self._required_model_files() if not path.is_file()]
                    raise RuntimeError(f"GLM-TTS 权重尚未下载完整：{', '.join(missing[:3])}")
                self._ensure_model_link()
                self.components = load_models(use_phoneme=False, sample_rate=SAMPLE_RATE)
            except torch.cuda.OutOfMemoryError as exc:
                self._clear_models()
                self.load_error = (
                    f"GLM-TTS CUDA OOM（物理 GPU {self.physical_gpu()}）；"
                    "请释放显存或重启服务以重新选择空闲 GPU"
                )
                raise RuntimeError(self.load_error) from exc
            except Exception as exc:
                self._clear_models()
                self.load_error = str(exc)
                raise
            finally:
                self.loading = False

    def _clear_models(self) -> None:
        self.components = None
        self.prompt_cache.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    @staticmethod
    def physical_gpu() -> str:
        return os.getenv(
            "GLM_TTS_GPU_PHYSICAL",
            os.getenv("CUDA_VISIBLE_DEVICES", "auto"),
        )

    def _prompt(self, voice: str) -> dict[str, Any]:
        profile_id = normalize_voice_profile(voice)
        cached = self.prompt_cache.get(profile_id)
        if cached is not None:
            return cached
        if self.components is None:
            raise RuntimeError("GLM-TTS 尚未加载")
        frontend, text_frontend, _, _, _ = self.components
        profile = voice_profile(profile_id)
        prompt_audio = Path(profile["local_reference_audio"])
        if not prompt_audio.is_file():
            raise RuntimeError(f"本地音色参考音频不存在：{prompt_audio}")
        prompt_text = text_frontend.text_normalize(profile["reference_text"]) + " "
        prompt_text_token = frontend._extract_text_token(prompt_text)
        prompt_speech_token = frontend._extract_speech_token([str(prompt_audio)])
        speech_feat = frontend._extract_speech_feat(
            str(prompt_audio), sample_rate=SAMPLE_RATE
        )
        embedding = frontend._extract_spk_embedding(str(prompt_audio))
        prompt = {
            "profile_id": profile_id,
            "prompt_text": prompt_text,
            "prompt_text_token": prompt_text_token,
            "prompt_speech_tokens": prompt_speech_token.squeeze().tolist(),
            "speech_feat": speech_feat,
            "embedding": embedding,
        }
        self.prompt_cache[profile_id] = prompt
        return prompt

    @staticmethod
    def _adjust_speed(audio: np.ndarray, speed: float) -> np.ndarray:
        if abs(speed - 1.0) < 0.01:
            return audio
        import librosa

        return librosa.effects.time_stretch(audio.astype(np.float32), rate=speed)

    def synthesize_pcm(self, text: str, speed: float, voice: str) -> tuple[bytes, str]:
        with self.lock:
            self.ensure_loaded()
            if self.components is None:
                raise RuntimeError("GLM-TTS 尚未加载")
            frontend, text_frontend, _, llm, flow = self.components
            prompt = self._prompt(voice)
            synth_text = text_frontend.text_normalize(text)
            prompt_speech_tokens = list(prompt["prompt_speech_tokens"])
            flow_prompt_token = torch.tensor(
                [prompt_speech_tokens], dtype=torch.int32, device=DEVICE
            )
            cache = {
                "cache_text": [prompt["prompt_text"]],
                "cache_text_token": [prompt["prompt_text_token"]],
                "cache_speech_token": [prompt_speech_tokens],
                "use_cache": True,
            }
            try:
                with torch.inference_mode():
                    speech, _, _, _ = generate_long(
                        frontend=frontend,
                        text_frontend=text_frontend,
                        llm=llm,
                        flow=flow,
                        text_info=["request", synth_text],
                        cache=cache,
                        device=DEVICE,
                        embedding=prompt["embedding"],
                        seed=42,
                        sample_method="ras",
                        flow_prompt_token=flow_prompt_token,
                        speech_feat=prompt["speech_feat"],
                        use_phoneme=False,
                    )
            except torch.cuda.OutOfMemoryError as exc:
                self.load_error = (
                    f"GLM-TTS CUDA OOM（物理 GPU {self.physical_gpu()}），"
                    "本次语音未生成"
                )
                self._clear_models()
                raise RuntimeError(self.load_error) from exc
            audio = speech.squeeze().detach().float().cpu().numpy()
            audio = self._adjust_speed(audio, speed)
            audio = np.clip(audio, -1.0, 1.0)
            pcm = (audio * 32767.0).astype("<i2").tobytes()
            return pcm, prompt["profile_id"]

    def status(self) -> dict[str, Any]:
        gpu_memory = None
        if torch.cuda.is_available():
            try:
                gpu_memory = {
                    "allocated_mib": round(torch.cuda.memory_allocated() / 1024**2),
                    "reserved_mib": round(torch.cuda.memory_reserved() / 1024**2),
                }
            except RuntimeError:
                pass
        return {
            "ok": self.model_complete() and self.load_error is None,
            "ready": self.components is not None,
            "loading": self.loading,
            "provider": "local-glm-tts",
            "model": str(GLM_TTS_MODEL_DIR),
            "sample_rate": SAMPLE_RATE,
            "device": str(DEVICE),
            "physical_gpu": self.physical_gpu(),
            "gpu_memory": gpu_memory,
            "error": self.load_error,
        }


runtime = GlmTtsRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Lazy loading keeps the service observable when model files are missing or
    # the selected GPU cannot satisfy the allocation.  The first request gets
    # a concrete 503/OOM message instead of a silent process crash.
    preload_task: asyncio.Task[None] | None = None
    if os.getenv("GLM_TTS_PRELOAD", "true").lower() in {"1", "true", "yes"}:
        async def preload() -> None:
            try:
                await asyncio.to_thread(runtime.ensure_loaded)
            except Exception as exc:
                # Keep the HTTP process alive so /health and the first request
                # can expose the exact download/CUDA/OOM failure.
                print(f"[glm-tts] preload failed: {exc}", flush=True)

        preload_task = asyncio.create_task(preload())
    try:
        yield
    finally:
        if preload_task and not preload_task.done():
            preload_task.cancel()


app = FastAPI(title="CUP Local GLM-TTS", lifespan=lifespan)


@app.get("/health")
async def health():
    return runtime.status()


@app.post("/load")
async def load():
    try:
        await asyncio.to_thread(runtime.ensure_loaded)
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    return runtime.status()


@app.post("/tts/pcm")
async def tts_pcm(req: TTSRequest):
    try:
        pcm, profile_id = await asyncio.to_thread(
            runtime.synthesize_pcm, req.text, req.speed, req.voice
        )
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(
        pcm,
        media_type="application/octet-stream",
        headers={
            "X-Sample-Rate": str(SAMPLE_RATE),
            "X-Speech-Provider": f"local-glm-tts/{profile_id}",
        },
    )


@app.post("/tts")
async def tts_wav(req: TTSRequest):
    try:
        pcm, profile_id = await asyncio.to_thread(
            runtime.synthesize_pcm, req.text, req.speed, req.voice
        )
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return Response(
        output.getvalue(),
        media_type="audio/wav",
        headers={"X-Speech-Provider": f"local-glm-tts/{profile_id}"},
    )
