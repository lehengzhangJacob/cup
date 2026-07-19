from __future__ import annotations

import asyncio
import json
import logging
import uuid
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Callable, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from rag.pipeline import RAGPipeline
from rag.config import LLM_MODEL, LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL


logger = logging.getLogger("rag-api")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(None, min_length=1, max_length=128)
    stream: bool = True
    interest: Optional[str] = Field(None, max_length=50)
    spot_id: Optional[str] = Field(None, max_length=100)
    context: Optional[dict[str, str]] = None
    model_route: Literal["cloud", "local"] = "cloud"


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
        description="BGE-M3 + FAISS retrieval with cloud GLM and local model routes.",
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
        return {"ok": True, **pipeline(request).stats()}

    @app.get("/v1/stats")
    async def stats(request: Request):
        return pipeline(request).stats()

    @app.get("/v1/model-routes")
    async def model_routes():
        health_url = f"{LOCAL_LLM_BASE_URL.removesuffix('/v1')}/health"
        local_ready = False
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                response = await client.get(health_url)
                local_ready = response.is_success
        except httpx.HTTPError:
            pass
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
                    "label": "本地 Qwen2-7B",
                    "model": Path(LOCAL_LLM_MODEL).name,
                    "ready": local_ready,
                    "uses_local_gpu": True,
                    "idle_unload": True,
                    "auto_start": True,
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
                raise HTTPException(502, f"RAG generation failed: {exc}") from exc
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
                    "message": f"RAG generation failed: {exc}",
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
