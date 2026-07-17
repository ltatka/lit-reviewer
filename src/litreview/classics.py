from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from .archive import Archive
from .config import Profile
from .llm import MODEL, get_client
from .models import ClassicEntry


class ClassicsDrafter(Protocol):
    def draft(self, profile: Profile, n: int) -> list[ClassicEntry]:
        ...


class FakeClassicsDrafter:
    def draft(self, profile, n: int) -> list[ClassicEntry]:
        return [
            ClassicEntry(title=f"Foundational Paper {i + 1}",
                         note="foundational", rank=i + 1)
            for i in range(n)
        ]


class _ClassicOut(BaseModel):
    title: str
    authors: list[str]
    doi: str | None = None
    note: str


class _ClassicsList(BaseModel):
    papers: list[_ClassicOut]


class ClaudeClassicsDrafter:
    def __init__(self, client=None) -> None:
        self._client = client or get_client()

    def draft(self, profile: Profile, n: int) -> list[ClassicEntry]:
        system = (
            "You are a senior scientist building a reading list of foundational, "
            "must-read papers for a researcher. Rank by importance, most "
            "foundational first. 'note' says why it is essential."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n\n"
            f"List the {n} most important foundational papers this person should "
            f"have read. Provide a DOI when you are confident of it, else null."
        )
        msg = self._client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=_ClassicsList,
        )
        return [
            ClassicEntry(title=p.title, authors=p.authors, doi=p.doi,
                         note=p.note, rank=i + 1)
            for i, p in enumerate(msg.parsed_output.papers[:n])
        ]


def init_classics(profile: Profile, archive: Archive,
                  drafter: ClassicsDrafter, n: int = 20) -> list[ClassicEntry]:
    entries = drafter.draft(profile, n)
    archive.add_classics(entries)
    return entries
