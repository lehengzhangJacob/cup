from __future__ import annotations

import base64
import unittest
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

    async def post(
        self,
        url,
        *,
        data=None,
        files=None,
        params=None,
        content=None,
        headers=None,
    ):
        self.posts.append(
            {
                "url": url,
                "data": data,
                "files": files,
                "params": params,
                "content": content,
                "headers": headers,
            }
        )
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

    def test_clock_times_are_spoken_naturally(self):
        spoken = main._speech_text(
            "开放时间为09:00—19:00，建议19：30前入园，最晚19:05到达。"
        )

        self.assertEqual(
            spoken,
            "开放时间为九点到十九点，建议十九点半前入园，最晚十九点零五分到达。",
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

    async def test_streams_provider_chunks_into_one_continuous_pcm_segment(self):
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
        self.assertEqual(len(_Client.posts), 3)
        self.assertEqual(_Client.posts[0]["content"], first)
        self.assertEqual(_Client.posts[1]["content"], second)
        self.assertEqual(_Client.posts[2]["content"], b"")
        self.assertEqual(_Client.posts[0]["params"]["final"], "false")
        self.assertEqual(_Client.posts[1]["params"]["sample_rate"], 24000)
        self.assertEqual(_Client.posts[2]["params"]["final"], "true")
        self.assertTrue(all(post["url"].endswith("/humanpcm") for post in _Client.posts))

    async def test_keeps_semantic_segments_in_one_answer_level_pcm_stream(self):
        first = b"\x01\x00" * 240
        second = b"\x02\x00" * 360

        async def tts_stream(text, *, voice, speed):
            pcm = first if text == "第一句，" else second
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

        forwarded = AsyncMock(return_value={"code": 0, "msg": "ok"})
        _Client.posts = []
        with (
            patch.object(main.zhipu, "tts_stream", new=tts_stream),
            patch.object(main.httpx, "AsyncClient", new=_Client),
            patch.object(main, "_livetalking_post", new=forwarded),
            patch.object(main, "_mark_livetalking_used"),
        ):
            queue = main._start_livetalking_speech_worker("answer-session")
            worker = main._livetalking_speech_workers["answer-session"]
            queue.put_nowait("第一句，")
            queue.put_nowait("第二句。")
            queue.put_nowait(None)
            await worker

        forwarded.assert_awaited_once_with(
            "/interrupt_talk",
            {"sessionid": "answer-session"},
        )
        self.assertEqual(len(_Client.posts), 3)
        self.assertEqual(_Client.posts[0]["content"], first)
        self.assertEqual(_Client.posts[1]["content"], second)
        self.assertEqual(_Client.posts[2]["content"], b"")
        self.assertEqual(_Client.posts[0]["params"]["final"], "false")
        self.assertEqual(_Client.posts[1]["params"]["final"], "false")
        self.assertEqual(_Client.posts[2]["params"]["final"], "true")


if __name__ == "__main__":
    unittest.main()
