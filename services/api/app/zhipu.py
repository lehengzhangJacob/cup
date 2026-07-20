from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Optional

import httpx

from .config import (
    ASR_MODEL,
    EMBED_MODEL,
    TTS_MODEL,
    TTS_VOICE,
    VISION_MODEL,
    ZHIPU_CHAT_MODEL,
    ZHIPU_BASE,
    load_api_key,
)
from .tts_audio import GlmTtsWatermarkFilter, strip_glm_tts_watermark_wav


class ZhipuClient:
    def __init__(self) -> None:
        self.api_key = load_api_key()
        self.base = ZHIPU_BASE.rstrip("/")
        self._async_client: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                timeout=90.0,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=32,
                    max_keepalive_connections=16,
                    keepalive_expiry=60.0,
                ),
            )
        return self._async_client

    async def aclose(self) -> None:
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()

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
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        selected_model = model or ZHIPU_CHAT_MODEL
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if _supports_thinking(selected_model):
            payload["thinking"] = {"type": "disabled"}
        client = self._client()
        for attempt in range(3):
            response = await client.post(
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=60.0,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(_retry_delay(response, attempt))
                continue
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        raise RuntimeError("GLM chat request exhausted retries")

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        selected_model = model or ZHIPU_CHAT_MODEL
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if _supports_thinking(selected_model):
            payload["thinking"] = {"type": "disabled"}
        client = self._client()
        for attempt in range(3):
            async with client.stream(
                "POST",
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=120.0,
            ) as response:
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await response.aread()
                    await asyncio.sleep(_retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                async for line in response.aiter_lines():
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
                return

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # embedding-3 accepts input as string or list
        payload = {"model": EMBED_MODEL, "input": texts}
        r = await self._client().post(
            f"{self.base}/embeddings",
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        items = sorted(data["data"], key=lambda x: x["index"])
        return [it["embedding"] for it in items]

    async def vision_describe(
        self,
        image_b64: str,
        prompt: str,
        *,
        mime_type: str = "image/jpeg",
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                    },
                ],
            }
        ]
        return await self.chat(messages, model=VISION_MODEL, max_tokens=512)

    async def vision_compare(
        self,
        image_b64: str,
        references: list[dict[str, str]],
        *,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Use only locally curated reference frames to validate a first-pass guess."""
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "第一张图片是游客刚拍摄的目标图。后续每张是带名称的景点参考图。"
                    "请仅根据可见建筑、雕塑、构图判断目标图最像哪一个参考景点；"
                    "没有把握时返回空 candidates。只返回 JSON："
                    '{"summary":"...","candidates":[{"name":"景点名","confidence":0.0,"evidence":"可见对应特征"}]}'
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
        ]
        for reference in references:
            content.append({
                "type": "text",
                "text": f"参考图：{reference['attraction_name']}（名称必须原样使用）",
            })
            content.append({
                "type": "image_url", "image_url": {"url": reference["data_url"]}},
            )
        return await self.chat([{"role": "user", "content": content}], model=VISION_MODEL, max_tokens=512)

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
            "watermark_enabled": False,
        }
        r = await self._client().post(
            f"{self.base}/audio/speech",
            headers=self._headers(),
            json=payload,
            timeout=90.0,
        )
        r.raise_for_status()
        if response_format == "wav":
            return strip_glm_tts_watermark_wav(r.content)
        if response_format == "pcm":
            watermark_filter = GlmTtsWatermarkFilter(24_000)
            return watermark_filter.feed(r.content) + watermark_filter.finish()
        return r.content

    async def tts_stream(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream base64 PCM chunks from GLM-TTS as they arrive."""
        payload = {
            "model": TTS_MODEL,
            "input": text[:2000],
            "voice": voice or TTS_VOICE,
            "speed": speed,
            "volume": 1.0,
            "response_format": "pcm",
            "encode_format": "base64",
            "stream": True,
            "watermark_enabled": False,
        }
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        watermark_filter: Optional[GlmTtsWatermarkFilter] = None
        buffered_event: Optional[dict[str, Any]] = None
        async with self._client().stream(
            "POST",
            f"{self.base}/audio/speech",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    if watermark_filter and not watermark_filter.decided and buffered_event:
                        cleaned = watermark_filter.finish()
                        if cleaned:
                            yield _replace_audio_content(buffered_event, cleaned)
                    break
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError(event["error"].get("message", "GLM-TTS stream failed"))
                choices = event.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                content = delta.get("content")
                if not content:
                    if watermark_filter and not watermark_filter.decided and buffered_event:
                        cleaned = watermark_filter.finish()
                        if cleaned:
                            yield _replace_audio_content(buffered_event, cleaned)
                    yield event
                    continue

                sample_rate = int(delta.get("return_sample_rate") or 24000)
                if watermark_filter is None:
                    watermark_filter = GlmTtsWatermarkFilter(sample_rate)
                elif watermark_filter.sample_rate != sample_rate:
                    raise RuntimeError("GLM-TTS sample rate changed during streaming")
                buffered_event = event
                cleaned = watermark_filter.feed(base64.b64decode(content))
                if cleaned:
                    yield _replace_audio_content(event, cleaned)

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

        r = await self._client().post(
            f"{self.base}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (filename, audio, mime)},
            data={"model": ASR_MODEL},
            timeout=90.0,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.text[:500]}")
        data = r.json()
        return (data.get("text") or "").strip()


def _supports_thinking(model: str) -> bool:
    return model.startswith(("glm-4.5", "glm-4.6", "glm-4.7", "glm-5"))


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "")
    try:
        return min(max(float(retry_after), 0.0), 4.0)
    except ValueError:
        return float(attempt + 1)


zhipu = ZhipuClient()


def _replace_audio_content(event: dict[str, Any], pcm: bytes) -> dict[str, Any]:
    cleaned_event = dict(event)
    choices = [dict(choice) for choice in event.get("choices") or []]
    if not choices:
        return cleaned_event
    delta = dict(choices[0].get("delta") or {})
    delta["content"] = base64.b64encode(pcm).decode("ascii")
    choices[0]["delta"] = delta
    cleaned_event["choices"] = choices
    return cleaned_event
