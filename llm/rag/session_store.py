from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional

from rag.config import (
    SESSION_MAX_COUNT,
    SESSION_MAX_MESSAGE_CHARS,
    SESSION_MAX_TURNS,
    SESSION_TTL_SECONDS,
)


@dataclass(frozen=True)
class ConversationTurn:
    user: str
    assistant: str


@dataclass
class _Session:
    turns: list[ConversationTurn] = field(default_factory=list)
    touched_at: float = 0.0


class ConversationStore:
    """Thread-safe, TTL/LRU-bounded in-memory conversation history."""

    def __init__(
        self,
        *,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_sessions: int = SESSION_MAX_COUNT,
        max_turns: int = SESSION_MAX_TURNS,
        max_message_chars: int = SESSION_MAX_MESSAGE_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(ttl_seconds, max_sessions, max_turns, max_message_chars) <= 0:
            raise ValueError("conversation store limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.max_turns = max_turns
        self.max_message_chars = max_message_chars
        self._clock = clock
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, session_id: Optional[str]) -> list[ConversationTurn]:
        if not session_id:
            return []
        with self._lock:
            now = self._clock()
            self._prune(now)
            session = self._sessions.get(session_id)
            if session is None:
                return []
            session.touched_at = now
            self._sessions.move_to_end(session_id)
            return list(session.turns)

    def append(self, session_id: Optional[str], user: str, assistant: str) -> None:
        if not session_id or not user.strip() or not assistant.strip():
            return
        with self._lock:
            now = self._clock()
            self._prune(now)
            session = self._sessions.get(session_id)
            if session is None:
                session = _Session(touched_at=now)
                self._sessions[session_id] = session
            session.turns.append(
                ConversationTurn(
                    user=user.strip()[-self.max_message_chars :],
                    assistant=assistant.strip()[-self.max_message_chars :],
                )
            )
            session.turns = session.turns[-self.max_turns :]
            session.touched_at = now
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._prune(self._clock())
            return {
                "sessions": len(self._sessions),
                "turns": sum(len(session.turns) for session in self._sessions.values()),
            }

    def _prune(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.touched_at >= self.ttl_seconds
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
