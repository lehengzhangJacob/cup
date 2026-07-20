from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import ChatRequest, generation_error_message


def test_full_local_oom_recommends_lightweight_route():
    message = generation_error_message(
        RuntimeError("torch.OutOfMemoryError: CUDA out of memory"),
        "local",
    )

    assert "CUDA 显存不足（OOM）" in message
    assert "轻量本地 Qwen3-1.7B" in message


def test_gpu_selection_failure_reports_required_memory():
    message = generation_error_message(
        RuntimeError("No candidate GPU has at least 18000 MiB free"),
        "local",
    )

    assert "无法启动" in message
    assert "18000 MiB" in message


def test_chat_request_accepts_lightweight_route():
    request = ChatRequest(message="介绍灵山大佛", model_route="local_lite")

    assert request.model_route == "local_lite"
