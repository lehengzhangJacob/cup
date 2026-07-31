from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import LOCAL_SPEECH_URL


class LocalSpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class PcmAudio:
    data: bytes
    sample_rate: int
    provider: str


class LocalSpeechClient:
    def __init__(self, base_url: str = LOCAL_SPEECH_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "detail": f"本地语音服务不可用：{exc}"}

    async def asr(self, audio: bytes, *, filename: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=240.0, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/asr",
                    files={"file": (filename, audio, "audio/wav")},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LocalSpeechError(f"FunASR 服务不可用：{exc}") from exc
        text = str(data.get("text") or "").strip()
        return {**data, "text": text}

    async def tts_wav(
        self, text: str, *, speed: float = 1.0, voice: str
    ) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=240.0, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/tts",
                    json={"text": text, "speed": speed, "voice": voice},
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise LocalSpeechError(f"本地段落语音服务不可用：{exc}") from exc

    async def tts_pcm(
        self, text: str, *, speed: float = 1.0, voice: str
    ) -> PcmAudio:
        try:
            async with httpx.AsyncClient(timeout=240.0, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/tts/pcm",
                    json={"text": text, "speed": speed, "voice": voice},
                )
            response.raise_for_status()
            sample_rate = int(response.headers.get("X-Sample-Rate") or 22050)
            provider = response.headers.get("X-Speech-Provider") or "local-paragraph-tts"
            return PcmAudio(response.content, sample_rate, provider)
        except (httpx.HTTPError, ValueError) as exc:
            raise LocalSpeechError(f"本地段落语音服务不可用：{exc}") from exc


local_speech = LocalSpeechClient()
