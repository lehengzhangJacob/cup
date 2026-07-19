from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from .config import DEEPSEEK_BASE, DEEPSEEK_MODEL, load_deepseek_api_key


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base: str = DEEPSEEK_BASE,
        model: str = DEEPSEEK_MODEL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key
        self.base = base.rstrip("/")
        self.model = model
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key or load_deepseek_api_key()}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "thinking": {"type": "disabled"},
        }

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        async with httpx.AsyncClient(
            timeout=60.0,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async with httpx.AsyncClient(
            timeout=120.0,
            transport=self.transport,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
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


deepseek = DeepSeekClient()
