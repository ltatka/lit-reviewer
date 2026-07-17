from __future__ import annotations

import datetime

import httpx

from ..models import Candidate

_BASE = "https://api.openalex.org/works"


def _strip_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.replace("https://doi.org/", "")


def _reconstruct_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda t: t[0])
    return " ".join(word for _, word in positions)


class OpenAlexSource:
    name = "openalex"

    def __init__(self, config: dict, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(self, query: str, since: datetime.date | None) -> list[Candidate]:
        filters = []
        if since:
            filters.append(f"from_publication_date:{since.isoformat()}")
        params = {
            "search": query,
            "per-page": str(self.config.get("per_page", 40)),
            "sort": "publication_date:desc",
        }
        if filters:
            params["filter"] = ",".join(filters)
        resp = self._client.get(_BASE, params=params)
        resp.raise_for_status()
        out: list[Candidate] = []
        for w in resp.json().get("results", []):
            oa_id = str(w.get("id", "")).rsplit("/", 1)[-1]
            loc = w.get("primary_location") or {}
            source_obj = loc.get("source") or {}
            out.append(Candidate(
                source="openalex",
                source_id=oa_id,
                title=w.get("title") or "(untitled)",
                authors=[
                    a["author"]["display_name"]
                    for a in w.get("authorships", [])
                    if a.get("author", {}).get("display_name")
                ],
                doi=_strip_doi(w.get("doi")),
                venue=source_obj.get("display_name"),
                published_date=w.get("publication_date"),
                abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
                url=w.get("id"),
                is_oa=bool((w.get("open_access") or {}).get("is_oa")),
            ))
        return out
