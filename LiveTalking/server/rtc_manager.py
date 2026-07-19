###############################################################################
#  WebRTC 连接管理 + RTC 音频/视频接收
###############################################################################

import json
import asyncio
import random
import copy
from typing import Dict, Optional
import queue

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration
from aiortc.rtcrtpsender import RTCRtpSender

from utils.logger import logger


# def _rand_session_id(n: int = 6) -> int:
#     """生成 N 位随机 session ID"""
#     return random.randint(10 ** (n - 1), 10 ** n - 1)


from server.session_manager import session_manager
from server.session_manager import MaxSessionError

class RTCManager:
    """
    WebRTC 连接管理器。
    
    管理 PeerConnection 生命周期、音视频轨道收发、DataChannel。
    """

    def __init__(self, opt):
        """
        Args:
            opt: 全局配置
        """
        self.opt = opt
        self.pcs: set = set()
        self.session_pcs: Dict[str, RTCPeerConnection] = {}

    def _ice_servers(self, params) -> list[RTCIceServer]:
        servers: list[RTCIceServer] = []
        raw_servers = params.get("ice_servers") or []
        if isinstance(raw_servers, list):
            for raw_server in raw_servers[:8]:
                if not isinstance(raw_server, dict):
                    continue
                raw_urls = raw_server.get("urls")
                if isinstance(raw_urls, str):
                    urls = raw_urls
                elif isinstance(raw_urls, list):
                    urls = [url for url in raw_urls if isinstance(url, str)][:16]
                    if not urls:
                        continue
                else:
                    continue
                credential_type = raw_server.get("credentialType", "password")
                if credential_type not in {"password", "oauth"}:
                    credential_type = "password"
                servers.append(
                    RTCIceServer(
                        urls=urls,
                        username=raw_server.get("username"),
                        credential=raw_server.get("credential"),
                        credentialType=credential_type,
                    )
                )
        if not servers and self.opt.stun:
            servers.append(RTCIceServer(urls=self.opt.stun))
        return servers

    async def _close_session(self, sessionid: str):
        """Close the peer connection and always release its session slot."""
        pc = self.session_pcs.pop(sessionid, None)
        if pc is not None:
            self.pcs.discard(pc)
            if pc.connectionState != "closed":
                await pc.close()
        session_manager.remove_session(sessionid)

    async def handle_close_session(self, request):
        """Explicit cleanup used when a browser offer fails or the page exits."""
        params = await request.json()
        sessionid = str(params.get("sessionid") or "").strip()
        if not sessionid:
            return web.json_response({"code": -1, "msg": "sessionid is required"})
        await self._close_session(sessionid)
        return web.json_response({"code": 0, "msg": "ok"})

    async def handle_offer(self, request):
        """处理 WebRTC offer 信令"""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        # 通过 SessionManager 构建（内部会检查 max_session）
        try:
            sessionid = await session_manager.create_session(params)
        except MaxSessionError as e:
            logger.warning("Rejecting offer: %s", e)
            return web.Response(
                content_type="application/json",
                text=json.dumps({"code": -1, "msg": str(e)}),
            )
        logger.info('offer sessionid=%s', sessionid)
        avatar_session = session_manager.get_session(sessionid)

        # 浏览器和服务端必须使用同一组公网 TURN 凭据，才能在双 NAT 下建立媒体链路。
        ice_servers = self._ice_servers(params)
        logger.info("Using %d ICE server entries", len(ice_servers))
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=ice_servers)
        )
        self.pcs.add(pc)
        self.session_pcs[sessionid] = pc

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self._close_session(sessionid)
            elif pc.connectionState == "disconnected":
                async def close_if_still_disconnected():
                    await asyncio.sleep(8)
                    if pc.connectionState == "disconnected":
                        logger.info("Closing disconnected session %s", sessionid)
                        await self._close_session(sessionid)

                asyncio.create_task(close_if_still_disconnected())

        async def connection_watchdog():
            await asyncio.sleep(15)
            if pc.connectionState not in ("connected", "closed"):
                logger.warning(
                    "Closing stale WebRTC session %s in state %s",
                    sessionid,
                    pc.connectionState,
                )
                await self._close_session(sessionid)

        asyncio.create_task(connection_watchdog())

        # 添加发送轨道
        from server.webrtc import HumanPlayer
        player = HumanPlayer(avatar_session)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        # 设置编解码器偏好
        capabilities = RTCRtpSender.getCapabilities("video")
        preferences = list(filter(lambda x: x.name == "H264", capabilities.codecs))
        preferences += list(filter(lambda x: x.name == "VP8", capabilities.codecs))
        preferences += list(filter(lambda x: x.name == "rtx", capabilities.codecs))
        transceiver = pc.getTransceivers()[1]
        transceiver.setCodecPreferences(preferences)

        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
                "sessionid": sessionid,
            }),
        )

    async def handle_rtcpush(self, push_url, sessionid: str):
        """RTCPush 模式：主动推流"""
        import aiohttp
        await session_manager.create_session({}, sessionid)
        avatar_session = session_manager.get_session(sessionid)

        pc = RTCPeerConnection()
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", pc.connectionState)
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        from server.webrtc import HumanPlayer
        player = HumanPlayer(avatar_session)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        await pc.setLocalDescription(await pc.createOffer())

        async with aiohttp.ClientSession() as session:
            async with session.post(push_url, data=pc.localDescription.sdp) as response:
                answer_sdp = await response.text()

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type='answer')
        )

    async def shutdown(self):
        """关闭所有 PeerConnection"""
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()
        self.session_pcs.clear()
