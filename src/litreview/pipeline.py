from __future__ import annotations

from .archive import Archive
from .config import Profile
from .models import Candidate, ClassicEntry
from .ranking import Ranker, allocate_slots
from .sources.base import PaperSource
from .summarize import Summarizer


def _classic_to_candidate(e: ClassicEntry) -> Candidate:
    return Candidate(
        source="classics",
        source_id=(e.doi or e.title),
        title=e.title,
        authors=e.authors,
        doi=e.doi,
        abstract=e.note,
        kind="classic",
    )


class Pipeline:
    def __init__(self, profile: Profile, archive: Archive,
                 sources: list[PaperSource], ranker: Ranker,
                 summarizer: Summarizer) -> None:
        self.profile = profile
        self.archive = archive
        self.sources = sources
        self.ranker = ranker
        self.summarizer = summarizer

    def run(self) -> dict:
        run_id = self.archive.create_run()
        try:
            since = self.archive.last_successful_run_date()

            fresh_pool: list[Candidate] = []
            for src in self.sources:
                query = self.profile.sources_config.get(src.name, {}).get("query", "")
                fresh_pool.extend(src.fetch(query, since))

            classic_pool = [
                _classic_to_candidate(e)
                for e in self.archive.pending_classics(self.profile.picks_per_run)
            ]

            fresh_pool = self.archive.filter_new(fresh_pool)
            classic_pool = self.archive.filter_new(classic_pool)
            n_candidates = len(fresh_pool) + len(classic_pool)

            classic_slots, fresh_slots = allocate_slots(
                self.profile.picks_per_run, self.profile.classic_fraction,
                len(classic_pool), len(fresh_pool),
            )

            selected: list[Candidate] = []
            selected += self.ranker.select(classic_pool, self.profile, classic_slots)
            selected += self.ranker.select(fresh_pool, self.profile, fresh_slots)

            items = [(c, self.summarizer.summarize(c, self.profile)) for c in selected]
            self.archive.store_selection(run_id, items)
            self.archive.finish_run(run_id, n_candidates, len(items), status="ok")
            return {
                "run_id": run_id,
                "n_candidates": n_candidates,
                "n_selected": len(items),
                "status": "ok",
            }
        except Exception as exc:
            self.archive.finish_run(run_id, 0, 0, status="error", error=str(exc))
            raise
