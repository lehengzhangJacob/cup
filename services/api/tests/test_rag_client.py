from __future__ import annotations

import json
import unittest

import httpx

from app.rag_client import RAGClient, RAGClientError


class RAGClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_streaming_chat_forwards_session_and_context(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.assertEqual(payload["session_id"], "session-1")
            self.assertEqual(payload["interest"], "历史")
            self.assertEqual(payload["spot_id"], "灵山大佛")
            self.assertEqual(payload["model_route"], "local")
            self.assertFalse(payload["stream"])
            return httpx.Response(
                200,
                json={
                    "session_id": "session-1",
                    "answer": "回答",
                    "citations": [],
                },
            )

        client = RAGClient(
            base_url="http://rag.test",
            transport=httpx.MockTransport(handler),
        )
        result = await client.chat(
            "问题",
            session_id="session-1",
            interest="历史",
            spot_id="灵山大佛",
            model_route="local",
        )
        self.assertEqual(result["answer"], "回答")

    async def test_streaming_chat_parses_sse(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            body = "\n".join(
                [
                    'data: {"type":"meta","citations":[]}',
                    "",
                    'data: {"type":"delta","content":"灵山"}',
                    "",
                    'data: {"type":"done","latency_ms":10}',
                    "",
                ]
            )
            return httpx.Response(200, text=body)

        client = RAGClient(
            base_url="http://rag.test",
            transport=httpx.MockTransport(handler),
        )
        events = [
            event
            async for event in client.chat_stream("问题", session_id="session-1")
        ]
        self.assertEqual([event["type"] for event in events], ["meta", "delta", "done"])

    async def test_stream_error_event_raises(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text='data: {"type":"error","message":"boom"}\n\n',
            )

        client = RAGClient(
            base_url="http://rag.test",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(RAGClientError, "boom"):
            async for _ in client.chat_stream("问题", session_id="session-1"):
                pass
