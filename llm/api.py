from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Callable, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from rag.pipeline import RAGPipeline
from rag.config import (
    LLM_MODEL,
    LOCAL_LITE_LLM_BASE_URL,
    LOCAL_LITE_LLM_LOG_FILE,
    LOCAL_LITE_LLM_MODEL,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_LOG_FILE,
    LOCAL_LLM_MODEL,
)


logger = logging.getLogger("rag-api")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(None, min_length=1, max_length=128)
    stream: bool = True
    interest: Optional[str] = Field(None, max_length=50)
    spot_id: Optional[str] = Field(None, max_length=100)
    context: Optional[dict[str, str]] = None
    model_route: Literal["cloud", "local", "local_lite"] = "cloud"


_OOM_MARKERS = (
    "cuda out of memory",
    "outofmemoryerror",
    "out of memory while trying to allocate",
    "cublas_status_alloc_failed",
)
_GPU_SELECTION_MARKERS = (
    "no candidate gpu has at least",
    "unable to select a gpu",
)


def _compact_error(value: str, limit: int = 700) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else f"{value[:limit]}…"


def _local_log_tail(model_route: str, limit: int = 48_000) -> str:
    log_file = (
        LOCAL_LITE_LLM_LOG_FILE
        if model_route == "local_lite"
        else LOCAL_LLM_LOG_FILE
    )
    try:
        if time.time() - log_file.stat().st_mtime > 30:
            return ""
        with log_file.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def generation_error_message(exc: Exception, model_route: str) -> str:
    """Turn local GPU failures into an actionable message for the visitor UI."""
    raw = str(exc).strip() or exc.__class__.__name__
    is_local = model_route in {"local", "local_lite"}
    evidence = raw
    if is_local:
        evidence = f"{raw}\n{_local_log_tail(model_route)}"
    normalized = evidence.lower()
    if any(marker in normalized for marker in _OOM_MARKERS):
        if model_route == "local":
            action = "请切换到“轻量本地 Qwen3-1.7B”或“云端 GLM”后重试"
            label = "完整本地 Qwen2-7B"
        else:
            action = "请释放 GPU 显存，或切换到“云端 GLM”后重试"
            label = "轻量本地 Qwen3-1.7B"
        return f"{label}发生 CUDA 显存不足（OOM），本次问答未完成。{action}。"
    if is_local and any(marker in normalized for marker in _GPU_SELECTION_MARKERS):
        required = (
            os.getenv("LOCAL_LITE_LLM_GPU_MIN_FREE_MB", "6000")
            if model_route == "local_lite"
            else os.getenv("LOCAL_LLM_GPU_MIN_FREE_MB", "18000")
        )
        label = (
            "轻量本地 Qwen3-1.7B"
            if model_route == "local_lite"
            else "完整本地 Qwen2-7B"
        )
        action = (
            "请释放显存或改用云端 GLM"
            if model_route == "local_lite"
            else "请改用轻量本地 Qwen3-1.7B 或云端 GLM"
        )
        selection_detail = next(
            (
                line.strip()
                for line in raw.splitlines()
                if "candidate GPU has at least" in line
            ),
            raw,
        )
        return (
            f"{label}无法启动：当前没有空闲显存不少于 {required} MiB 的候选 GPU。"
            f"{action}。详情：{_compact_error(selection_detail)}"
        )
    if is_local:
        label = (
            "轻量本地 Qwen3-1.7B"
            if model_route == "local_lite"
            else "完整本地 Qwen2-7B"
        )
        return (
            f"{label}启动或推理失败，本次问答未完成。"
            f"错误：{_compact_error(raw)}；服务日志："
            f"{LOCAL_LITE_LLM_LOG_FILE if model_route == 'local_lite' else LOCAL_LLM_LOG_FILE}"
        )
    return f"云端 GLM 问答失败：{_compact_error(raw)}"


def _user_context(req: ChatRequest) -> dict[str, str]:
    context: dict[str, str] = {}
    if req.interest:
        context["兴趣偏好"] = req.interest[:50]
    if req.spot_id:
        context["当前景点"] = req.spot_id[:100]
    for key, value in (req.context or {}).items():
        if len(context) >= 8:
            break
        clean_key = str(key).strip()[:30]
        clean_value = str(value).strip()[:1000]
        if clean_key and clean_value:
            context[clean_key] = clean_value
    return context


def create_app(
    pipeline_factory: Callable[[], RAGPipeline] = RAGPipeline,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pipeline = await asyncio.to_thread(pipeline_factory)
        app.state.rebuild_lock = asyncio.Lock()
        app.state.session_locks = weakref.WeakValueDictionary()
        try:
            yield
        finally:
            await app.state.pipeline.aclose()

    app = FastAPI(
        title="灵山胜境 RAG Service",
        description=(
            "BGE-M3 + FAISS retrieval with cloud GLM, full local Qwen2-7B, "
            "and lightweight local Qwen3-1.7B routes."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    def pipeline(request: Request) -> RAGPipeline:
        return request.app.state.pipeline

    def session_lock(request: Request, session_id: str) -> asyncio.Lock:
        locks = request.app.state.session_locks
        lock = locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[session_id] = lock
        return lock

    @app.get("/health")
    async def health(request: Request):
        service_stats = pipeline(request).stats()
        healthy = service_stats.get("embedding", {}).get("ready", True)
        return JSONResponse(
            {"ok": healthy, **service_stats},
            status_code=200 if healthy else 503,
        )

    @app.get("/v1/stats")
    async def stats(request: Request):
        return pipeline(request).stats()

    @app.post("/v1/warmup")
    async def warmup(request: Request):
        try:
            result = await asyncio.to_thread(pipeline(request).warmup)
        except Exception as exc:
            logger.exception("RAG embedding warmup failed")
            raise HTTPException(503, f"RAG warmup failed: {exc}") from exc
        return {"ok": True, **result}

    @app.get("/v1/model-routes")
    async def model_routes():
        async def ready(base_url: str) -> bool:
            health_url = f"{base_url.removesuffix('/v1')}/health"
            try:
                async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                    response = await client.get(health_url)
                    return response.is_success
            except httpx.HTTPError:
                return False

        local_ready, local_lite_ready = await asyncio.gather(
            ready(LOCAL_LLM_BASE_URL),
            ready(LOCAL_LITE_LLM_BASE_URL),
        )
        return {
            "default": "cloud",
            "routes": {
                "cloud": {
                    "label": "GLM API",
                    "model": LLM_MODEL,
                    "ready": True,
                    "uses_local_gpu": False,
                },
                "local": {
                    "label": "完整本地 Qwen2-7B",
                    "model": Path(LOCAL_LLM_MODEL).name,
                    "ready": local_ready,
                    "uses_local_gpu": True,
                    "idle_unload": True,
                    "auto_start": True,
                    "required_free_mb": int(
                        os.getenv("LOCAL_LLM_GPU_MIN_FREE_MB", "18000")
                    ),
                },
                "local_lite": {
                    "label": "轻量本地 Qwen3-1.7B",
                    "model": Path(LOCAL_LITE_LLM_MODEL).name,
                    "ready": local_lite_ready,
                    "uses_local_gpu": True,
                    "idle_unload": True,
                    "auto_start": True,
                    "oom_fallback": True,
                    "required_free_mb": int(
                        os.getenv("LOCAL_LITE_LLM_GPU_MIN_FREE_MB", "6000")
                    ),
                },
            },
        }

    @app.post("/v1/chat")
    async def chat(req: ChatRequest, request: Request):
        session_id = req.session_id or str(uuid.uuid4())
        context = _user_context(req)
        lock = session_lock(request, session_id)

        if not req.stream:
            try:
                async with lock:
                    result = await pipeline(request).aquery_result(
                        req.message,
                        session_id=session_id,
                        user_context=context,
                        model_route=req.model_route,
                    )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:
                logger.exception("RAG non-streaming chat failed")
                raise HTTPException(
                    502, generation_error_message(exc, req.model_route)
                ) from exc
            return {
                "session_id": session_id,
                "answer": result.answer,
                "citations": [citation.as_dict() for citation in result.citations],
                "history_turns": result.history_turns,
                "retrieval_ms": result.retrieval_ms,
                "latency_ms": result.latency_ms,
                "model_route": req.model_route,
            }

        async def event_stream() -> AsyncIterator[str]:
            try:
                async with lock:
                    async for event in pipeline(request).astream(
                        req.message,
                        session_id=session_id,
                        user_context=context,
                        model_route=req.model_route,
                    ):
                        data = event.as_dict()
                        if event.type == "meta":
                            data["session_id"] = session_id
                            data["model_route"] = req.model_route
                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("RAG streaming chat failed")
                error = {
                    "type": "error",
                    "message": generation_error_message(exc, req.model_route),
                }
                yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/v1/sessions/{session_id}")
    async def clear_session(session_id: str, request: Request):
        if not 1 <= len(session_id) <= 128:
            raise HTTPException(400, "invalid session id")
        return {
            "ok": True,
            "cleared": pipeline(request).clear_session(session_id),
        }

    @app.post("/v1/index/rebuild")
    async def rebuild_index(request: Request):
        lock = request.app.state.rebuild_lock
        if lock.locked():
            raise HTTPException(409, "RAG index rebuild is already running")
        try:
            async with lock:
                result = await asyncio.to_thread(pipeline(request).rebuild_index)
        except Exception as exc:
            logger.exception("RAG index rebuild failed")
            raise HTTPException(500, f"RAG index rebuild failed: {exc}") from exc
        return {"ok": True, **result}

    return app


app = create_app()
