from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import signal
import subprocess
import time
from collections.abc import Callable

import torch

from utils.logger import logger


class GPUUnavailableError(RuntimeError):
    pass


class GPULifecycle:
    def __init__(
        self,
        model: torch.nn.Module,
        warmup: Callable[[], None],
        active_sessions: Callable[[], int],
    ) -> None:
        self.model = model
        self.warmup = warmup
        self.active_sessions = active_sessions
        raw_candidates = os.getenv("LIVETALKING_GPU_CANDIDATES", "0,1,2,3")
        self.candidates = [
            int(value.strip())
            for value in raw_candidates.split(",")
            if value.strip().isdigit()
        ]
        self.min_free_mb = int(os.getenv("LIVETALKING_GPU_MIN_FREE_MB", "2048"))
        self.offload_delay = float(
            os.getenv("LIVETALKING_GPU_OFFLOAD_DELAY_SECONDS", "2")
        )
        self.exit_after_offload = (
            os.getenv("LIVETALKING_EXIT_AFTER_GPU_OFFLOAD", "true").lower()
            in {"1", "true", "yes"}
        )
        self.lock = asyncio.Lock()
        self.offload_task: asyncio.Task[None] | None = None
        self.gpu_index: int | None = None
        self.last_selection: list[dict[str, int]] = []

    def status(self) -> dict:
        device = str(next(self.model.parameters()).device)
        return {
            "mode": "gpu" if self.gpu_index is not None else "cpu-standby",
            "device": device,
            "gpu_index": self.gpu_index,
            "active_sessions": self.active_sessions(),
            "exit_after_offload": self.exit_after_offload,
            "candidates": self.candidates,
            "last_selection": self.last_selection,
        }

    def _gpu_snapshot(self) -> list[dict[str, int]]:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        snapshot: list[dict[str, int]] = []
        allowed = set(self.candidates)
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 3:
                continue
            index, free_mb, utilization = map(int, parts)
            if index in allowed:
                snapshot.append(
                    {
                        "index": index,
                        "free_mb": free_mb,
                        "utilization": utilization,
                    }
                )
        return snapshot

    def _select_gpu(self) -> int:
        snapshot = self._gpu_snapshot()
        self.last_selection = snapshot
        eligible = [
            gpu for gpu in snapshot if gpu["free_mb"] >= self.min_free_mb
        ]
        if not eligible:
            raise GPUUnavailableError(
                f"No GPU has at least {self.min_free_mb} MiB free"
            )
        selected = min(
            eligible,
            key=lambda gpu: (gpu["utilization"], -gpu["free_mb"], gpu["index"]),
        )
        return selected["index"]

    def _promote(self, gpu_index: int) -> None:
        target = torch.device(f"cuda:{gpu_index}")
        self.model.to(device=target, dtype=torch.float16)
        self.warmup()
        torch.cuda.synchronize(target)

    def _offload(self, gpu_index: int) -> None:
        source = torch.device(f"cuda:{gpu_index}")
        self.model.to(device="cpu")
        gc.collect()
        with torch.cuda.device(source):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    async def acquire(self) -> int:
        if self.offload_task and not self.offload_task.done():
            self.offload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.offload_task
        async with self.lock:
            if self.gpu_index is not None:
                return self.gpu_index
            started = time.perf_counter()
            gpu_index = await asyncio.to_thread(self._select_gpu)
            try:
                await asyncio.to_thread(self._promote, gpu_index)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._offload, gpu_index)
                raise GPUUnavailableError(
                    f"Failed to activate GPU {gpu_index}: {exc}"
                ) from exc
            self.gpu_index = gpu_index
            logger.info(
                "Promoted Wav2Lip from CPU to GPU %d in %.0f ms",
                gpu_index,
                (time.perf_counter() - started) * 1000,
            )
            return gpu_index

    def schedule_offload(self) -> None:
        if self.offload_task and not self.offload_task.done():
            self.offload_task.cancel()
        self.offload_task = asyncio.create_task(self._offload_when_idle())

    async def _offload_when_idle(self) -> None:
        try:
            await asyncio.sleep(self.offload_delay)
            if self.active_sessions():
                return
            async with self.lock:
                if self.active_sessions() or self.gpu_index is None:
                    return
                gpu_index = self.gpu_index
                started = time.perf_counter()
                offload_worker = asyncio.create_task(
                    asyncio.to_thread(self._offload, gpu_index)
                )
                try:
                    await asyncio.shield(offload_worker)
                except asyncio.CancelledError:
                    await offload_worker
                self.gpu_index = None
                logger.info(
                    "Offloaded Wav2Lip from GPU %d to CPU in %.0f ms",
                    gpu_index,
                    (time.perf_counter() - started) * 1000,
                )
                if self.exit_after_offload:
                    logger.info(
                        "Restarting LiveTalking in CPU standby to release the CUDA context"
                    )
                    os.kill(os.getpid(), signal.SIGTERM)
        except asyncio.CancelledError:
            return

    async def shutdown(self) -> None:
        if self.offload_task and not self.offload_task.done():
            self.offload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.offload_task
        async with self.lock:
            if self.gpu_index is None:
                return
            gpu_index = self.gpu_index
            await asyncio.to_thread(self._offload, gpu_index)
            self.gpu_index = None
