import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.pipeline import RAGPipeline


def _chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class FakeRetriever:
    def __init__(self):
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        return [
            {
                "text": "灵山大佛通高88米，佛体由青铜铸造。",
                "metadata": {
                    "source": "dataset",
                    "scenic_area": "灵山胜境",
                    "attraction_name": "灵山大佛",
                    "section": "建筑参数",
                },
                "score": 0.92,
            }
        ]

    def stats(self):
        return {"chunk_count": 1, "embedding_dimension": 1024, "sources": ["dataset"]}


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["stream"]:
            return iter([_chunk("灵山大佛"), _chunk("通高88米。")])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="灵山大佛通高88米。"))]
        )


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)

    def close(self):
        pass


class AsyncChunks:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeAsyncCompletions(FakeCompletions):
    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["stream"]:
            return AsyncChunks([_chunk("灵山大佛"), _chunk("通高88米。")])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="灵山大佛通高88米。"))]
        )


class FakeAsyncClient:
    def __init__(self):
        self.completions = FakeAsyncCompletions()
        self.chat = SimpleNamespace(completions=self.completions)

    async def close(self):
        pass


def make_pipeline():
    retriever = FakeRetriever()
    client = FakeClient()
    async_client = FakeAsyncClient()
    return (
        RAGPipeline(
            retriever=retriever,
            client=client,
            async_client=async_client,
        ),
        retriever,
        client,
        async_client,
    )


def test_query_is_backward_compatible_and_returns_citations():
    pipeline, _, _, _ = make_pipeline()
    result = pipeline.query_result("灵山大佛多高？", session_id="s1")
    assert result.answer == "灵山大佛通高88米。"
    assert result.citations[0].title == "灵山大佛 · 建筑参数"
    assert result.citations[0].score == 0.92
    assert pipeline.query("灵山大佛多高？") == "灵山大佛通高88米。"


def test_warmup_only_runs_retrieval():
    pipeline, retriever, client, _ = make_pipeline()

    result = pipeline.warmup()

    assert result["ready"] is True
    assert retriever.queries == ["灵山胜境"]
    assert client.completions.calls == []


def test_follow_up_uses_history_for_retrieval_and_prompt():
    pipeline, retriever, client, _ = make_pipeline()
    pipeline.query("介绍一下灵山大佛", session_id="s1")
    result = pipeline.query_result("它多高？", session_id="s1")

    assert result.history_turns == 1
    assert "上一问题：介绍一下灵山大佛" in retriever.queries[-1]
    messages = client.completions.calls[-1]["messages"]
    assert any(m["role"] == "assistant" and "88米" in m["content"] for m in messages)


def test_sync_stream_emits_meta_deltas_done_and_commits_turn():
    pipeline, _, _, _ = make_pipeline()
    events = list(pipeline.stream("灵山大佛多高？", session_id="stream"))
    assert [event.type for event in events] == ["meta", "delta", "delta", "done"]
    assert "".join(event.content for event in events) == "灵山大佛通高88米。"
    assert len(pipeline.sessions.get("stream")) == 1


def test_async_stream_and_non_stream_share_session_memory():
    async def run():
        pipeline, retriever, _, _ = make_pipeline()
        first = await pipeline.aquery_result("介绍灵山大佛", session_id="async")
        events = [
            event
            async for event in pipeline.astream("它多高？", session_id="async")
        ]
        await pipeline.aclose()
        return first, events, retriever

    first, events, retriever = asyncio.run(run())
    assert first.answer
    assert events[0].history_turns == 1
    assert events[-1].type == "done"
    assert "上一问题：介绍灵山大佛" in retriever.queries[-1]


def test_local_route_uses_local_client_and_model():
    retriever = FakeRetriever()
    cloud_client = FakeClient()
    local_client = FakeClient()
    pipeline = RAGPipeline(
        retriever=retriever,
        client=cloud_client,
        local_client=local_client,
    )

    result = pipeline.query_result("灵山大佛多高？", model_route="local")

    assert result.answer == "灵山大佛通高88米。"
    assert cloud_client.completions.calls == []
    assert local_client.completions.calls[0]["model"].endswith("Qwen2-7B-Instruct")


def test_cloud_flash_uses_low_latency_default():
    pipeline, _, client, _ = make_pipeline()

    pipeline.query_result("灵山大佛多高？", model_route="cloud")

    assert client.completions.calls[0]["model"] == "glm-4-flash-250414"
    assert "extra_body" not in client.completions.calls[0]


def test_cloud_thinking_model_is_explicitly_disabled():
    assert RAGPipeline._completion_extras("cloud", "glm-4.5-flash") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
