from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from .config import Profile
from .llm import MODEL, get_client
from .models import Candidate, Summary


class Summarizer(Protocol):
    def summarize(self, candidate: Candidate, profile: Profile) -> Summary:
        ...


class FakeSummarizer:
    def summarize(self, candidate: Candidate, profile) -> Summary:
        return Summary(
            approach=f"Approach of {candidate.title}.",
            result="Key result.",
            novelty="Why it is novel.",
            relevance=f"Why {candidate.title} is relevant to you.",
            why_relevant_axes=["domain"],
            eli12=f"Imagine {candidate.title} explained simply.",
        )


class _SummaryOut(BaseModel):
    approach: str
    result: str
    novelty: str
    relevance: str
    why_relevant_axes: list[str]
    eli12: str


class ClaudeSummarizer:
    def __init__(self, client=None) -> None:
        self._client = client or get_client()

    def summarize(self, candidate: Candidate, profile: Profile) -> Summary:
        body = candidate.full_text or candidate.abstract or "(no abstract available)"
        system = (
            "You summarize a scientific paper for a specific researcher. Be "
            "concrete and concise. 'relevance' must explain why THIS researcher "
            "should care. 'why_relevant_axes' is a subset of "
            "['domain', 'portable_ml', 'classic']. 'eli12' is an 'explain like "
            "I'm 12' paragraph: 3-4 sentences, plain language, no jargon or "
            "acronyms, analogies welcome, so a curious 12-year-old could follow it."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n"
            f"Portable-ML interest: {profile.portable_ml}\n\n"
            f"Paper title: {candidate.title}\n"
            f"Venue: {candidate.venue or 'unknown'}\n"
            f"Kind: {candidate.kind}\n"
            f"Content:\n{body[:6000]}"
        )
        msg = self._client.messages.parse(
            model=MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=_SummaryOut,
        )
        out = msg.parsed_output
        return Summary(
            approach=out.approach,
            result=out.result,
            novelty=out.novelty,
            relevance=out.relevance,
            why_relevant_axes=out.why_relevant_axes,
            eli12=out.eli12,
        )
