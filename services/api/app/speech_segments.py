from __future__ import annotations

import re


class SpeechSegmenter:
    def __init__(self, soft_limit: int = 40, clause_limit: int = 8) -> None:
        self.pending = ""
        self.soft_limit = soft_limit
        self.clause_limit = clause_limit
        self.metadata_started = False

    def feed(self, text: str, *, flush: bool = False) -> list[str]:
        if not self.metadata_started:
            self.pending += text
            metadata = re.search(r"(?:^|\n)\s*\{", self.pending)
            if metadata:
                self.pending = self.pending[: metadata.start()]
                self.metadata_started = True

        segments: list[str] = []
        while self.pending:
            end = self._next_end(flush)
            if not end:
                break
            segment = self.pending[:end].strip()
            self.pending = self.pending[end:]
            if segment:
                segments.append(segment)
        return segments

    def finish(self) -> list[str]:
        return self.feed("", flush=True)

    def _next_end(self, flush: bool) -> int:
        for match in re.finditer(r"[。！？!?；;\n]", self.pending):
            if len(self.pending[: match.end()].strip()) >= 4:
                return match.end()

        for match in re.finditer(r"[，,：:]", self.pending):
            if len(self.pending[: match.start()].strip()) >= self.clause_limit:
                return match.end()

        if len(self.pending) >= self.soft_limit:
            limit = min(self.soft_limit, len(self.pending))
            soft_end = -1
            for index in range(18, limit):
                if self.pending[index] in "，,：:":
                    soft_end = index + 1
            return soft_end if soft_end > 0 else limit
        return len(self.pending) if flush else 0
