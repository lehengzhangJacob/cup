###############################################################################
#  Output — WebRTC 输出（同时缓存 JPEG 供 HTTP/MJPEG 预览）
###############################################################################

import os
import threading
import time
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

from streamout.base_output import BaseOutput
from registry import register
from utils.logger import logger

if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar


@register("streamout", "webrtc")
@register("streamout", "rtcpush")
class WebRTCOutput(BaseOutput):
    """WebRTC 输出；无 player 时缓存 JPEG，供同源 HTTP/MJPEG 使用。"""

    def __init__(self, opt=None, parent: Optional['BaseAvatar'] = None, **kwargs):
        super().__init__(opt, parent)
        self._player = None
        self._jpeg_lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._next_http_frame_at: Optional[float] = None
        self._http_fps = float(os.getenv("LIVETALKING_HTTP_FPS", "12"))
        self._http_width = int(os.getenv("LIVETALKING_HTTP_WIDTH", "432"))
        self._http_jpeg_quality = int(os.getenv("LIVETALKING_HTTP_JPEG_Q", "60"))

    def start(self) -> None:
        pass

    def _update_jpeg(self, frame: np.ndarray) -> None:
        try:
            height, width = frame.shape[:2]
            if width > self._http_width:
                resized_height = max(1, int(height * self._http_width / width))
                frame = cv2.resize(
                    frame,
                    (self._http_width, resized_height),
                    interpolation=cv2.INTER_LINEAR,
                )
            encoded, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self._http_jpeg_quality],
            )
            if encoded:
                with self._jpeg_lock:
                    self._latest_jpeg = buffer.tobytes()
        except Exception as exc:
            logger.debug("JPEG preview encoding failed: %s", exc)

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._jpeg_lock:
            return self._latest_jpeg

    def _pace_http_frame(self) -> None:
        interval = 1.0 / max(1.0, self._http_fps)
        now = time.perf_counter()
        if self._next_http_frame_at is None:
            self._next_http_frame_at = now
        delay = self._next_http_frame_at - now
        if delay > 0:
            time.sleep(min(delay, 0.12))
        self._next_http_frame_at = max(
            self._next_http_frame_at + interval,
            time.perf_counter(),
        )

    def push_video_frame(self, frame) -> None:
        if isinstance(frame, np.ndarray) and self._player is None:
            self._update_jpeg(frame)
            self._pace_http_frame()
        if self._player:
            self._player.push_video(frame)

    def push_audio_frame(self, frame, eventpoint=None) -> None:
        if self._player:
            self._player.push_audio(frame, eventpoint)

    def get_buffer_size(self) -> int:
        if self._player and hasattr(self._player, 'get_buffer_size'):
            return self._player.get_buffer_size()
        return 0

    def stop(self) -> None:
        pass
