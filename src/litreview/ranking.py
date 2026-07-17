from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from .config import Profile
from .llm import MODEL, get_client
from .models import Candidate


def allocate_slots(picks: int, classic_fraction: float,
                   n_classic_available: int, n_fresh_available: int) -> tuple[int, int]:
    classic_slots = min(round(picks * classic_fraction), n_classic_available)
    fresh_slots = min(picks - classic_slots, n_fresh_available)
    # If fresh couldn't absorb its share, hand the spare back to classics.
    spare = picks - classic_slots - fresh_slots
    if spare > 0:
        classic_slots = min(classic_slots + spare, n_classic_available)
    return classic_slots, fresh_slots


class Ranker(Protocol):
    def select(self, candidates: list[Candidate], profile: Profile,
               n: int) -> list[Candidate]:
        ...


class FakeRanker:
    def select(self, candidates: list[Candidate], profile, n: int) -> list[Candidate]:
        return candidates[:n]


class _Selection(BaseModel):
    indices: list[int]  # 0-based indices into the candidate list, best first


class ClaudeRanker:
    def __init__(self, client=None) -> None:
        self._client = client or get_client()

    def select(self, candidates: list[Candidate], profile: Profile,
               n: int) -> list[Candidate]:
        if n <= 0 or not candidates:
            return []
        listing = "\n".join(
            f"[{i}] {c.title}\n    {(c.abstract or '')[:600]}"
            for i, c in enumerate(candidates)
        )
        system = (
            "You select the most relevant scientific papers for a specific "
            "researcher. Return only indices, best first."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n"
            f"Portable-ML interest: {profile.portable_ml}\n\n"
            f"Pick the {n} best of these {len(candidates)} candidates. "
            f"Return their 0-based indices, best first, at most {n}.\n\n"
            f"{listing}"
        )
        msg = self._client.messages.parse(
            model=MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=_Selection,
        )
        chosen = msg.parsed_output.indices[:n]
        return [candidates[i] for i in chosen if 0 <= i < len(candidates)]
