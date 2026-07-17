from __future__ import annotations

from ..config import Profile
from .base import PaperSource
from .openalex import OpenAlexSource

SOURCES: dict[str, type] = {
    "openalex": OpenAlexSource,
}


def build_sources(profile: Profile) -> list[PaperSource]:
    built: list[PaperSource] = []
    for name in profile.sources_enabled:
        cls = SOURCES.get(name)
        if cls is None:
            raise ValueError(f"unknown source: {name!r}")
        built.append(cls(profile.sources_config.get(name, {})))
    return built


__all__ = ["PaperSource", "SOURCES", "build_sources", "OpenAlexSource"]
