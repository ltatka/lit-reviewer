from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field


class ProfileError(Exception):
    """Raised when profile.toml is missing required fields or has bad values."""


@dataclass(frozen=True)
class Profile:
    description: str
    domain_focus: list[str]
    portable_ml: str
    cadence_days: int
    picks_per_run: int
    classic_fraction: float
    lookback_days: int
    sources_enabled: list[str]
    sources_config: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Profile":
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError as exc:
            raise ProfileError(f"profile not found: {path}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ProfileError(f"profile is not valid TOML: {exc}") from exc

        identity = data.get("identity", {})
        axes = data.get("axes", {})
        schedule = data.get("schedule", {})
        sources = data.get("sources", {})

        description = identity.get("description", "").strip()
        if not description:
            raise ProfileError("identity.description is required and must be non-empty")

        enabled = sources.get("enabled", [])
        if not enabled:
            raise ProfileError("sources.enabled must list at least one source")

        classic_fraction = float(schedule.get("classic_fraction", 0.30))
        if not 0.0 <= classic_fraction <= 1.0:
            raise ProfileError("schedule.classic_fraction must be between 0 and 1")

        picks_per_run = int(schedule.get("picks_per_run", 5))
        if picks_per_run < 1:
            raise ProfileError("schedule.picks_per_run must be >= 1")

        lookback_days = int(schedule.get("lookback_days", 730))
        if lookback_days < 1:
            raise ProfileError("schedule.lookback_days must be >= 1")

        # Per-source config: any [sources.<name>] table, minus the scalar `enabled`.
        sources_config = {k: v for k, v in sources.items() if isinstance(v, dict)}

        return cls(
            description=description,
            domain_focus=list(axes.get("domain_focus", [])),
            portable_ml=str(axes.get("portable_ml", "")),
            cadence_days=int(schedule.get("cadence_days", 7)),
            picks_per_run=picks_per_run,
            classic_fraction=classic_fraction,
            lookback_days=lookback_days,
            sources_enabled=list(enabled),
            sources_config=sources_config,
        )
