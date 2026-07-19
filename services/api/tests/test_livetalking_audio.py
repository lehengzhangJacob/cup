from __future__ import annotations

import base64
import unittest
import wave
from io import BytesIO
from unittest.mock import AsyncMock, patch

from app import main


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, int]:
        return {"code": 0}


class _Client:
    posts: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url, *, data=None, files=None):
        self.posts.append({"url": url, "data": data, "files": files})
        return _Response()


class LiveTalkingAudioTests(unittest.IsolatedAsyncioTestCase):
    def test_route_arrows_are_spoken_as_navigation_transitions(self):
        spoken = main._speech_text(
            "南门入园→佛手广场（天下第一掌） → 灵山大佛。\n"
            '{"emotion":"smile"}'
        )

        self.assertEqual(
            spoken,
            "南门入园，接着前往佛手广场（天下第一掌），接着前往灵山大佛。",
        )

    async def test_heartbeat_is_forwarded_to_livetalking(self):
        forwarded = AsyncMock(return_value={"code": 0, "msg": "ok"})
        with patch.object(main, "_livetalking_post", new=forwarded):
            result = await main.livetalking_heartbeat(
                main.LiveTalkingSessionRequest(session_id="session-1")
            )

        self.assertEqual(result, {"code": 0, "msg": "ok"})
        forwarded.assert_awaited_once_with(
            "/heartbeat",
            {"sessionid": "session-1"},
        )

    async def test_combines_provider_chunks_before_one_livetalking_upload(self):
        first = b"\x01\x00" * 240
        second = b"\x02\x00" * 360
        tts_arguments: dict = {}

        async def tts_stream(text, *, voice, speed):
            tts_arguments.update(text=text, voice=voice, speed=speed)
            for pcm in (first, second):
                yield {
                    "choices": [
                        {
                            "delta": {
                                "content": base64.b64encode(pcm).decode("ascii"),
                                "return_sample_rate": 24000,
                            }
                        }
                    ]
                }

        _Client.posts = []
        with (
            patch.object(main.zhipu, "tts_stream", new=tts_stream),
            patch.object(main.httpx, "AsyncClient", new=_Client),
            patch.object(main, "_mark_livetalking_used"),
        ):
            await main._stream_tts_to_livetalking(
                "session-1",
                "请连续自然地播报这句话。",
                interrupt=False,
            )

        self.assertEqual(tts_arguments["speed"], 1.0)
        self.assertEqual(len(_Client.posts), 1)
        uploaded_wav = _Client.posts[0]["files"]["file"][1]
        with wave.open(BytesIO(uploaded_wav), "rb") as audio:
            self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(audio.readframes(audio.getnframes()), first + second)


if __name__ == "__main__":
    unittest.main()
