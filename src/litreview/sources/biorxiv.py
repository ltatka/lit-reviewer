from __future__ import annotations

import datetime

import httpx

from ..models import Candidate

_BASE = "https://api.biorxiv.org/details"


class BioRxivSource:
    name = "biorxiv"

    def __init__(self, config: dict, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(self, query: str, since: datetime.date | None) -> list[Candidate]:
        server = self.config.get("server", "biorxiv")
        window = int(self.config.get("lookback_days", 30))
        floor = datetime.date.today() - datetime.timedelta(days=window)
        start_date = max(since, floor) if since is not None else floor
        start = start_date.isoformat()
        end = datetime.date.today().isoformat()
        url = f"{_BASE}/{server}/{start}/{end}/0"
        resp = self._client.get(url)
        resp.raise_for_status()
        wanted = (self.config.get("category") or "").strip().lower()
        out: list[Candidate] = []
        for r in resp.json().get("collection", []):
            if wanted and (r.get("category") or "").strip().lower() != wanted:
                continue
            doi = r.get("doi")
            authors = [a.strip() for a in (r.get("authors") or "").split(";") if a.strip()]
            out.append(Candidate(
                source="biorxiv",
                source_id=doi or r.get("title", ""),
                title=r.get("title") or "(untitled)",
                authors=authors,
                doi=doi,
                venue="bioRxiv",
                published_date=r.get("date"),
                abstract=r.get("abstract"),
                url=f"https://www.biorxiv.org/content/{doi}" if doi else None,
                is_oa=True,
            ))
        return out
