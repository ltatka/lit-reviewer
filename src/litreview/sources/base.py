from __future__ import annotations

import datetime
from typing import Protocol

from ..models import Candidate


class PaperSource(Protocol):
    name: str

    def fetch(self, query: str, since: datetime.date | None) -> list[Candidate]:
        ...
