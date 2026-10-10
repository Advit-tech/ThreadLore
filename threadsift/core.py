from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

_SPLIT = re.compile(r"[^a-z0-9]+")
_WHATSAPP = re.compile(r"^\[(?P<stamp>[^\]]+)\]\s*(?P<author>[^:]+):\s*(?P<message>.+)$")
_LOG = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\s+(?P<author>[^:]+):\s*(?P<message>.+)$")
_AUTHOR = re.compile(r"^(?P<author>[^:]{1,40}):\s*(?P<message>.+)$")


@dataclass(frozen=True)
class SearchResult:
    text: str
    score: int


def _tokens(value: str) -> list[str]:
    return [token for token in _SPLIT.split(value.lower()) if token]


def _normalize_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line:
        return ""
    for matcher in (_WHATSAPP, _LOG, _AUTHOR):
        match = matcher.match(line)
        if match:
            parts = [match.groupdict().get("stamp"), match.groupdict().get("author"), match.groupdict()["message"]]
            return " | ".join(part.strip() for part in parts if part and part.strip())
    return line


def load_records(paths: Iterable[str | Path]) -> list[str]:
    records: list[str] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                normalized = _normalize_line(raw_line)
                if normalized:
                    records.append(normalized)
    return records


class ThreadSift:
    def __init__(self, records: Iterable[str]):
        self.records = [record.strip() for record in records if record and record.strip()]

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        scored: list[SearchResult] = []
        for record in self.records:
            record_tokens = _tokens(record)
            if not record_tokens:
                continue
            score = sum(record_tokens.count(token) for token in query_tokens)
            if score:
                scored.append(SearchResult(text=record, score=score))

        scored.sort(key=lambda result: (-result.score, len(result.text), result.text.lower()))
        return scored[: max(0, top_k)]

    def synthesize(self, query: str, top_k: int = 5) -> str:
        matches = self.search(query, top_k=top_k)
        if not matches:
            return f"No relevant context found for query: {query!r}."

        terms = _tokens(query)
        focus = ", ".join(sorted(set(terms))) if terms else query.strip()
        lines = [
            "AI synthesis (local heuristic):",
            f"Focus: {focus}",
            f"Relevant messages: {len(matches)}",
            "Highlights:",
        ]
        for idx, match in enumerate(matches, start=1):
            lines.append(f"{idx}. ({match.score}) {match.text}")
        return "\n".join(lines)
