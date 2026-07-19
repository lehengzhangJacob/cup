from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from .config import (
    RAG_CONNECT_TIMEOUT_SECONDS,
    RAG_READ_TIMEOUT_SECONDS,
    RAG_URL,
)


class RAGClientError(RuntimeError):
    pass


class RAGClient:
    def __init__(
        self,
        *,
        base_url: str = RAG_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = httpx.Timeout(
            connect=RAG_CONNECT_TIMEOUT_SECONDS,
            read=RAG_READ_TIMEOUT_SECONDS,
            write=30.0,
            pool=5.0,
        )

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health", timeout=5.0)

    async def stats(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/stats")

    async def warmup(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/warmup",
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
        )

    async def model_routes(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/model-routes", timeout=5.0)

    async def rebuild(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/index/rebuild",
            timeout=httpx.Timeout(connect=5.0, read=900.0, write=30.0, pool=5.0),
        )

    async def clear_session(self, session_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/v1/sessions/{session_id}")

    async def chat(
        self,
        message: str,
        *,
        session_id: str,
        interest: Optional[str] = None,
        spot_id: Optional[str] = None,
        context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/chat",
            json={
                "message": message,
                "session_id": session_id,
                "interest": interest,
                "spot_id": spot_id,
                "context": context,
                "model_route": model_route,
                "stream": False,
            },
        )

    async def chat_stream(
        self,
        message: str,
        *,
        session_id: str,
        interest: Optional[str] = None,
        spot_id: Optional[str] = None,
        context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "message": message,
            "session_id": session_id,
            "interest": interest,
            "spot_id": spot_id,
            "context": context,
            "model_route": model_route,
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat",
                    json=payload,
                ) as response:
                    if response.is_error:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise RAGClientError(
                            f"RAG service returned {response.status_code}: {body[:500]}"
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise RAGClientError("RAG service returned invalid SSE JSON") from exc
                        if not isinstance(event, dict):
                            raise RAGClientError("RAG service returned a non-object SSE event")
                        if event.get("type") == "error":
                            raise RAGClientError(str(event.get("message") or "RAG stream failed"))
                        yield event
        except RAGClientError:
            raise
        except httpx.HTTPError as exc:
            raise RAGClientError(f"RAG service unavailable: {exc}") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict[str, Any]] = None,
        timeout: Any = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=timeout or self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RAGClientError(f"RAG service unavailable: {exc}") from exc
        if not isinstance(data, dict):
            raise RAGClientError("RAG service returned an invalid JSON response")
        return data


rag = RAGClient()
