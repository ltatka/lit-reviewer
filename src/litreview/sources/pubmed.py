from __future__ import annotations

import datetime

import httpx

from ..models import Candidate

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _split_authors(author_string: str | None) -> list[str]:
    if not author_string:
        return []
    return [a.strip().rstrip(".") for a in author_string.split(",") if a.strip()]


class PubMedSource:
    name = "pubmed"

    def __init__(self, config: dict, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(self, query: str, since: datetime.date | None) -> list[Candidate]:
        q = query
        if since:
            today = datetime.date.today().isoformat()
            q = f"({query}) AND (FIRST_PDATE:[{since.isoformat()} TO {today}])"
        params = {
            "query": q,
            "format": "json",
            "pageSize": str(self.config.get("per_page", 40)),
            "sort": "P_PDATE_D desc",
        }
        resp = self._client.get(_BASE, params=params)
        resp.raise_for_status()
        results = resp.json().get("resultList", {}).get("result", [])
        out: list[Candidate] = []
        for r in results:
            urls = (r.get("fullTextUrlList") or {}).get("fullTextUrl") or []
            url = urls[0]["url"] if urls else None
            out.append(Candidate(
                source="pubmed",
                source_id=str(r.get("id")),
                title=r.get("title") or "(untitled)",
                authors=_split_authors(r.get("authorString")),
                doi=r.get("doi"),
                venue=r.get("journalTitle"),
                published_date=r.get("firstPublicationDate"),
                abstract=r.get("abstractText"),
                url=url,
                is_oa=r.get("isOpenAccess") == "Y",
            ))
        return out
