from __future__ import annotations

import base64
import io
import json
import sqlite3
import time
import uuid
import wave
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    CORS_ORIGINS,
    DATA_DIR,
    DOCS_DIR,
    LOG_DB,
    LIVETALKING_AVATAR_ID,
    LIVETALKING_ENABLED,
    LIVETALKING_URL,
    TTS_VOICE,
    ROOT,
    UPLOADS_DIR,
    XMOV_APP_ID,
    XMOV_APP_SECRET,
    XMOV_AUTH_HEADER,
    XMOV_BROWSER_CONFIG_ENABLED,
    XMOV_SDK_URL,
    XMOV_SESSION_GATEWAY_URL,
    load_api_key,
)
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


class LiveTalkingOfferRequest(BaseModel):
    sdp: str = Field(..., min_length=1)
    type: str = "offer"
    avatar: Optional[str] = None


class LiveTalkingSpeakRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=2000)
    interrupt: bool = False


class LiveTalkingSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field("", max_length=1000)


class AvatarSettingsRequest(BaseModel):
    display_name: str = Field("灵山小向导", min_length=1, max_length=30)
    avatar_id: str = Field(LIVETALKING_AVATAR_ID, min_length=1, max_length=100)
    voice: str = Field(TTS_VOICE, min_length=1, max_length=50)
    costume: str = Field("禅意导游", max_length=50)
    expression: str = Field("亲切自然", max_length=50)


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            rating INTEGER NOT NULL,
            comment TEXT,
            sentiment TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS avatar_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            display_name TEXT NOT NULL,
            avatar_id TEXT NOT NULL,
            voice TEXT NOT NULL,
            costume TEXT NOT NULL,
            expression TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _infer_sentiment(text: str, rating: Optional[int] = None) -> str:
    if rating is not None:
        if rating >= 4:
            return "positive"
        if rating <= 2:
            return "negative"
    positive = ("喜欢", "满意", "很好", "不错", "漂亮", "方便", "感谢", "推荐", "开心")
    negative = ("不满", "失望", "不好", "太慢", "拥挤", "排队", "投诉", "贵", "累", "生气")
    positive_hits = sum(word in text for word in positive)
    negative_hits = sum(word in text for word in negative)
    if positive_hits > negative_hits:
        return "positive"
    if negative_hits > positive_hits:
        return "negative"
    return "neutral"


def _avatar_settings() -> dict[str, str]:
    conn = _db()
    row = conn.execute(
        "SELECT display_name, avatar_id, voice, costume, expression, updated_at "
        "FROM avatar_settings WHERE id=1"
    ).fetchone()
    conn.close()
    if row:
        return {
            "display_name": row[0],
            "avatar_id": row[1],
            "voice": row[2],
            "costume": row[3],
            "expression": row[4],
            "updated_at": row[5],
        }
    return {
        "display_name": "灵山小向导",
        "avatar_id": LIVETALKING_AVATAR_ID,
        "voice": TTS_VOICE,
        "costume": "禅意导游",
        "expression": "亲切自然",
        "updated_at": "",
    }


def _available_avatars() -> list[str]:
    avatar_dir = ROOT / "LiveTalking" / "data" / "avatars"
    if not avatar_dir.exists():
        return [LIVETALKING_AVATAR_ID]
    avatars = sorted(path.name for path in avatar_dir.iterdir() if path.is_dir())
    return avatars or [LIVETALKING_AVATAR_ID]


def _log(session_id: str, role: str, content: str, meta: Optional[dict] = None) -> None:
    stored_meta = dict(meta or {})
    if role == "user" and "sentiment" not in stored_meta:
        stored_meta["sentiment"] = _infer_sentiment(content)
    conn = _db()
    conn.execute(
        "INSERT INTO chat_logs VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            session_id,
            role,
            content,
            json.dumps(stored_meta, ensure_ascii=False),
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


async def _refresh_embeddings() -> bool:
    if not kb.chunks:
        return False
    try:
        texts = [c.text[:800] for c in kb.chunks]
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), 16):
            embeddings.extend(await zhipu.embed(texts[i : i + 16]))
        kb.set_embeddings(embeddings)
        return True
    except Exception as exc:
        print(f"[warn] embedding refresh skipped: {exc}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_api_key()
    kb.load()
    # try build embeddings if missing (best effort, keyword still works)
    if kb.chunks and not any(c.embedding for c in kb.chunks):
        await _refresh_embeddings()
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



@app.get("/v1/xmov/config")
async def xmov_config():
    """Return browser SDK config only after an explicit secret-exposure opt-in."""
    configured = bool(XMOV_APP_ID and XMOV_APP_SECRET and XMOV_SESSION_GATEWAY_URL)
    enabled = XMOV_BROWSER_CONFIG_ENABLED and configured
    result = {
        "enabled": enabled,
        "configured": configured,
        "requires_browser_secret_opt_in": configured and not XMOV_BROWSER_CONFIG_ENABLED,
    }
    if enabled:
        result.update(
            {
                "app_id": XMOV_APP_ID,
                "app_secret": XMOV_APP_SECRET,
                "gateway_server": XMOV_SESSION_GATEWAY_URL,
                "auth_header": XMOV_AUTH_HEADER,
                "sdk_url": XMOV_SDK_URL,
            }
        )
    return result


async def _livetalking_post(path: str, payload: dict, timeout: float = 10.0) -> dict:
    if not LIVETALKING_ENABLED:
        raise HTTPException(503, "LiveTalking is disabled")
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(f"{LIVETALKING_URL}{path}", json=payload)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"LiveTalking unavailable: {exc}") from exc
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise HTTPException(502, data.get("msg") or "LiveTalking request failed")
    return data


@app.get("/v1/livetalking/status")
async def livetalking_status():
    avatar_id = _avatar_settings()["avatar_id"]
    if not LIVETALKING_ENABLED:
        return {"enabled": False, "ready": False}
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(f"{LIVETALKING_URL}/api/admin/config")
        response.raise_for_status()
        return {
            "enabled": True,
            "ready": True,
            "avatar_id": avatar_id,
        }
    except httpx.HTTPError as exc:
        return {
            "enabled": True,
            "ready": False,
            "avatar_id": avatar_id,
            "detail": str(exc),
        }


@app.post("/v1/livetalking/offer")
async def livetalking_offer(req: LiveTalkingOfferRequest):
    payload = req.model_dump(exclude_none=True)
    payload["avatar"] = payload.get("avatar") or _avatar_settings()["avatar_id"]
    return await _livetalking_post("/offer", payload, timeout=20.0)


@app.post("/v1/livetalking/speak")
async def livetalking_speak(req: LiveTalkingSpeakRequest):
    if req.interrupt:
        await _livetalking_post(
            "/interrupt_talk",
            {"sessionid": req.session_id},
        )

    uploaded_audio = False
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            async for event in zhipu.tts_stream(
                req.text.strip(),
                voice=_avatar_settings()["voice"],
                speed=1.0,
            ):
                choices = event.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                encoded = delta.get("content")
                if not encoded:
                    continue

                wav_file = io.BytesIO()
                with wave.open(wav_file, "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(int(delta.get("return_sample_rate") or 24000))
                    output.writeframes(base64.b64decode(encoded))

                response = await client.post(
                    f"{LIVETALKING_URL}/humanaudio",
                    data={"sessionid": req.session_id},
                    files={"file": ("speech.wav", wav_file.getvalue(), "audio/wav")},
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and data.get("code") not in (None, 0):
                    raise RuntimeError(data.get("msg") or "LiveTalking audio upload failed")
                uploaded_audio = True
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, f"LiveTalking streaming TTS failed: {exc}") from exc

    if not uploaded_audio:
        raise HTTPException(502, "GLM-TTS returned no PCM audio")
    return {"code": 0, "msg": "ok"}


@app.post("/v1/livetalking/interrupt")
async def livetalking_interrupt(req: LiveTalkingSessionRequest):
    return await _livetalking_post(
        "/interrupt_talk",
        {"sessionid": req.session_id},
    )


@app.post("/v1/livetalking/is-speaking")
async def livetalking_is_speaking(req: LiveTalkingSessionRequest):
    return await _livetalking_post(
        "/is_speaking",
        {"sessionid": req.session_id},
    )


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
    embedded = await _refresh_embeddings()
    return {"ok": True, "chunks": n, "embedded": embedded}


def _knowledge_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for directory, category, editable in (
        (DOCS_DIR, "官方资料", False),
        (UPLOADS_DIR, "管理员上传", True),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".docx", ".txt", ".md"}:
                continue
            stat = path.stat()
            documents.append(
                {
                    "name": path.name,
                    "category": category,
                    "editable": editable,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
    return documents


@app.get("/v1/admin/kb/documents")
async def admin_kb_documents():
    return {"documents": _knowledge_documents(), "chunk_count": len(kb.chunks)}


@app.post("/v1/admin/kb/documents")
async def admin_kb_upload(file: UploadFile = File(...)):
    filename = Path(file.filename or "").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(400, "文件名无效")
    if Path(filename).suffix.lower() not in {".docx", ".txt", ".md"}:
        raise HTTPException(400, "仅支持 DOCX、TXT、Markdown 知识文档")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件为空")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 10MB")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOADS_DIR / filename
    destination.write_bytes(raw)
    try:
        chunks = kb.rebuild_from_docs()
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        destination.unlink(missing_ok=True)
        kb.rebuild_from_docs()
        raise HTTPException(400, f"知识文档解析失败：{exc}") from exc
    embedded = await _refresh_embeddings()
    return {
        "ok": True,
        "name": filename,
        "chunks": chunks,
        "embedded": embedded,
        "message": "知识库已更新",
    }


@app.delete("/v1/admin/kb/documents/{filename}")
async def admin_kb_delete(filename: str):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(400, "文件名无效")
    target = UPLOADS_DIR / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "只能删除管理员上传的文档")
    target.unlink()
    chunks = kb.rebuild_from_docs()
    embedded = await _refresh_embeddings()
    return {"ok": True, "chunks": chunks, "embedded": embedded}


@app.get("/v1/admin/avatar")
async def admin_avatar_get():
    return {
        "settings": _avatar_settings(),
        "available_avatars": _available_avatars(),
        "available_voices": ["female", "male", "tongtong", "chuichui"],
    }


@app.put("/v1/admin/avatar")
async def admin_avatar_update(req: AvatarSettingsRequest):
    available = _available_avatars()
    if req.avatar_id not in available:
        raise HTTPException(400, f"数字人形象不存在：{req.avatar_id}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _db()
    conn.execute(
        """
        INSERT INTO avatar_settings
            (id, display_name, avatar_id, voice, costume, expression, updated_at)
        VALUES (1,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            display_name=excluded.display_name,
            avatar_id=excluded.avatar_id,
            voice=excluded.voice,
            costume=excluded.costume,
            expression=excluded.expression,
            updated_at=excluded.updated_at
        """,
        (
            req.display_name.strip(),
            req.avatar_id,
            req.voice,
            req.costume,
            req.expression,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "settings": _avatar_settings()}


@app.post("/v1/feedback")
async def feedback(req: FeedbackRequest):
    sentiment = _infer_sentiment(req.comment, req.rating)
    conn = _db()
    conn.execute(
        "INSERT INTO feedback VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            req.session_id or "anonymous",
            req.rating,
            req.comment.strip(),
            sentiment,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "sentiment": sentiment, "message": "感谢您的反馈"}


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
        audio = await zhipu.tts(
            speak,
            voice=req.voice or _avatar_settings()["voice"],
            speed=req.speed,
        )
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
                voice=req.voice or _avatar_settings()["voice"],
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
    user_rows = conn.execute(
        "SELECT session_id, content, meta, created_at FROM chat_logs "
        "WHERE role='user' ORDER BY created_at DESC"
    ).fetchall()
    assistant_rows = conn.execute(
        "SELECT meta FROM chat_logs WHERE role='assistant' ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    feedback_rows = conn.execute(
        "SELECT rating, comment, sentiment, created_at FROM feedback "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_start = (now.date() - timedelta(days=6)).isoformat()
    recent_questions = [row[1] for row in user_rows[:200]]
    today_sessions = {row[0] for row in user_rows if row[3][:10] == today}
    week_sessions = {row[0] for row in user_rows if row[3][:10] >= week_start}

    hot = ["灵山大佛", "梵宫", "九龙灌浴", "祥符禅寺", "路线", "五印坛城"]
    counts = {key: sum(1 for question in recent_questions if key in question) for key in hot}

    daily = []
    for offset in range(6, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        day_rows = [row for row in user_rows if row[3][:10] == day]
        daily.append(
            {
                "date": day,
                "turns": len(day_rows),
                "visitors": len({row[0] for row in day_rows}),
            }
        )

    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for _, content, meta_text, _ in user_rows[:500]:
        try:
            sentiment = json.loads(meta_text or "{}").get("sentiment")
        except json.JSONDecodeError:
            sentiment = None
        sentiment = sentiment or _infer_sentiment(content)
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
    for _, _, sentiment, _ in feedback_rows:
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

    ratings = [row[0] for row in feedback_rows]
    satisfaction_trend = []
    for offset in range(6, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        values = [row[0] for row in feedback_rows if row[3][:10] == day]
        satisfaction_trend.append(
            {
                "date": day,
                "score": round(sum(values) / len(values), 2) if values else None,
                "count": len(values),
            }
        )

    latencies = []
    for (meta_text,) in assistant_rows:
        try:
            latency = json.loads(meta_text or "{}").get("latency_ms")
        except json.JSONDecodeError:
            latency = None
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))

    suggestions = []
    if sentiment_counts.get("negative", 0) > sentiment_counts.get("positive", 0):
        suggestions.append("负向反馈偏多，建议复核高频问题回答与现场排队体验。")
    if counts.get("路线", 0) > 0:
        suggestions.append("路线咨询活跃，可在入口增加分众路线二维码和预计时长提示。")
    if counts.get("九龙灌浴", 0) > 0:
        suggestions.append("九龙灌浴关注度较高，建议突出表演时刻和最佳观看位置。")
    if not suggestions:
        suggestions.append("当前服务运行平稳，建议持续扩充高频问题知识库并收集满意度。")

    return {
        "service_turns": len(user_rows),
        "unique_visitors": len({row[0] for row in user_rows}),
        "today_visitors": len(today_sessions),
        "week_visitors": len(week_sessions),
        "avg_satisfaction": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "feedback_count": len(feedback_rows),
        "avg_response_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "hot_topics": sorted(
            [{"name": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "sentiment": sentiment_counts,
        "daily_service": daily,
        "satisfaction_trend": satisfaction_trend,
        "recent_questions": recent_questions[:10],
        "recent_feedback": [
            {
                "rating": row[0],
                "comment": row[1],
                "sentiment": row[2],
                "created_at": row[3],
            }
            for row in feedback_rows[:10]
        ],
        "service_suggestions": suggestions,
        "routes": ROUTES,
    }


@app.get("/admin")
@app.get("/admin/")
async def admin_index():
    admin_path = STATIC_DIR / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    raise HTTPException(404, "管理后台页面尚未生成")


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
