from __future__ import annotations

import json
import unittest

import httpx

from app.deepseek import DeepSeekClient


class DeepSeekClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_streaming_chat_disables_thinking(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "deepseek-v4-flash")
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "导览回答"}}]},
            )

        client = DeepSeekClient(
            api_key="test-key",
            base="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        answer = await client.chat([{"role": "user", "content": "你好"}])

        self.assertEqual(answer, "导览回答")

    async def test_streaming_chat_ignores_reasoning_content(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            body = "\n".join(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"内部推理"}}]}',
                    'data: {"choices":[{"delta":{"content":"灵山"}}]}',
                    'data: {"choices":[{"delta":{"content":"欢迎您"}}]}',
                    "data: [DONE]",
                    "",
                ]
            )
            return httpx.Response(200, text=body)

        client = DeepSeekClient(
            api_key="test-key",
            base="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        tokens = [
            token
            async for token in client.chat_stream(
                [{"role": "user", "content": "你好"}]
            )
        ]

        self.assertEqual(tokens, ["灵山", "欢迎您"])
