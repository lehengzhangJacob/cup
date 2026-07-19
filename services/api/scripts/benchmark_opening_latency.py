"""Measure text-chat latency through the final LiveTalking audio frame."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError


LIVETALKING_URL = "http://127.0.0.1:8010"


async def wait_for_connection(peer: RTCPeerConnection, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if peer.connectionState == "connected":
            return
        if peer.connectionState in {"failed", "closed"}:
            raise RuntimeError(f"WebRTC connection {peer.connectionState}")
        await asyncio.sleep(0.05)
    raise TimeoutError(f"WebRTC connection timed out in state {peer.connectionState}")


async def open_livetalking_session(livetalking_url: str):
    peer = RTCPeerConnection()
    request_started = asyncio.Event()
    first_audio = asyncio.get_running_loop().create_future()
    request_start = [0.0]
    audio_metrics = {"last_audio_at": 0.0, "non_silent_frames": 0}
    audio_tasks: list[asyncio.Task[None]] = []

    async def consume_audio(track) -> None:
        try:
            while True:
                frame = await track.recv()
                if not request_started.is_set():
                    continue
                samples = frame.to_ndarray().astype(np.int32, copy=False)
                if samples.size and int(np.abs(samples).max()) >= 300:
                    now = time.perf_counter()
                    audio_metrics["last_audio_at"] = now
                    audio_metrics["non_silent_frames"] += 1
                    if not first_audio.done():
                        first_audio.set_result(now - request_start[0])
        except (MediaStreamError, asyncio.CancelledError):
            return

    @peer.on("track")
    def on_track(track) -> None:
        if track.kind == "audio":
            audio_tasks.append(asyncio.create_task(consume_audio(track)))

    peer.addTransceiver("video", direction="recvonly")
    peer.addTransceiver("audio", direction="recvonly")
    await peer.setLocalDescription(await peer.createOffer())

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        response = await client.post(
            f"{livetalking_url.rstrip('/')}/offer",
            json={
                "sdp": peer.localDescription.sdp,
                "type": peer.localDescription.type,
            },
        )
        response.raise_for_status()
        answer = response.json()
    if not answer.get("sdp") or not answer.get("sessionid"):
        await peer.close()
        raise RuntimeError(answer.get("msg") or "LiveTalking did not return a session")

    session_id = str(answer["sessionid"])
    await peer.setRemoteDescription(
        RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
    )
    await wait_for_connection(peer)
    return (
        peer,
        session_id,
        request_started,
        request_start,
        first_audio,
        audio_metrics,
        audio_tasks,
    )


async def wait_for_speech_completion(
    client: httpx.AsyncClient,
    base_url: str,
    session_id: str,
    request_start: float,
    audio_metrics: dict[str, float | int],
    *,
    timeout: float = 90.0,
    silence_seconds: float = 0.8,
) -> tuple[float, float, float]:
    deadline = time.monotonic() + timeout
    queue_done_at = 0.0
    while time.monotonic() < deadline:
        response = await client.post(
            f"{base_url.rstrip('/')}/v1/livetalking/is-speaking",
            json={"session_id": session_id},
        )
        response.raise_for_status()
        state = response.json()
        now = time.perf_counter()
        speaking = bool(state.get("data"))
        pending = bool(state.get("pending"))
        last_audio_at = float(audio_metrics["last_audio_at"])
        if not pending and not queue_done_at:
            queue_done_at = now
        if (
            last_audio_at
            and not pending
            and not speaking
            and now - last_audio_at >= silence_seconds
        ):
            return (
                last_audio_at - request_start,
                queue_done_at - request_start,
                now - request_start,
            )
        await asyncio.sleep(0.1)
    raise TimeoutError("LiveTalking speech completion timed out")


async def close_livetalking_session(
    peer: RTCPeerConnection,
    session_id: str,
    audio_tasks: list[asyncio.Task[None]],
    livetalking_url: str,
) -> None:
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        try:
            await client.post(
                f"{livetalking_url.rstrip('/')}/close_session",
                json={"sessionid": session_id},
            )
        except httpx.HTTPError:
            pass
    await peer.close()
    for task in audio_tasks:
        task.cancel()
    await asyncio.gather(*audio_tasks, return_exceptions=True)


async def benchmark(
    base_url: str,
    question: str,
    model_route: str,
    livetalking_url: str = LIVETALKING_URL,
) -> dict[str, float | str]:
    (
        peer,
        session_id,
        request_started,
        request_start,
        first_audio,
        audio_metrics,
        audio_tasks,
    ) = await open_livetalking_session(livetalking_url)
    first_token = None
    chat_done = None
    answer_parts: list[str] = []
    try:
        request_start[0] = time.perf_counter()
        request_started.set()
        async with httpx.AsyncClient(timeout=45.0, trust_env=False) as client:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/v1/chat",
                json={
                    "message": question,
                    "stream": True,
                    "model_route": model_route,
                    "livetalking_session_id": session_id,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    elapsed = time.perf_counter() - request_start[0]
                    if event.get("type") == "delta" and first_token is None:
                        first_token = elapsed
                    if event.get("type") == "delta":
                        answer_parts.append(str(event.get("content") or ""))
                    if event.get("type") == "done":
                        chat_done = elapsed
            first_audio_seconds = await asyncio.wait_for(first_audio, timeout=20.0)
            (
                completion_seconds,
                queue_done_seconds,
                completion_observed_seconds,
            ) = await wait_for_speech_completion(
                client,
                base_url,
                session_id,
                request_start[0],
                audio_metrics,
            )
        answer = "".join(answer_parts)
        return {
            "url": base_url,
            "model_route": model_route,
            "session_id": session_id,
            "first_token_ms": round((first_token or 0) * 1000),
            "chat_done_ms": round((chat_done or 0) * 1000),
            "first_audio_ms": round(first_audio_seconds * 1000),
            "speech_queue_done_ms": round(queue_done_seconds * 1000),
            "last_audio_ms": round(completion_seconds * 1000),
            "completion_observed_ms": round(completion_observed_seconds * 1000),
            "speech_duration_ms": round((completion_seconds - first_audio_seconds) * 1000),
            "answer_chars": len(answer),
            "non_silent_frames": int(audio_metrics["non_silent_frames"]),
        }
    finally:
        await close_livetalking_session(
            peer,
            session_id,
            audio_tasks,
            livetalking_url,
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "urls",
        nargs="*",
        default=["http://127.0.0.1:8001", "https://lingshanguide.de5.net"],
    )
    parser.add_argument("--question", default="灵山大佛有多高？")
    parser.add_argument("--model-route", choices=("cloud", "local"), default="cloud")
    parser.add_argument("--livetalking-url", default=LIVETALKING_URL)
    args = parser.parse_args()
    for url in args.urls:
        result = await benchmark(
            url,
            args.question,
            args.model_route,
            args.livetalking_url,
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
