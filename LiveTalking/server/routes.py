###############################################################################
#  服务器路由 — 统一异常处理的 API 路由
###############################################################################

import json
import asyncio
from threading import Event, Thread
from typing import Dict

from aiohttp import web

from utils.logger import logger


# ─── 路由工具函数 ──────────────────────────────────────────────────────────

def json_ok(data=None):
    """返回成功 JSON 响应"""
    body = {"code": 0, "msg": "ok"}
    if data is not None:
        body["data"] = data
    return web.Response(
        content_type="application/json",
        text=json.dumps(body),
    )


def json_error(msg: str, code: int = -1):
    """返回错误 JSON 响应"""
    return web.Response(
        content_type="application/json",
        text=json.dumps({"code": code, "msg": str(msg)}),
    )


from server.session_manager import MaxSessionError, session_manager
from server.avatar_routes import setup_avatar_routes

_http_render_quit: Dict[str, Event] = {}
_http_stream_clients: Dict[str, int] = {}
_http_cleanup_tasks: Dict[str, asyncio.Task] = {}
_HTTP_DISCONNECT_GRACE_SECONDS = 30


async def _release_http_session_after_grace(sessionid: str) -> None:
    """Keep the renderer alive briefly so an MJPEG client can reconnect."""
    try:
        await asyncio.sleep(_HTTP_DISCONNECT_GRACE_SECONDS)
        if _http_stream_clients.get(sessionid, 0) == 0:
            _http_cleanup_tasks.pop(sessionid, None)
            _release_http_session(sessionid)
    except asyncio.CancelledError:
        pass

def get_session(request, sessionid: str):
    """从 app 中获取 session 实例"""
    return session_manager.get_session(sessionid)


# ─── 路由处理函数 ──────────────────────────────────────────────────────────

async def human(request):
    """文本输入（echo/chat 模式），支持 voice/emotion 参数"""
    try:
        params: dict = await request.json()

        sessionid: str = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")

        if params.get('interrupt'):
            avatar_session.flush_talk()

        datainfo = {}
        if params.get('tts'):  # tts 参数透传（voice, emotion 等）
            datainfo['tts'] = params.get('tts')

        if params['type'] == 'echo':
            avatar_session.put_msg_txt(params['text'], datainfo)
        elif params['type'] == 'chat':
            llm_response = request.app.get("llm_response")
            if llm_response:
                asyncio.get_event_loop().run_in_executor(
                    None, llm_response, params['text'], avatar_session, datainfo
                )

        return json_ok()
    except Exception as e:
        logger.exception('human route exception:')
        return json_error(str(e))


async def interrupt_talk(request):
    """打断当前说话"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.flush_talk()
        return json_ok()
    except Exception as e:
        logger.exception('interrupt_talk exception:')
        return json_error(str(e))


async def humanaudio(request):
    """上传音频文件"""
    try:
        form = await request.post()
        sessionid = str(form.get('sessionid', ''))
        fileobj = form["file"]
        filebytes = fileobj.file.read()

        datainfo = {}

        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.put_audio_file(filebytes, datainfo)
        return json_ok()
    except Exception as e:
        logger.exception('humanaudio exception:')
        return json_error(str(e))


async def set_audiotype(request):
    """设置自定义状态（动作编排）"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.set_custom_state(params['audiotype'])
        return json_ok()
    except Exception as e:
        logger.exception('set_audiotype exception:')
        return json_error(str(e))


async def record(request):
    """录制控制"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        if params['type'] == 'start_record':
            avatar_session.start_recording()
        elif params['type'] == 'end_record':
            avatar_session.stop_recording()
        return json_ok()
    except Exception as e:
        logger.exception('record exception:')
        return json_error(str(e))


async def is_speaking(request):
    """查询是否正在说话"""
    params = await request.json()
    sessionid = params.get('sessionid', '')
    avatar_session = get_session(request, sessionid)
    if avatar_session is None:
        return json_error("session not found")
    return json_ok(data=avatar_session.is_speaking())


async def admin_config(request):
    """Admin: 获取全局配置参数"""
    try:
        opt = request.app.get("opt")
        if opt:
            return json_ok(data={"config": vars(opt)})
        return json_error("Config not found")
    except Exception as e:
        logger.exception('admin_config exception:')
        return json_error(str(e))


async def admin_sessions(request):
    """Admin: 获取活跃的会话及其配置"""
    try:
        sessions_info = []
        for sid, avatar_session in session_manager.sessions.items():
            if avatar_session:
                s_opt = getattr(avatar_session, 'opt', None)
                s_data = {
                    "sessionid": sid,
                    "speaking": avatar_session.is_speaking() if hasattr(avatar_session, 'is_speaking') else False,
                    "recording": getattr(avatar_session, 'recording', False),
                }
                if s_opt:
                    s_data.update({
                        "model": getattr(s_opt, "model", ""),
                        "avatar_id": getattr(s_opt, "avatar_id", ""),
                        "REF_FILE": getattr(s_opt, "REF_FILE", ""),
                        "transport": getattr(s_opt, "transport", ""),
                        "batch_size": getattr(s_opt, "batch_size", 0),
                        "customopt": getattr(s_opt, "customopt", []),
                    })
                sessions_info.append(s_data)
        return json_ok(data={"sessions": sessions_info})
    except Exception as e:
        logger.exception('admin_sessions exception:')
        return json_error(str(e))


async def create_http_session(request):
    """创建同源 HTTP/MJPEG 会话，避免公网 WebRTC/TURN 依赖。"""
    try:
        try:
            params = await request.json()
        except Exception:
            params = {}
        if not isinstance(params, dict):
            params = {}
        sessionid = await session_manager.create_session(params)
        avatar = session_manager.get_session(sessionid)
        if avatar is None:
            return json_error("failed to create session")
        quit_event = Event()
        _http_render_quit[sessionid] = quit_event
        Thread(
            target=avatar.render,
            args=(quit_event,),
            daemon=True,
            name=f"http-render-{sessionid[:8]}",
        ).start()
        logger.info("HTTP session ready sessionid=%s", sessionid)
        return web.json_response({"code": 0, "msg": "ok", "sessionid": sessionid})
    except MaxSessionError as exc:
        return json_error(str(exc))
    except Exception as exc:
        logger.exception("create_http_session exception:")
        return json_error(str(exc))


def _release_http_session(sessionid: str) -> None:
    cleanup_task = _http_cleanup_tasks.pop(sessionid, None)
    if cleanup_task is not None:
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if cleanup_task is not current_task:
            cleanup_task.cancel()
    _http_stream_clients.pop(sessionid, None)
    quit_event = _http_render_quit.pop(sessionid, None)
    if quit_event:
        quit_event.set()
    session_manager.remove_session(sessionid)


async def close_http_session(request):
    try:
        params = await request.json()
        _release_http_session(str(params.get("sessionid", "")))
        return json_ok()
    except Exception as exc:
        logger.exception("close_http_session exception:")
        return json_error(str(exc))


async def frame_jpeg(request):
    sessionid = request.query.get("sessionid", "")
    avatar = session_manager.get_session(sessionid)
    if avatar is None or not hasattr(avatar, "output"):
        return web.Response(status=404, text="session not found")
    getter = getattr(avatar.output, "get_latest_jpeg", None)
    jpeg = getter() if callable(getter) else None
    if not jpeg:
        return web.Response(status=503, text="no frame yet")
    return web.Response(
        body=jpeg,
        content_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


async def mjpeg_stream(request):
    sessionid = request.query.get("sessionid", "")
    cleanup_task = _http_cleanup_tasks.pop(sessionid, None)
    if cleanup_task is not None:
        cleanup_task.cancel()
    avatar = session_manager.get_session(sessionid)
    if avatar is None or not hasattr(avatar, "output"):
        return web.Response(status=404, text="session not found")

    _http_stream_clients[sessionid] = _http_stream_clients.get(sessionid, 0) + 1

    response = web.StreamResponse(
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache, no-store, no-transform, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
    last_jpeg = None
    try:
        await response.prepare(request)
        while request.transport and not request.transport.is_closing():
            getter = getattr(avatar.output, "get_latest_jpeg", None)
            jpeg = getter() if callable(getter) else None
            if jpeg and jpeg != last_jpeg:
                last_jpeg = jpeg
                await response.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
            await asyncio.sleep(0.04)
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as exc:
        logger.warning("MJPEG stream ended: %s", exc)
    finally:
        remaining = max(0, _http_stream_clients.get(sessionid, 1) - 1)
        if remaining:
            _http_stream_clients[sessionid] = remaining
        else:
            _http_stream_clients.pop(sessionid, None)
            previous_task = _http_cleanup_tasks.pop(sessionid, None)
            if previous_task is not None:
                previous_task.cancel()
            if session_manager.get_session(sessionid) is not None:
                _http_cleanup_tasks[sessionid] = asyncio.create_task(
                    _release_http_session_after_grace(sessionid)
                )
    return response


# ─── 路由注册 ──────────────────────────────────────────────────────────────

def setup_routes(app):
    """注册所有路由到 aiohttp app"""
    # aiohttp's static resource returns 403 for a directory request when
    # directory listing is disabled. Serve the UI explicitly at the root so
    # opening http://<host>:8010 works without requiring /index.html.
    app.router.add_get("/", lambda request: web.FileResponse("web/index.html"))
    app.router.add_post("/human", human)
    app.router.add_post("/humanaudio", humanaudio)
    app.router.add_post("/set_audiotype", set_audiotype)
    app.router.add_post("/record", record)
    app.router.add_post("/interrupt_talk", interrupt_talk)
    app.router.add_post("/is_speaking", is_speaking)
    app.router.add_post("/session", create_http_session)
    app.router.add_post("/session/close", close_http_session)
    app.router.add_get("/mjpeg", mjpeg_stream)
    app.router.add_get("/frame.jpg", frame_jpeg)
    app.router.add_get("/api/admin/config", admin_config)
    app.router.add_get("/api/admin/sessions", admin_sessions)

    # ── Local ASR endpoint (SenseVoice/FunASR) ── Issue #604 ──
    try:
        from server.asr_server import asr_websocket_handler, is_funasr_available
        if is_funasr_available():
            app.router.add_get("/api/asr", asr_websocket_handler)
            logger.info("[ASR] Local SenseVoice ASR endpoint enabled at /api/asr")
        else:
            logger.info("[ASR] funasr not installed — local ASR endpoint disabled "
                        "(pip install funasr modelscope)")
    except Exception as e:
        logger.warning(f"[ASR] Failed to register ASR endpoint: {e}")

    # 注册 avatar 生成相关的路由
    setup_avatar_routes(app)

    app.router.add_static('/', path='web')
