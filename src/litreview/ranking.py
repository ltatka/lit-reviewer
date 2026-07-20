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
            f"[{i}] ({c.published_date or 'n.d.'}) {c.title}\n    {(c.abstract or '')[:1500]}"
            for i, c in enumerate(candidates)
        )
        system = (
            "You are a strict curator selecting papers for a specific researcher. "
            "Apply the researcher's relevance bar literally and conservatively. It "
            "is much better to return FEWER papers — even none — than to include "
            "one that does not clearly meet the bar. Never pad the list to reach a "
            "target count. Return only the 0-based indices of papers that clearly "
            "qualify, best first."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n"
            f"Portable-ML interest: {profile.portable_ml}\n\n"
            "Selection bar — a paper qualifies ONLY if a novel ML/AI/computational "
            "method is its CENTRAL contribution:\n"
            "- INCLUDE: the main contribution is a new ML/AI method, model, or "
            "algorithm relevant to the domain focus above, OR a broadly interesting "
            "ML method that could plausibly transfer to it.\n"
            "- EXCLUDE: purely biological / wet-lab / mass-spec / DIA / proteomics "
            "papers with no novel ML contribution, however good the biology.\n"
            "- EXCLUDE: papers where ML is merely applied as an off-the-shelf tool "
            "to process or analyze data ('we used a neural network to analyze our "
            "results'). The methodological novelty, not the application, must be the "
            "point.\n"
            "When uncertain, EXCLUDE.\n\n"
            "A publication date is shown in parentheses before each title; all else "
            "being roughly equal in quality and fit, prefer the more recent paper — "
            "but treat this only as a soft tiebreaker, never as a reason to include "
            "a paper that does not clearly meet the bar above.\n\n"
            f"From these {len(candidates)} candidates, return the 0-based indices of "
            f"AT MOST {n} that clearly meet the bar, best first. Return an empty "
            "list if none qualify. Do not include borderline or filler papers.\n\n"
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
        # De-dup indices order-preservingly: a repeated index would map the same
        # Candidate twice and trip the papers.dedup_key UNIQUE constraint on store.
        seen: set[int] = set()
        chosen: list[int] = []
        for i in msg.parsed_output.indices:
            if i not in seen:
                seen.add(i)
                chosen.append(i)
        chosen = chosen[:n]
        return [candidates[i] for i in chosen if 0 <= i < len(candidates)]
