from __future__ import annotations

import datetime
import json
import sqlite3
from importlib import resources

from .models import Candidate, ClassicEntry, Summary


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class Archive:
    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        ddl = resources.files("litreview").joinpath("schema.sql").read_text()
        with self._connect() as conn:
            conn.executescript(ddl)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(summaries)")}
            if "eli12" not in cols:
                conn.execute(
                    "ALTER TABLE summaries ADD COLUMN eli12 TEXT NOT NULL DEFAULT ''"
                )

    # ---- dedup -------------------------------------------------------------

    def filter_new(self, candidates: list[Candidate]) -> list[Candidate]:
        with self._connect() as conn:
            existing = {
                row["dedup_key"]
                for row in conn.execute("SELECT dedup_key FROM papers")
            }
        out: list[Candidate] = []
        seen_this_batch: set[str] = set()
        for c in candidates:
            key = c.dedup_key()
            if key in existing or key in seen_this_batch:
                continue
            seen_this_batch.add(key)
            out.append(c)
        return out

    # ---- runs --------------------------------------------------------------

    def create_run(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (_now_iso(),),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, n_candidates: int, n_selected: int,
                   status: str, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, n_candidates=?, n_selected=?, "
                "status=?, error=? WHERE id=?",
                (_now_iso(), n_candidates, n_selected, status, error, run_id),
            )

    def last_successful_run_date(self) -> datetime.date | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM runs WHERE status='ok' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return datetime.date.fromisoformat(row["started_at"][:10])

    def last_run(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    # ---- store selection (atomic) -----------------------------------------

    def store_selection(self, run_id: int,
                         items: list[tuple[Candidate, Summary]]) -> None:
        with self._connect() as conn:  # transaction: commits on clean exit
            for cand, summ in items:
                cur = conn.execute(
                    "INSERT INTO papers (dedup_key, doi, source, source_id, title, "
                    "authors, venue, published_date, abstract, url, is_oa, kind, "
                    "first_surfaced_run) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        cand.dedup_key(), cand.doi, cand.source, cand.source_id,
                        cand.title, json.dumps(cand.authors), cand.venue,
                        cand.published_date, cand.abstract, cand.url,
                        1 if cand.is_oa else 0, cand.kind, run_id,
                    ),
                )
                paper_id = int(cur.lastrowid)
                conn.execute(
                    "INSERT INTO summaries (paper_id, approach, result, novelty, "
                    "relevance, why_relevant_axes, eli12, status) "
                    "VALUES (?,?,?,?,?,?,?, 'unread')",
                    (
                        paper_id, summ.approach, summ.result, summ.novelty,
                        summ.relevance, json.dumps(summ.why_relevant_axes),
                        summ.eli12,
                    ),
                )
                if cand.kind == "classic":
                    if cand.doi:
                        conn.execute(
                            "UPDATE classics SET status='shown' WHERE doi=?",
                            (cand.doi,),
                        )
                    else:
                        conn.execute(
                            "UPDATE classics SET status='shown' WHERE title=?",
                            (cand.title,),
                        )

    # ---- classics ----------------------------------------------------------

    def add_classics(self, entries: list[ClassicEntry]) -> None:
        with self._connect() as conn:
            for e in entries:
                conn.execute(
                    "INSERT INTO classics (title, authors, doi, note, rank, status) "
                    "VALUES (?,?,?,?,?, 'pending')",
                    (e.title, json.dumps(e.authors), e.doi, e.note, e.rank),
                )

    def pending_classics(self, limit: int) -> list[ClassicEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM classics WHERE status='pending' "
                "ORDER BY rank ASC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            ClassicEntry(
                id=r["id"], title=r["title"], authors=json.loads(r["authors"]),
                doi=r["doi"], note=r["note"], rank=r["rank"], status=r["status"],
            )
            for r in rows
        ]

    # ---- reading -----------------------------------------------------------

    def _rows_to_dicts(self, rows) -> list[dict]:
        out = []
        for r in rows:
            d = dict(r)
            d["authors"] = json.loads(d["authors"])
            d["why_relevant_axes"] = json.loads(d["why_relevant_axes"])
            d["is_oa"] = bool(d["is_oa"])
            out.append(d)
        return out

    _SELECT = (
        "SELECT s.id AS summary_id, s.approach, s.result, s.novelty, s.relevance, "
        "s.eli12, s.why_relevant_axes, s.status, s.read_at, s.rating, "
        "p.title, p.authors, p.venue, p.published_date, p.url, p.is_oa, p.kind, "
        "p.first_surfaced_run "
        "FROM summaries s JOIN papers p ON p.id = s.paper_id "
    )

    def unread_summaries(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT + "WHERE s.status='unread' "
                "ORDER BY p.first_surfaced_run DESC, s.id ASC"
            ).fetchall()
        return self._rows_to_dicts(rows)

    def archived_summaries(self, query: str | None = None) -> list[dict]:
        sql = self._SELECT + "WHERE s.status='read' "
        params: tuple = ()
        if query:
            sql += "AND p.title LIKE ? "
            params = (f"%{query}%",)
        sql += "ORDER BY s.read_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return self._rows_to_dicts(rows)

    def mark_read(self, summary_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE summaries SET status='read', read_at=? WHERE id=?",
                (_now_iso(), summary_id),
            )

    def mark_all_read(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE summaries SET status='read', read_at=? WHERE status='unread'",
                (_now_iso(),),
            )

    def set_rating(self, summary_id: int, rating: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE summaries SET rating=? WHERE id=?", (rating, summary_id)
            )
