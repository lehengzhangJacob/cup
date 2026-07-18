from __future__ import annotations

import base64
import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import CORS_ORIGINS, DATA_DIR, LOG_DB, TTS_VOICE, load_api_key
from .kb import ROUTES, kb
from .zhipu import zhipu

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


SYSTEM_PROMPT = """你是「灵山胜境」景区AI数字人导游，名字叫「灵山小向导」。
严格依据检索到的官方资料回答，不要编造未出现的数字、日期、高度、重量。
若资料不足，诚实说明「当前知识库未覆盖」，并建议游客换个问法或前往游客中心。
回答简洁亲切，可带轻微佛教文化气息，但不要说教。
先用一个不超过30字的完整短句直接回答核心问题，再补充必要细节。
在回复末尾单独一行输出 JSON 元数据（不要用代码块）：
{"emotion":"smile|calm|solemn|surprise","spot_hints":["景点名"],"citations":["资料片段编号"]}
"""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    interest: Optional[str] = Field(None, description="历史/自然/亲子")
    stream: bool = True
    spot_id: Optional[str] = None


class RecommendRequest(BaseModel):
    interest: str = Field(..., description="历史/自然/亲子 或 history/nature/family")


class LocateRequest(BaseModel):
    mode: str = Field(..., description="gps|qr|manual|wifi")
    lat: Optional[float] = None
    lng: Optional[float] = None
    code: Optional[str] = None
    spot_name: Optional[str] = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = None
    speed: float = 1.0


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOG_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            meta TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _log(session_id: str, role: str, content: str, meta: Optional[dict] = None) -> None:
    conn = _db()
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            session_id,
            role,
            content,
            json.dumps(meta or {}, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _build_context(chunks: list) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[片段{i}|{c.id}|{c.title}]\n{c.text}")
    return "\n\n".join(parts)


async def _retrieve(query: str):
    query_vec = None
    try:
        if any(c.embedding for c in kb.chunks):
            query_vec = (await zhipu.embed([query]))[0]
    except Exception:
        query_vec = None
    return kb.hybrid_search(query, query_vec=query_vec, top_k=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_api_key()
    kb.load()
    # try build embeddings if missing (best effort, keyword still works)
    if kb.chunks and not any(c.embedding for c in kb.chunks):
        try:
            texts = [c.text[:800] for c in kb.chunks]
            # batch to avoid huge payload
            embs: list[list[float]] = []
            batch = 16
            for i in range(0, len(texts), batch):
                embs.extend(await zhipu.embed(texts[i : i + batch]))
            kb.set_embeddings(embs)
        except Exception as e:
            print(f"[warn] embedding skipped: {e}")
    yield


app = FastAPI(
    title="灵山胜境 AI 数字人导览 API",
    description="软件杯 A5 开放接口：供浏览器/APK/第三方客户端调用。服务端调用智谱 GLM。",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "chunks": len(kb.chunks),
        "has_embeddings": bool(kb.chunks and kb.chunks[0].embedding),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/routes")
async def list_routes():
    return {"routes": ROUTES}


@app.post("/v1/recommend")
async def recommend(req: RecommendRequest):
    mapping = {
        "历史": "history",
        "历史文化": "history",
        "history": "history",
        "自然": "nature",
        "风光": "nature",
        "nature": "nature",
        "亲子": "family",
        "家庭": "family",
        "family": "family",
    }
    rid = mapping.get(req.interest.strip().lower(), mapping.get(req.interest.strip(), "history"))
    route = next((r for r in ROUTES if r["id"] == rid), ROUTES[0])
    return {"interest": req.interest, "route": route}


@app.post("/v1/locate")
async def locate(req: LocateRequest):
    """弱定位：gps / qr / manual / wifi 三级降级。"""
    spots = {
        "LS-001": "灵山大照壁",
        "LS-006": "九龙灌浴",
        "LS-FO": "灵山大佛",
        "LS-FG": "灵山梵宫",
        "LS-WY": "五印坛城",
    }
    if req.mode == "gps":
        # demo: without real geo DB, return nearest symbolic spot
        return {
            "mode": "gps",
            "resolved": True,
            "spot_name": "灵山大佛",
            "note": "GPS可用，已匹配中轴核心景点（演示逻辑，可替换真实坐标库）。",
        }
    if req.mode == "qr":
        name = spots.get(req.code or "", req.code or "未知景点")
        return {"mode": "qr", "resolved": True, "spot_name": name, "code": req.code}
    if req.mode == "wifi":
        return {
            "mode": "wifi",
            "resolved": True,
            "spot_name": "南门/入口区",
            "note": "模拟锐捷 WiFi/边端入园节点定位。",
        }
    # manual
    return {
        "mode": "manual",
        "resolved": True,
        "spot_name": req.spot_name or "灵山大佛",
        "note": "用户手动选择景点。",
    }


@app.get("/v1/kb/stats")
async def kb_stats():
    return {
        "chunk_count": len(kb.chunks),
        "sources": sorted({c.source for c in kb.chunks}),
        "embedded": sum(1 for c in kb.chunks if c.embedding),
    }


@app.post("/v1/kb/rebuild")
async def kb_rebuild():
    n = kb.rebuild_from_docs()
    return {"ok": True, "chunks": n}


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    chunks = await _retrieve(req.message)
    context = _build_context(chunks) if chunks else "（未检索到相关资料）"
    interest_line = f"游客兴趣偏好：{req.interest}" if req.interest else ""
    spot_line = f"当前景点上下文：{req.spot_id}" if req.spot_id else ""
    user_content = (
        f"{interest_line}\n{spot_line}\n\n"
        f"【检索资料】\n{context}\n\n"
        f"【游客提问】\n{req.message}"
    ).strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    _log(session_id, "user", req.message, {"chunk_ids": [c.id for c in chunks]})

    if not req.stream:
        t0 = time.time()
        answer = await zhipu.chat(messages)
        _log(session_id, "assistant", answer, {"latency_ms": int((time.time() - t0) * 1000)})
        return {
            "session_id": session_id,
            "answer": answer,
            "citations": [{"id": c.id, "title": c.title} for c in chunks],
            "latency_ms": int((time.time() - t0) * 1000),
        }

    async def event_gen():
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id, 'citations': [{'id': c.id, 'title': c.title} for c in chunks]}, ensure_ascii=False)}\n\n"
        parts: list[str] = []
        t0 = time.time()
        async for token in zhipu.chat_stream(messages):
            parts.append(token)
            yield f"data: {json.dumps({'type': 'delta', 'content': token}, ensure_ascii=False)}\n\n"
        full = "".join(parts)
        _log(
            session_id,
            "assistant",
            full,
            {"latency_ms": int((time.time() - t0) * 1000)},
        )
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': int((time.time() - t0) * 1000)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/v1/tts")
async def tts(req: TTSRequest):
    """智谱 GLM-TTS 语音合成，返回 wav 音频。"""
    text = req.text.strip()
    # strip trailing meta json line for cleaner speech
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("{")]
    speak = "\n".join(lines).strip() or text
    try:
        audio = await zhipu.tts(speak, voice=req.voice or TTS_VOICE, speed=req.speed)
    except Exception as e:
        raise HTTPException(502, f"tts failed: {e}") from e
    return Response(content=audio, media_type="audio/wav")


@app.post("/v1/tts/stream")
async def tts_stream(req: TTSRequest):
    """Stream GLM-TTS PCM chunks as SSE so playback can start at the first frame."""
    text = req.text.strip()
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("{")]
    speak = "\n".join(lines).strip() or text

    async def event_gen():
        try:
            async for event in zhipu.tts_stream(
                speak,
                voice=req.voice or TTS_VOICE,
                speed=req.speed,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"error": {"message": f"tts stream failed: {exc}"}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def _normalize_asr_audio(raw: bytes, filename: str) -> tuple[bytes, str]:
    """Ensure payload is something glm-asr accepts (prefer wav)."""
    name = (filename or "audio.wav").lower()
    if _looks_like_wav(raw) or name.endswith((".wav", ".mp3", ".m4a")):
        if _looks_like_wav(raw) and not name.endswith(".wav"):
            return raw, "audio.wav"
        return raw, filename or "audio.wav"

    # browser often sends webm/ogg — try ffmpeg if present
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(
            400,
            "当前音频格式(webm/ogg)不被识别接口支持。请用页面「按住说话」(会录成 wav)，或上传 wav/mp3。",
        )
    suffix = ".webm" if "webm" in name else ".ogg"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(raw)
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dst.exists():
            raise HTTPException(400, f"音频转码失败: {proc.stderr[-300:]}")
        return dst.read_bytes(), "audio.wav"


@app.post("/v1/asr")
async def asr(file: UploadFile = File(...)):
    """智谱语音识别。推荐上传 wav/mp3；webm 需本机有 ffmpeg。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty audio")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(400, "audio too large")
    name = file.filename or "audio.wav"
    try:
        audio, fname = _normalize_asr_audio(raw, name)
        text = await zhipu.asr(audio, filename=fname)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"asr failed: {e}") from e
    return {"text": text}


@app.post("/v1/vision/guide")
async def vision_guide(file: UploadFile = File(...), question: str = "这是灵山胜境的哪个景点？请结合景区知识讲解。"):
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "image too large")
    b64 = base64.b64encode(raw).decode("ascii")
    # first let vision describe, then ground with RAG
    vision_text = await zhipu.vision_describe(
        b64,
        "请识别图片中可能的景区建筑/雕像/场景，用中文简短描述关键视觉特征与可能景点名。",
    )
    chunks = await _retrieve(vision_text + " " + question)
    context = _build_context(chunks)
    answer = await zhipu.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"视觉识别结果：{vision_text}\n\n"
                    f"【检索资料】\n{context}\n\n"
                    f"游客问题：{question}\n"
                    "请结合资料给出导览讲解。"
                ),
            },
        ]
    )
    return {
        "vision": vision_text,
        "answer": answer,
        "citations": [{"id": c.id, "title": c.title} for c in chunks],
    }


@app.get("/v1/stats/overview")
async def stats_overview():
    conn = _db()
    cur = conn.execute("SELECT COUNT(*) FROM chat_logs WHERE role='user'")
    users = cur.fetchone()[0]
    cur = conn.execute(
        "SELECT content FROM chat_logs WHERE role='user' ORDER BY created_at DESC LIMIT 200"
    )
    recent = [r[0] for r in cur.fetchall()]
    conn.close()
    # naive hot keywords
    hot = ["灵山大佛", "梵宫", "九龙灌浴", "祥符禅寺", "路线", "五印坛城"]
    counts = {k: sum(1 for q in recent if k in q) for k in hot}
    return {
        "service_turns": users,
        "hot_topics": sorted(
            [{"name": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "routes": ROUTES,
    }


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "name": "Lingshan AI Guide API",
        "docs": "/docs",
        "health": "/health",
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
