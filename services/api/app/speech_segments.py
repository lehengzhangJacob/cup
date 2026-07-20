from __future__ import annotations

import re


class SpeechSegmenter:
    def __init__(
        self,
        first_clause_limit: int = 8,
        clause_limit: int = 24,
        hard_limit: int = 120,
    ) -> None:
        self.pending = ""
        self.first_clause_limit = first_clause_limit
        self.clause_limit = clause_limit
        self.hard_limit = hard_limit
        self.metadata_started = False
        self.segments_emitted = 0

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
                self.segments_emitted += 1
        return segments

    def finish(self) -> list[str]:
        return self.feed("", flush=True)

    def _next_end(self, flush: bool) -> int:
        candidate_ends: list[int] = []
        for match in re.finditer(r"[。！？!?；;\n]", self.pending):
            if len(self.pending[: match.end()].strip()) >= 4:
                candidate_ends.append(match.end())
                break

        clause_limit = (
            self.first_clause_limit
            if self.segments_emitted == 0
            else self.clause_limit
        )
        for match in re.finditer(r"[，,]", self.pending):
            if len(self.pending[: match.start()].strip()) >= clause_limit:
                candidate_ends.append(match.end())
                break

        if candidate_ends:
            return min(candidate_ends)

        # Do not split ordinary text at a fixed character count. A TTS request
        # needs the complete sentence to infer prosody and pronounce word
        # boundaries reliably. The hard limit is only a safety valve for very
        # long model output that contains no punctuation at all.
        if len(self.pending) >= self.hard_limit:
            return self.hard_limit
        return len(self.pending) if flush else 0
