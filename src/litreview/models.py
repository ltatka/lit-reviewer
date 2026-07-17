from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    authors: list[str]
    doi: str | None = None
    venue: str | None = None
    published_date: str | None = None  # ISO YYYY-MM-DD
    abstract: str | None = None
    url: str | None = None
    is_oa: bool = False
    full_text: str | None = None
    kind: str = "fresh"  # "fresh" | "classic"

    def dedup_key(self) -> str:
        if self.doi:
            return f"doi:{self.doi}"
        return f"src:{self.source}:{self.source_id}"


@dataclass
class Summary:
    approach: str
    result: str
    novelty: str
    relevance: str
    why_relevant_axes: list[str] = field(default_factory=list)
    eli12: str = ""


@dataclass
class ClassicEntry:
    title: str
    note: str
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    id: int | None = None
    rank: int = 0
    status: str = "pending"  # "pending" | "shown"
