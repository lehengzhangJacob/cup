import json
import os

import numpy as np

import rag.embedder as embedder_module
from rag.embedder import Embedder


class FakeModel:
    device = "cpu"

    def encode(self, texts, **_kwargs):
        return np.ones((len(texts), 3), dtype=np.float32)


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.closed = False

    def send(self, request):
        self.request = request

    def poll(self, _timeout):
        return True

    def recv(self):
        return self.response

    def close(self):
        self.closed = True


def test_local_embedder_uses_supplied_model():
    embedder = Embedder(model=FakeModel())

    vectors = embedder.encode_batch(["one", "two"])

    assert vectors.shape == (2, 3)
    assert embedder.status()["mode"] == "local"


def test_on_demand_embedder_calls_coordinator(monkeypatch):
    connection = FakeConnection(
        {"ok": True, "vectors": np.ones((1, 4), dtype=np.float32)}
    )
    monkeypatch.setattr(embedder_module, "EMBED_DEVICE", "on-demand")
    monkeypatch.setattr(embedder_module, "Client", lambda *_args, **_kwargs: connection)
    embedder = Embedder()

    vector = embedder.encode_query("question")

    assert vector.shape == (4,)
    assert connection.request == {"command": "encode", "texts": ["question"]}
    assert connection.closed is True


def test_on_demand_status_checks_coordinator_pid(monkeypatch, tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text(
        json.dumps(
            {
                "ready": True,
                "mode": "cpu-standby",
                "device": "cpu",
                "gpu_index": None,
                "coordinator_pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(embedder_module, "EMBED_DEVICE", "on-demand")
    monkeypatch.setattr(embedder_module, "EMBED_STATUS_FILE", status_file)
    monkeypatch.setattr(
        embedder_module,
        "Client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )

    status = Embedder().status()

    assert status["ready"] is True
    assert status["mode"] == "cpu-standby"
