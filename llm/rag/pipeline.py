from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Optional

from openai import AsyncOpenAI, OpenAI
import httpx

from rag.config import (
    EMBED_MODEL,
    LLM_BASE_URL,
    LLM_FALLBACK_MODELS,
    LLM_FIRST_TOKEN_TIMEOUT_SECONDS,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LOCAL_LLM_API_KEY,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_LAST_USED_FILE,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_START_SCRIPT,
    QUESTION_MAX_CHARS,
    RETRIEVAL_HISTORY_TURNS,
    load_llm_api_key,
)
from rag.prompt_builder import build_messages
from rag.index_builder import build_index
from rag.retriever import Retriever
from rag.session_store import ConversationStore, ConversationTurn


_FOLLOW_UP_RE = re.compile(
    r"(它|这个|那个|这里|那里|刚才|上面|前面|该景点|该建筑|还有|那么|然后|呢|多高|多久|怎么走)"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Citation:
    id: str
    title: str
    source: str
    section: str = ""
    score: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "source": self.source,
        }
        if self.section:
            data["section"] = self.section
        if self.score is not None:
            data["score"] = round(self.score, 4)
        return data


@dataclass(frozen=True)
class RAGResponse:
    answer: str
    citations: list[Citation]
    history_turns: int
    retrieval_ms: int
    latency_ms: int


@dataclass(frozen=True)
class RAGStreamEvent:
    type: str
    content: str = ""
    citations: list[Citation] = field(default_factory=list)
    history_turns: int = 0
    retrieval_ms: int = 0
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type}
        if self.content:
            data["content"] = self.content
        if self.citations:
            data["citations"] = [citation.as_dict() for citation in self.citations]
        if self.type == "meta":
            data["history_turns"] = self.history_turns
            data["retrieval_ms"] = self.retrieval_ms
        if self.type == "done":
            data["latency_ms"] = self.latency_ms
        return data


@dataclass(frozen=True)
class _PreparedQuery:
    question: str
    session_id: Optional[str]
    messages: list[dict[str, str]]
    citations: list[Citation]
    history_turns: int
    retrieval_ms: int


class RAGPipeline:
    """BGE-M3 + FAISS retrieval with cloud and local generation routes."""

    def __init__(
        self,
        *,
        retriever=None,
        client=None,
        async_client=None,
        local_client=None,
        local_async_client=None,
        sessions: Optional[ConversationStore] = None,
    ) -> None:
        self._retriever = retriever or Retriever()
        self._client = client
        self._async_client = async_client
        self._local_client = local_client
        self._local_async_client = local_async_client
        self._manage_local_service = local_client is None and local_async_client is None
        self.sessions = sessions or ConversationStore()
        self._retriever_lock = threading.RLock()

    def query(
        self,
        question: str,
        *,
        session_id: Optional[str] = None,
        user_context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> str:
        return self.query_result(
            question,
            session_id=session_id,
            user_context=user_context,
            model_route=model_route,
        ).answer

    def query_result(
        self,
        question: str,
        *,
        session_id: Optional[str] = None,
        user_context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> RAGResponse:
        started = time.perf_counter()
        prepared = self._prepare(question, session_id, user_context)
        self._prepare_model_route(model_route)
        completion = self._get_client(model_route).chat.completions.create(
            model=self._model_for_route(model_route),
            messages=prepared.messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            stream=False,
            **self._completion_extras(model_route),
        )
        self._mark_local_used(model_route)
        answer = self._message_content(completion).strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        self.sessions.append(session_id, prepared.question, answer)
        return RAGResponse(
            answer=answer,
            citations=prepared.citations,
            history_turns=prepared.history_turns,
            retrieval_ms=prepared.retrieval_ms,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def aquery_result(
        self,
        question: str,
        *,
        session_id: Optional[str] = None,
        user_context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> RAGResponse:
        started = time.perf_counter()
        prepared = await asyncio.to_thread(
            self._prepare, question, session_id, user_context
        )
        await self._prepare_model_route_async(model_route)
        completion = await self._get_async_client(model_route).chat.completions.create(
            model=self._model_for_route(model_route),
            messages=prepared.messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            stream=False,
            **self._completion_extras(model_route),
        )
        self._mark_local_used(model_route)
        answer = self._message_content(completion).strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        self.sessions.append(session_id, prepared.question, answer)
        return RAGResponse(
            answer=answer,
            citations=prepared.citations,
            history_turns=prepared.history_turns,
            retrieval_ms=prepared.retrieval_ms,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def stream(
        self,
        question: str,
        *,
        session_id: Optional[str] = None,
        user_context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> Iterator[RAGStreamEvent]:
        started = time.perf_counter()
        prepared = self._prepare(question, session_id, user_context)
        yield RAGStreamEvent(
            type="meta",
            citations=prepared.citations,
            history_turns=prepared.history_turns,
            retrieval_ms=prepared.retrieval_ms,
        )
        answer_parts: list[str] = []
        self._prepare_model_route(model_route)
        completion = self._get_client(model_route).chat.completions.create(
            model=self._model_for_route(model_route),
            messages=prepared.messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            stream=True,
            **self._completion_extras(model_route),
        )
        for chunk in completion:
            content = self._delta_content(chunk)
            if content:
                answer_parts.append(content)
                yield RAGStreamEvent(type="delta", content=content)
        self._mark_local_used(model_route)
        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        self.sessions.append(session_id, prepared.question, answer)
        yield RAGStreamEvent(
            type="done",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def astream(
        self,
        question: str,
        *,
        session_id: Optional[str] = None,
        user_context: Optional[dict[str, str]] = None,
        model_route: str = "cloud",
    ) -> AsyncIterator[RAGStreamEvent]:
        started = time.perf_counter()
        prepared = await asyncio.to_thread(
            self._prepare, question, session_id, user_context
        )
        yield RAGStreamEvent(
            type="meta",
            citations=prepared.citations,
            history_turns=prepared.history_turns,
            retrieval_ms=prepared.retrieval_ms,
        )
        answer_parts: list[str] = []
        await self._prepare_model_route_async(model_route)
        primary_model = self._model_for_route(model_route)
        models = [primary_model]
        if model_route == "cloud":
            models.extend(
                model
                for model in LLM_FALLBACK_MODELS
                if model not in models
            )
        for model_index, selected_model in enumerate(models):
            completion = None
            attempt_parts: list[str] = []
            first_token_deadline = (
                asyncio.get_running_loop().time()
                + LLM_FIRST_TOKEN_TIMEOUT_SECONDS
            )
            try:
                create_call = self._get_async_client(
                    model_route
                ).chat.completions.create(
                    model=selected_model,
                    messages=prepared.messages,
                    temperature=LLM_TEMPERATURE,
                    max_tokens=LLM_MAX_TOKENS,
                    stream=True,
                    **self._completion_extras(model_route, selected_model),
                )
                if model_route == "cloud":
                    completion = await asyncio.wait_for(
                        create_call,
                        timeout=LLM_FIRST_TOKEN_TIMEOUT_SECONDS,
                    )
                else:
                    completion = await create_call
                iterator = completion.__aiter__()
                while True:
                    try:
                        if model_route == "cloud" and not attempt_parts:
                            remaining = max(
                                0.01,
                                first_token_deadline
                                - asyncio.get_running_loop().time(),
                            )
                            chunk = await asyncio.wait_for(
                                anext(iterator),
                                timeout=remaining,
                            )
                        else:
                            chunk = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    content = self._delta_content(chunk)
                    if content:
                        attempt_parts.append(content)
                        yield RAGStreamEvent(type="delta", content=content)
                if not attempt_parts:
                    raise RuntimeError("LLM returned an empty answer")
                answer_parts = attempt_parts
                break
            except Exception as exc:
                if attempt_parts or model_index == len(models) - 1:
                    raise
                if completion is not None and hasattr(completion, "close"):
                    await completion.close()
                logger.warning(
                    "Cloud model %s failed before first token; trying %s: %s",
                    selected_model,
                    models[model_index + 1],
                    exc,
                )
        self._mark_local_used(model_route)
        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        self.sessions.append(session_id, prepared.question, answer)
        yield RAGStreamEvent(
            type="done",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def clear_session(self, session_id: str) -> bool:
        return self.sessions.clear(session_id)

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.close()
        if self._client is not None:
            self._client.close()
        if self._local_async_client is not None:
            await self._local_async_client.close()
        if self._local_client is not None:
            self._local_client.close()
        with self._retriever_lock:
            embedder = getattr(self._retriever, "embedder", None)
        if embedder is not None and hasattr(embedder, "close"):
            embedder.close()

    def replace_retriever(self, retriever) -> None:
        with self._retriever_lock:
            self._retriever = retriever

    def rebuild_index(self) -> dict[str, Any]:
        """Rebuild on disk, then swap in a validated retriever without downtime."""
        with self._retriever_lock:
            embedder = self._retriever.embedder
        result = build_index(embedder=embedder)
        replacement = Retriever(embedder=embedder)
        self.replace_retriever(replacement)
        return result

    def stats(self) -> dict[str, Any]:
        retriever_stats = self._retriever.stats()
        return {
            **retriever_stats,
            "model": LLM_MODEL,
            "model_routes": {
                "cloud": {"model": LLM_MODEL, "uses_gpu": False},
                "local": {"model": LOCAL_LLM_MODEL, "uses_gpu": True},
            },
            "embedding_model": EMBED_MODEL,
            **self.sessions.stats(),
        }

    def warmup(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self._retriever_lock:
            self._retriever.retrieve("灵山胜境")
            embedding = self._retriever.stats().get("embedding", {})
        return {
            "ready": True,
            "retrieval_ms": int((time.perf_counter() - started) * 1000),
            "embedding": embedding,
        }

    def _prepare(
        self,
        question: str,
        session_id: Optional[str],
        user_context: Optional[dict[str, str]],
    ) -> _PreparedQuery:
        question = str(question).strip()
        if not question:
            raise ValueError("question must not be empty")
        if len(question) > QUESTION_MAX_CHARS:
            raise ValueError(f"question exceeds {QUESTION_MAX_CHARS} characters")
        history = self.sessions.get(session_id)
        retrieval_query = self._retrieval_query(question, history, user_context)
        retrieval_started = time.perf_counter()
        with self._retriever_lock:
            chunks = self._retriever.retrieve(retrieval_query)
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
        messages = build_messages(
            chunks,
            question,
            history=history,
            user_context=user_context,
        )
        return _PreparedQuery(
            question=question,
            session_id=session_id,
            messages=messages,
            citations=self._citations(chunks),
            history_turns=len(history),
            retrieval_ms=retrieval_ms,
        )

    @staticmethod
    def _retrieval_query(
        question: str,
        history: list[ConversationTurn],
        user_context: Optional[dict[str, str]],
    ) -> str:
        parts: list[str] = []
        for key in ("当前景点", "视觉识别结果"):
            value = str((user_context or {}).get(key, "")).strip()
            if value:
                parts.append(f"{key}：{value}")
        contextual = bool(history) and (
            len(question) <= 14 or _FOLLOW_UP_RE.search(question) is not None
        )
        if contextual:
            recent = history[-RETRIEVAL_HISTORY_TURNS:]
            parts.extend(f"上一问题：{turn.user}" for turn in recent)
        parts.append(f"当前问题：{question}")
        return "\n".join(parts)

    @staticmethod
    def _citations(chunks: list[dict]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[str] = set()
        for chunk in chunks:
            metadata = chunk.get("metadata") or {}
            source = str(metadata.get("source") or "unknown")
            name = str(
                metadata.get("attraction_name")
                or metadata.get("scenic_area")
                or "景区资料"
            )
            section = str(metadata.get("section") or "")
            digest = hashlib.sha1(
                f"{source}\0{name}\0{section}\0{chunk.get('text', '')}".encode("utf-8")
            ).hexdigest()[:12]
            citation_id = f"{source}-{digest}"
            if citation_id in seen:
                continue
            seen.add(citation_id)
            title = f"{name} · {section}" if section else name
            citations.append(
                Citation(
                    id=citation_id,
                    title=title,
                    source=source,
                    section=section,
                    score=chunk.get("score"),
                )
            )
        return citations

    def _get_client(self, model_route: str = "cloud"):
        if model_route == "local":
            if self._local_client is None:
                self._local_client = OpenAI(
                    api_key=LOCAL_LLM_API_KEY,
                    base_url=LOCAL_LLM_BASE_URL,
                )
            return self._local_client
        if model_route != "cloud":
            raise ValueError(f"unsupported model route: {model_route}")
        if self._client is None:
            self._client = OpenAI(
                api_key=load_llm_api_key(),
                base_url=LLM_BASE_URL,
            )
        return self._client

    def _get_async_client(self, model_route: str = "cloud"):
        if model_route == "local":
            if self._local_async_client is None:
                self._local_async_client = AsyncOpenAI(
                    api_key=LOCAL_LLM_API_KEY,
                    base_url=LOCAL_LLM_BASE_URL,
                )
            return self._local_async_client
        if model_route != "cloud":
            raise ValueError(f"unsupported model route: {model_route}")
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=load_llm_api_key(),
                base_url=LLM_BASE_URL,
            )
        return self._async_client

    def _prepare_model_route(self, model_route: str) -> None:
        self._model_for_route(model_route)
        if model_route == "local" and self._manage_local_service:
            self._ensure_local_service()

    async def _prepare_model_route_async(self, model_route: str) -> None:
        self._model_for_route(model_route)
        if model_route == "local" and self._manage_local_service:
            await asyncio.to_thread(self._ensure_local_service)

    @staticmethod
    def _ensure_local_service() -> None:
        health_url = f"{LOCAL_LLM_BASE_URL.removesuffix('/v1')}/health"
        try:
            response = httpx.get(health_url, timeout=1.0, trust_env=False)
            response.raise_for_status()
        except httpx.HTTPError:
            completed = subprocess.run(
                ["bash", str(LOCAL_LLM_START_SCRIPT)],
                cwd=str(LOCAL_LLM_START_SCRIPT.parent.parent),
                capture_output=True,
                text=True,
                timeout=90,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"local LLM failed to start: {detail}")
        LOCAL_LLM_LAST_USED_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_LLM_LAST_USED_FILE.touch()

    def _mark_local_used(self, model_route: str) -> None:
        if model_route == "local" and self._manage_local_service:
            LOCAL_LLM_LAST_USED_FILE.touch()

    @staticmethod
    def _model_for_route(model_route: str) -> str:
        if model_route == "cloud":
            return LLM_MODEL
        if model_route == "local":
            return LOCAL_LLM_MODEL
        raise ValueError(f"unsupported model route: {model_route}")

    @staticmethod
    def _completion_extras(
        model_route: str,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        selected_model = model or LLM_MODEL
        if model_route == "cloud" and selected_model.startswith(
            ("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")
        ):
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {}

    @staticmethod
    def _message_content(completion: Any) -> str:
        choices = getattr(completion, "choices", None) or []
        if not choices:
            return ""
        return getattr(getattr(choices[0], "message", None), "content", None) or ""

    @staticmethod
    def _delta_content(chunk: Any) -> str:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        return getattr(getattr(choices[0], "delta", None), "content", None) or ""
