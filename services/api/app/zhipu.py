from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from .config import (
    ASR_MODEL,
    CHAT_MODEL,
    EMBED_MODEL,
    TTS_MODEL,
    TTS_VOICE,
    VISION_MODEL,
    ZHIPU_BASE,
    load_api_key,
)


class ZhipuClient:
    def __init__(self) -> None:
        self.api_key = load_api_key()
        self.base = ZHIPU_BASE.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # embedding-3 accepts input as string or list
        payload = {"model": EMBED_MODEL, "input": texts}
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self.base}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            items = sorted(data["data"], key=lambda x: x["index"])
            return [it["embedding"] for it in items]

    async def vision_describe(self, image_b64: str, prompt: str) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }
        ]
        return await self.chat(messages, model=VISION_MODEL, max_tokens=512)

    async def tts(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        speed: float = 1.0,
        response_format: str = "wav",
    ) -> bytes:
        payload = {
            "model": TTS_MODEL,
            "input": text[:2000],
            "voice": voice or TTS_VOICE,
            "speed": speed,
            "volume": 1.0,
            "response_format": response_format,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                f"{self.base}/audio/speech",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            return r.content

    async def asr(self, audio: bytes, filename: str = "audio.wav") -> str:
        # glm-asr 对格式敏感，优先 wav/mp3；按扩展名设置 MIME
        lower = filename.lower()
        if lower.endswith(".wav"):
            mime = "audio/wav"
        elif lower.endswith(".mp3"):
            mime = "audio/mpeg"
        elif lower.endswith(".m4a"):
            mime = "audio/mp4"
        elif lower.endswith(".webm"):
            mime = "audio/webm"
        else:
            mime = "application/octet-stream"
            filename = "audio.wav"
            mime = "audio/wav"

        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                f"{self.base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (filename, audio, mime)},
                data={"model": ASR_MODEL},
            )
            if r.status_code >= 400:
                raise RuntimeError(f"{r.status_code} {r.text[:500]}")
            data = r.json()
            return (data.get("text") or "").strip()


zhipu = ZhipuClient()
