"""Measure chat first-token and LiveTalking first-audio latency."""

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


async def open_livetalking_session():
    peer = RTCPeerConnection()
    request_started = asyncio.Event()
    first_audio = asyncio.get_running_loop().create_future()
    request_start = [0.0]
    audio_tasks: list[asyncio.Task[None]] = []

    async def consume_audio(track) -> None:
        try:
            while True:
                frame = await track.recv()
                if not request_started.is_set() or first_audio.done():
                    continue
                samples = frame.to_ndarray().astype(np.int32, copy=False)
                if samples.size and int(np.abs(samples).max()) >= 300:
                    first_audio.set_result(time.perf_counter() - request_start[0])
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
            f"{LIVETALKING_URL}/offer",
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
    return peer, session_id, request_started, request_start, first_audio, audio_tasks


async def close_livetalking_session(
    peer: RTCPeerConnection,
    session_id: str,
    audio_tasks: list[asyncio.Task[None]],
) -> None:
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        try:
            await client.post(
                f"{LIVETALKING_URL}/close_session",
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
) -> dict[str, float | str]:
    (
        peer,
        session_id,
        request_started,
        request_start,
        first_audio,
        audio_tasks,
    ) = await open_livetalking_session()
    first_token = None
    chat_done = None
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
                    if event.get("type") == "done":
                        chat_done = elapsed
        first_audio_seconds = await asyncio.wait_for(first_audio, timeout=20.0)
        return {
            "url": base_url,
            "model_route": model_route,
            "session_id": session_id,
            "first_token_ms": round((first_token or 0) * 1000),
            "chat_done_ms": round((chat_done or 0) * 1000),
            "first_audio_ms": round(first_audio_seconds * 1000),
        }
    finally:
        await close_livetalking_session(peer, session_id, audio_tasks)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "urls",
        nargs="*",
        default=["http://127.0.0.1:8001", "https://lingshanguide.de5.net"],
    )
    parser.add_argument("--question", default="灵山大佛有多高？")
    parser.add_argument("--model-route", choices=("cloud", "local"), default="cloud")
    args = parser.parse_args()
    for url in args.urls:
        result = await benchmark(url, args.question, args.model_route)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
