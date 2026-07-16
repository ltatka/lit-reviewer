# Lit Review App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, single-user app that weekly fetches relevant scientific papers, LLM-ranks and summarizes the best 3–6, and serves them in a web UI where the user reads and acknowledges them into a searchable archive.

**Architecture:** A deterministic Python pipeline (`fetch → dedupe → allocate slots → rank → summarize → store`) with the LLM injected at exactly two judgment points (`Ranker`, `Summarizer`), both behind interfaces. Storage is a single SQLite file. A FastAPI + Jinja + htmx web UI reads that DB. Scheduling lives outside the app (a documented `launchd` job invokes `litreview run`).

**Tech Stack:** Python 3.11+, SQLite (stdlib `sqlite3`), `httpx` (paper-source HTTP), `anthropic` SDK (Claude, structured outputs), FastAPI + Jinja2 + `uvicorn` + `python-multipart` (web), `pytest` (tests). Config via `tomllib` (stdlib).

Design spec: `docs/superpowers/specs/2026-07-16-lit-review-app-design.md`.

## Global Constraints

- **Python `requires-python = ">=3.11"`** (uses stdlib `tomllib`).
- **Default model:** `claude-opus-4-8`. Never downgrade without an explicit config value.
- **No personal or machine-specific values in code** — all of it lives in `profile.toml` (git-ignored). Only `profile.example.toml` is committed.
- **The two judgment steps are the only non-deterministic code.** Everything else is deterministic and unit-tested with no network and no live API calls (recorded fixtures + fakes).
- **Dedup key:** `doi` when present, else `source_id`. A paper already in the `papers` table is never recommended again.
- **Atomic store:** papers enter the archive only after they are summarized and written, inside one DB transaction.
- **Anthropic calls use structured outputs** (`client.messages.parse` with a Pydantic model) and adaptive thinking (`thinking={"type": "adaptive"}`).
- Package name: `litreview`. Source under `src/litreview/`. Tests under `tests/`.

---

## File Structure

```
lit_review_app/
  pyproject.toml
  profile.example.toml
  README.md
  deploy/com.talus.litreview.plist.template
  src/litreview/
    __init__.py
    config.py            # Profile dataclass + load()
    models.py            # Candidate, Summary, ClassicEntry dataclasses
    archive.py           # Archive (SQLite): schema, dedup, store, read-state, classics
    schema.sql           # DDL
    llm.py               # Anthropic client factory + shared call helper
    sources/
      __init__.py        # SOURCES registry + build_sources()
      base.py            # PaperSource protocol
      openalex.py        # OpenAlexSource
      pubmed.py          # PubMedSource (via Europe PMC REST)
      biorxiv.py         # BioRxivSource
    ranking.py           # allocate_slots(); Ranker protocol; ClaudeRanker; FakeRanker
    summarize.py         # Summarizer protocol; ClaudeSummarizer; FakeSummarizer
    classics.py          # ClassicsDrafter (LLM) + init_classics()
    pipeline.py          # Pipeline.run()
    cli.py               # argparse CLI: run / status / init-classics / serve
    web/
      app.py             # FastAPI app factory
      templates/
        base.html
        digest.html
        archive.html
        status.html
  tests/
    conftest.py
    fixtures/
      openalex_works.json
      europepmc_search.json
      biorxiv_details.json
    test_config.py
    test_archive.py
    test_sources_openalex.py
    test_sources_pubmed.py
    test_sources_biorxiv.py
    test_ranking.py
    test_summarize.py
    test_pipeline.py
    test_classics.py
    test_web.py
```

---

### Task 1: Project scaffold + Profile loading

**Files:**
- Create: `pyproject.toml`, `src/litreview/__init__.py`, `src/litreview/config.py`, `profile.example.toml`
- Test: `tests/test_config.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `litreview.config.Profile` — frozen dataclass with fields: `description: str`, `domain_focus: list[str]`, `portable_ml: str`, `cadence_days: int`, `picks_per_run: int`, `classic_fraction: float`, `sources_enabled: list[str]`, `sources_config: dict[str, dict]`.
  - `Profile.load(path: str | os.PathLike) -> Profile` (classmethod).
  - `class ProfileError(Exception)`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "litreview"
version = "0.1.0"
description = "Personal weekly literature review digest"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "anthropic>=0.69",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
litreview = "litreview.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `src/litreview/__init__.py`**

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
import textwrap
import pytest
from litreview.config import Profile, ProfileError


def _write(tmp_path, text):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent(text))
    return p


def test_load_full_profile(tmp_path):
    path = _write(tmp_path, """
        [identity]
        description = "I study proteomics."
        [axes]
        domain_focus = ["proteomics", "DIA-MS"]
        portable_ml = "ML that could transfer."
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.30
        [sources]
        enabled = ["openalex", "biorxiv"]
        [sources.openalex]
        query = "proteomics"
    """)
    prof = Profile.load(path)
    assert prof.description == "I study proteomics."
    assert prof.domain_focus == ["proteomics", "DIA-MS"]
    assert prof.picks_per_run == 5
    assert prof.classic_fraction == 0.30
    assert prof.sources_enabled == ["openalex", "biorxiv"]
    assert prof.sources_config["openalex"]["query"] == "proteomics"


def test_missing_description_raises(tmp_path):
    path = _write(tmp_path, """
        [axes]
        domain_focus = []
        portable_ml = "x"
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.3
        [sources]
        enabled = ["openalex"]
    """)
    with pytest.raises(ProfileError):
        Profile.load(path)


def test_invalid_classic_fraction_raises(tmp_path):
    path = _write(tmp_path, """
        [identity]
        description = "x"
        [axes]
        domain_focus = []
        portable_ml = "x"
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 1.5
        [sources]
        enabled = ["openalex"]
    """)
    with pytest.raises(ProfileError):
        Profile.load(path)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.config'`

- [ ] **Step 5: Implement `src/litreview/config.py`**

```python
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

        # Per-source config: any [sources.<name>] table, minus the scalar `enabled`.
        sources_config = {k: v for k, v in sources.items() if isinstance(v, dict)}

        return cls(
            description=description,
            domain_focus=list(axes.get("domain_focus", [])),
            portable_ml=str(axes.get("portable_ml", "")),
            cadence_days=int(schedule.get("cadence_days", 7)),
            picks_per_run=picks_per_run,
            classic_fraction=classic_fraction,
            sources_enabled=list(enabled),
            sources_config=sources_config,
        )
```

- [ ] **Step 6: Create `tests/conftest.py`** (shared fixtures used by later tasks)

```python
import textwrap
import pytest
from litreview.config import Profile


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent("""
        [identity]
        description = "I study proteomics and ML for mass spec."
        [axes]
        domain_focus = ["proteomics", "DIA-MS"]
        portable_ml = "ML methods that could transfer to proteomics."
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.30
        [sources]
        enabled = ["openalex"]
        [sources.openalex]
        query = "proteomics"
    """))
    return Profile.load(p)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Create `profile.example.toml`**

```toml
[identity]
# First-person description of your research interests. The LLM reads this
# verbatim to judge which papers are relevant to you.
description = """
I'm a data scientist working on proteomics / TF-focused drug discovery —
DIA mass spec, targeted protein degradation, ML for proteomics. I also want
exposure to broadly cool ML/AI that could port into our field, and general
things a data-science professional should know about.
"""

[axes]
domain_focus = ["proteomics", "targeted protein degradation", "DIA-MS"]
portable_ml = "New ML/AI methods that could plausibly transfer to proteomics, or that a DS professional should know."

[schedule]
cadence_days = 7
picks_per_run = 5
classic_fraction = 0.30

[sources]
enabled = ["openalex", "pubmed", "biorxiv"]

[sources.openalex]
query = "proteomics OR mass spectrometry proteomics"

[sources.pubmed]
query = "proteomics"

[sources.biorxiv]
# bioRxiv is filtered by subject category (see get_categories).
category = "biochemistry"
```

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/litreview/__init__.py src/litreview/config.py profile.example.toml tests/test_config.py tests/conftest.py
git commit -m "feat: project scaffold + profile loading"
```

---

### Task 2: Domain models

**Files:**
- Create: `src/litreview/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Candidate` dataclass: `source: str`, `source_id: str`, `title: str`, `authors: list[str]`, `doi: str | None = None`, `venue: str | None = None`, `published_date: str | None = None` (ISO `YYYY-MM-DD`), `abstract: str | None = None`, `url: str | None = None`, `is_oa: bool = False`, `full_text: str | None = None`, `kind: str = "fresh"`. Method `dedup_key() -> str` returns `f"doi:{doi}"` if `doi` else `f"src:{source}:{source_id}"`.
  - `Summary` dataclass: `approach: str`, `result: str`, `novelty: str`, `relevance: str`, `why_relevant_axes: list[str]`.
  - `ClassicEntry` dataclass: `title: str`, `note: str`, `authors: list[str] = []`, `doi: str | None = None`, `id: int | None = None`, `rank: int = 0`, `status: str = "pending"`.

- [ ] **Step 1: Write the failing test** — `tests/test_models.py`

```python
from litreview.models import Candidate, Summary, ClassicEntry


def test_dedup_key_prefers_doi():
    c = Candidate(source="openalex", source_id="W1", title="t", authors=[], doi="10.1/x")
    assert c.dedup_key() == "doi:10.1/x"


def test_dedup_key_falls_back_to_source_id():
    c = Candidate(source="openalex", source_id="W1", title="t", authors=[])
    assert c.dedup_key() == "src:openalex:W1"


def test_candidate_defaults():
    c = Candidate(source="s", source_id="i", title="t", authors=["A"])
    assert c.kind == "fresh"
    assert c.is_oa is False
    assert c.full_text is None


def test_summary_and_classic_fields():
    s = Summary(approach="a", result="r", novelty="n", relevance="v",
                why_relevant_axes=["domain"])
    assert s.why_relevant_axes == ["domain"]
    e = ClassicEntry(title="Seminal Paper", note="foundational")
    assert e.status == "pending"
    assert e.authors == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.models'`

- [ ] **Step 3: Implement `src/litreview/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    authors: list[str]
    doi: str | None = None
    venue: str | None = None
    published_date: str | None = None  # ISO YYYY-MM-DD
    abstract: str | None = None
    url: str | None = None
    is_oa: bool = False
    full_text: str | None = None
    kind: str = "fresh"  # "fresh" | "classic"

    def dedup_key(self) -> str:
        if self.doi:
            return f"doi:{self.doi}"
        return f"src:{self.source}:{self.source_id}"


@dataclass
class Summary:
    approach: str
    result: str
    novelty: str
    relevance: str
    why_relevant_axes: list[str] = field(default_factory=list)


@dataclass
class ClassicEntry:
    title: str
    note: str
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    id: int | None = None
    rank: int = 0
    status: str = "pending"  # "pending" | "shown"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/litreview/models.py tests/test_models.py
git commit -m "feat: domain models (Candidate, Summary, ClassicEntry)"
```

---

### Task 3: Archive (SQLite persistence layer)

**Files:**
- Create: `src/litreview/schema.sql`, `src/litreview/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `Candidate`, `Summary`, `ClassicEntry` from Task 2.
- Produces `litreview.archive.Archive` with:
  - `__init__(self, path: str)` and `initialize(self) -> None` (idempotent DDL run).
  - `filter_new(self, candidates: list[Candidate]) -> list[Candidate]` — drop candidates whose `dedup_key()` already exists in `papers`.
  - `last_successful_run_date(self) -> datetime.date | None`.
  - `create_run(self) -> int`.
  - `finish_run(self, run_id: int, n_candidates: int, n_selected: int, status: str, error: str | None = None) -> None`.
  - `store_selection(self, run_id: int, items: list[tuple[Candidate, Summary]]) -> None` — one transaction; inserts each paper + its summary (`status="unread"`); flips matching classics to `shown`.
  - `add_classics(self, entries: list[ClassicEntry]) -> None`.
  - `pending_classics(self, limit: int) -> list[ClassicEntry]` — ordered by `rank`.
  - `unread_summaries(self) -> list[dict]` and `archived_summaries(self, query: str | None = None) -> list[dict]` — each dict has paper + summary fields incl. `summary_id`.
  - `mark_read(self, summary_id: int) -> None`, `mark_all_read(self) -> None`, `set_rating(self, summary_id: int, rating: int) -> None`.
  - `last_run(self) -> dict | None`.
  - Dedup key stored in `papers.dedup_key` (unique); classic-vs-fresh via `papers.kind`.

- [ ] **Step 1: Create `src/litreview/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    n_candidates  INTEGER,
    n_selected    INTEGER,
    status        TEXT NOT NULL DEFAULT 'running',  -- running|ok|error
    error         TEXT
);

CREATE TABLE IF NOT EXISTS papers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key          TEXT NOT NULL UNIQUE,
    doi                TEXT,
    source             TEXT NOT NULL,
    source_id          TEXT NOT NULL,
    title              TEXT NOT NULL,
    authors            TEXT NOT NULL DEFAULT '[]',   -- JSON array
    venue              TEXT,
    published_date     TEXT,
    abstract           TEXT,
    url                TEXT,
    is_oa              INTEGER NOT NULL DEFAULT 0,
    kind               TEXT NOT NULL DEFAULT 'fresh',
    first_surfaced_run INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS summaries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id          INTEGER NOT NULL REFERENCES papers(id),
    approach          TEXT NOT NULL,
    result            TEXT NOT NULL,
    novelty           TEXT NOT NULL,
    relevance         TEXT NOT NULL,
    why_relevant_axes TEXT NOT NULL DEFAULT '[]',    -- JSON array
    status            TEXT NOT NULL DEFAULT 'unread', -- unread|read
    read_at           TEXT,
    rating            INTEGER                          -- reserved; unused in v1
);

CREATE TABLE IF NOT EXISTS classics (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title   TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    doi     TEXT,
    note    TEXT NOT NULL DEFAULT '',
    rank    INTEGER NOT NULL DEFAULT 0,
    status  TEXT NOT NULL DEFAULT 'pending'  -- pending|shown
);
```

- [ ] **Step 2: Write the failing test** — `tests/test_archive.py`

```python
import datetime
import pytest
from litreview.archive import Archive
from litreview.models import Candidate, Summary, ClassicEntry


@pytest.fixture
def archive(tmp_path):
    a = Archive(str(tmp_path / "test.db"))
    a.initialize()
    return a


def _cand(source_id, doi=None, kind="fresh", title="t"):
    return Candidate(source="openalex", source_id=source_id, title=title,
                     authors=["A. Author"], doi=doi, kind=kind)


def test_filter_new_excludes_stored_papers(archive):
    run = archive.create_run()
    c1 = _cand("W1", doi="10.1/a")
    archive.store_selection(run, [(c1, Summary("a", "r", "n", "v", ["domain"]))])
    c1_again = _cand("W1", doi="10.1/a")
    c2 = _cand("W2", doi="10.1/b")
    new = archive.filter_new([c1_again, c2])
    assert [c.source_id for c in new] == ["W2"]


def test_filter_new_dedups_by_source_id_when_no_doi(archive):
    run = archive.create_run()
    c = _cand("W3")
    archive.store_selection(run, [(c, Summary("a", "r", "n", "v", []))])
    assert archive.filter_new([_cand("W3")]) == []


def test_store_and_read_unread_summaries(archive):
    run = archive.create_run()
    c = _cand("W1", doi="10.1/a", title="Cool paper")
    archive.store_selection(run, [(c, Summary("appr", "res", "nov", "rel", ["portable_ml"]))])
    unread = archive.unread_summaries()
    assert len(unread) == 1
    row = unread[0]
    assert row["title"] == "Cool paper"
    assert row["approach"] == "appr"
    assert row["why_relevant_axes"] == ["portable_ml"]
    assert row["status"] == "unread"


def test_mark_read_moves_to_archive(archive):
    run = archive.create_run()
    c = _cand("W1", doi="10.1/a", title="Readme")
    archive.store_selection(run, [(c, Summary("a", "r", "n", "v", []))])
    sid = archive.unread_summaries()[0]["summary_id"]
    archive.mark_read(sid)
    assert archive.unread_summaries() == []
    arch = archive.archived_summaries()
    assert [r["title"] for r in arch] == ["Readme"]


def test_archived_search(archive):
    run = archive.create_run()
    archive.store_selection(run, [
        (_cand("W1", doi="10.1/a", title="Proteomics advances"), Summary("a", "r", "n", "v", [])),
        (_cand("W2", doi="10.1/b", title="Genomics review"), Summary("a", "r", "n", "v", [])),
    ])
    for r in archive.unread_summaries():
        archive.mark_read(r["summary_id"])
    hits = archive.archived_summaries(query="proteomics")
    assert [r["title"] for r in hits] == ["Proteomics advances"]


def test_set_rating(archive):
    run = archive.create_run()
    archive.store_selection(run, [(_cand("W1", doi="10.1/a"), Summary("a", "r", "n", "v", []))])
    sid = archive.unread_summaries()[0]["summary_id"]
    archive.set_rating(sid, 4)  # stored but unused in v1


def test_classics_lifecycle(archive):
    archive.add_classics([
        ClassicEntry(title="Foundational A", note="must read", rank=1),
        ClassicEntry(title="Foundational B", note="must read", rank=2),
    ])
    pending = archive.pending_classics(limit=1)
    assert [e.title for e in pending] == ["Foundational A"]


def test_store_selection_flips_matching_classic(archive):
    archive.add_classics([ClassicEntry(title="Foundational A", note="x", doi="10.1/classic", rank=1)])
    run = archive.create_run()
    c = _cand("Wc", doi="10.1/classic", kind="classic", title="Foundational A")
    archive.store_selection(run, [(c, Summary("a", "r", "n", "v", []))])
    assert archive.pending_classics(limit=10) == []


def test_last_successful_run_date(archive):
    assert archive.last_successful_run_date() is None
    run = archive.create_run()
    archive.finish_run(run, n_candidates=10, n_selected=3, status="ok")
    assert archive.last_successful_run_date() == datetime.date.today()


def test_run_failure_is_recorded(archive):
    run = archive.create_run()
    archive.finish_run(run, n_candidates=0, n_selected=0, status="error", error="boom")
    last = archive.last_run()
    assert last["status"] == "error"
    assert last["error"] == "boom"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.archive'`

- [ ] **Step 4: Implement `src/litreview/archive.py`**

```python
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
                    "relevance, why_relevant_axes, status) "
                    "VALUES (?,?,?,?,?,?, 'unread')",
                    (
                        paper_id, summ.approach, summ.result, summ.novelty,
                        summ.relevance, json.dumps(summ.why_relevant_axes),
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
        "s.why_relevant_axes, s.status, s.read_at, s.rating, "
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_archive.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git add src/litreview/schema.sql src/litreview/archive.py tests/test_archive.py
git commit -m "feat: SQLite archive (dedup, atomic store, read-state, classics)"
```

---

### Task 4: PaperSource protocol + OpenAlex source

**Files:**
- Create: `src/litreview/sources/__init__.py`, `src/litreview/sources/base.py`, `src/litreview/sources/openalex.py`, `tests/fixtures/openalex_works.json`
- Test: `tests/test_sources_openalex.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2), `Profile` (Task 1).
- Produces:
  - `litreview.sources.base.PaperSource` (typing.Protocol): attribute `name: str`; method `fetch(self, query: str, since: datetime.date | None) -> list[Candidate]`.
  - `litreview.sources.openalex.OpenAlexSource(config: dict)` implementing it, with `name = "openalex"`. Accepts an injected `client` (an object with `.get(url, params=...) -> httpx.Response`) defaulting to a module-level `httpx.Client`, so tests inject a fake.
  - `litreview.sources.build_sources(profile: Profile) -> list[PaperSource]` — instantiates enabled sources from `SOURCES` registry; unknown names raise `ValueError`.
  - Module dict `SOURCES: dict[str, type]`.

- [ ] **Step 1: Create `tests/fixtures/openalex_works.json`** (trimmed real OpenAlex `/works` shape)

```json
{
  "results": [
    {
      "id": "https://openalex.org/W123",
      "doi": "https://doi.org/10.1234/abc",
      "title": "A DIA-MS method for fast proteomics",
      "publication_date": "2026-07-01",
      "authorships": [
        {"author": {"display_name": "Jane Roe"}},
        {"author": {"display_name": "John Doe"}}
      ],
      "primary_location": {"source": {"display_name": "Nature Methods"}},
      "open_access": {"is_oa": true},
      "abstract_inverted_index": {"Fast": [0], "proteomics": [1], "method.": [2]}
    },
    {
      "id": "https://openalex.org/W124",
      "doi": null,
      "title": "No-DOI preprint",
      "publication_date": "2026-06-15",
      "authorships": [{"author": {"display_name": "A. Nonymous"}}],
      "primary_location": {"source": null},
      "open_access": {"is_oa": false},
      "abstract_inverted_index": null
    }
  ]
}
```

- [ ] **Step 2: Write the failing test** — `tests/test_sources_openalex.py`

```python
import datetime
import json
import pathlib
from litreview.sources.openalex import OpenAlexSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "openalex_works.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self._payload)


def test_openalex_maps_fields_and_reconstructs_abstract():
    payload = json.loads(FIX.read_text())
    src = OpenAlexSource({"query": "proteomics"}, client=FakeClient(payload))
    cands = src.fetch("proteomics", since=datetime.date(2026, 6, 1))
    assert src.name == "openalex"
    assert len(cands) == 2
    c0 = cands[0]
    assert c0.source == "openalex"
    assert c0.source_id == "W123"
    assert c0.doi == "10.1234/abc"          # bare DOI, prefix stripped
    assert c0.title == "A DIA-MS method for fast proteomics"
    assert c0.authors == ["Jane Roe", "John Doe"]
    assert c0.venue == "Nature Methods"
    assert c0.is_oa is True
    assert c0.abstract == "Fast proteomics method."   # reconstructed from inverted index
    c1 = cands[1]
    assert c1.doi is None
    assert c1.venue is None
    assert c1.abstract is None


def test_openalex_passes_since_filter():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    src = OpenAlexSource({"query": "proteomics"}, client=fake)
    src.fetch("proteomics", since=datetime.date(2026, 6, 1))
    _, params = fake.calls[0]
    assert "from_publication_date:2026-06-01" in params["filter"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_sources_openalex.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.sources'`

- [ ] **Step 4: Create `src/litreview/sources/base.py`**

```python
from __future__ import annotations

import datetime
from typing import Protocol

from ..models import Candidate


class PaperSource(Protocol):
    name: str

    def fetch(self, query: str, since: datetime.date | None) -> list[Candidate]:
        ...
```

- [ ] **Step 5: Create `src/litreview/sources/openalex.py`**

```python
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
```

- [ ] **Step 6: Create `src/litreview/sources/__init__.py`**

```python
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
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_sources_openalex.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add src/litreview/sources/ tests/test_sources_openalex.py tests/fixtures/openalex_works.json
git commit -m "feat: PaperSource protocol + OpenAlex source"
```

---

### Task 5: PubMed source (via Europe PMC REST)

PubMed's native E-utilities return XML across two calls. Europe PMC's REST search
indexes PubMed/MEDLINE and returns JSON in one call, so we back the `"pubmed"`
source with it — same normalized `Candidate` out.

**Files:**
- Create: `src/litreview/sources/pubmed.py`, `tests/fixtures/europepmc_search.json`
- Modify: `src/litreview/sources/__init__.py` (register `"pubmed"`)
- Test: `tests/test_sources_pubmed.py`

**Interfaces:**
- Consumes: `Candidate`.
- Produces: `litreview.sources.pubmed.PubMedSource(config: dict, client=None)` with `name = "pubmed"`, implementing `PaperSource`. Registered in `SOURCES` under `"pubmed"`.

- [ ] **Step 1: Create `tests/fixtures/europepmc_search.json`** (trimmed Europe PMC `/search` shape)

```json
{
  "resultList": {
    "result": [
      {
        "id": "40000001",
        "source": "MED",
        "doi": "10.9999/pmid1",
        "title": "Targeted protein degradation in cancer",
        "authorString": "Roe J, Doe J.",
        "journalTitle": "Cell",
        "firstPublicationDate": "2026-07-02",
        "abstractText": "We describe a new PROTAC.",
        "isOpenAccess": "Y",
        "fullTextUrlList": {"fullTextUrl": [{"url": "https://europepmc.org/article/MED/40000001"}]}
      },
      {
        "id": "40000002",
        "source": "MED",
        "title": "No abstract paper",
        "authorString": "Anon A.",
        "journalTitle": "J Obscure",
        "firstPublicationDate": "2026-06-20",
        "isOpenAccess": "N"
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing test** — `tests/test_sources_pubmed.py`

```python
import datetime
import json
import pathlib
from litreview.sources.pubmed import PubMedSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "europepmc_search.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self._payload)


def test_pubmed_maps_fields():
    payload = json.loads(FIX.read_text())
    src = PubMedSource({"query": "protac"}, client=FakeClient(payload))
    cands = src.fetch("protac", since=datetime.date(2026, 6, 1))
    assert src.name == "pubmed"
    assert len(cands) == 2
    c0 = cands[0]
    assert c0.source == "pubmed"
    assert c0.source_id == "40000001"
    assert c0.doi == "10.9999/pmid1"
    assert c0.authors == ["Roe J", "Doe J"]
    assert c0.venue == "Cell"
    assert c0.abstract == "We describe a new PROTAC."
    assert c0.is_oa is True
    assert c0.url == "https://europepmc.org/article/MED/40000001"
    c1 = cands[1]
    assert c1.abstract is None
    assert c1.is_oa is False


def test_pubmed_builds_date_filtered_query():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    PubMedSource({}, client=fake).fetch("protac", since=datetime.date(2026, 6, 1))
    _, params = fake.calls[0]
    assert "protac" in params["query"]
    assert "FIRST_PDATE:[2026-06-01" in params["query"]
    assert params["format"] == "json"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_sources_pubmed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.sources.pubmed'`

- [ ] **Step 4: Implement `src/litreview/sources/pubmed.py`**

```python
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
```

- [ ] **Step 5: Register the source** — modify `src/litreview/sources/__init__.py`

Add the import and registry entry:

```python
from .openalex import OpenAlexSource
from .pubmed import PubMedSource

SOURCES: dict[str, type] = {
    "openalex": OpenAlexSource,
    "pubmed": PubMedSource,
}
```

And add `"PubMedSource"` to `__all__`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_sources_pubmed.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add src/litreview/sources/pubmed.py src/litreview/sources/__init__.py tests/test_sources_pubmed.py tests/fixtures/europepmc_search.json
git commit -m "feat: PubMed source via Europe PMC REST"
```

---

### Task 6: bioRxiv source

bioRxiv's `/details` API lists preprints by date range; we filter to the
configured subject category client-side.

**Files:**
- Create: `src/litreview/sources/biorxiv.py`, `tests/fixtures/biorxiv_details.json`
- Modify: `src/litreview/sources/__init__.py` (register `"biorxiv"`)
- Test: `tests/test_sources_biorxiv.py`

**Interfaces:**
- Consumes: `Candidate`.
- Produces: `litreview.sources.biorxiv.BioRxivSource(config: dict, client=None)` with `name = "biorxiv"`, implementing `PaperSource`. Registered under `"biorxiv"`. `query` is ignored (bioRxiv has no keyword search); `config["category"]` filters results (case-insensitive); missing category means no category filter.

- [ ] **Step 1: Create `tests/fixtures/biorxiv_details.json`** (trimmed bioRxiv `/details` shape)

```json
{
  "collection": [
    {
      "doi": "10.1101/2026.07.01.500001",
      "title": "Cryo-EM of a degrader complex",
      "authors": "Roe, J.; Doe, J.",
      "category": "biochemistry",
      "date": "2026-07-01",
      "abstract": "We solved the structure.",
      "server": "biorxiv"
    },
    {
      "doi": "10.1101/2026.07.02.500002",
      "title": "A neuroscience preprint",
      "authors": "Smith, A.",
      "category": "neuroscience",
      "date": "2026-07-02",
      "abstract": "Unrelated.",
      "server": "biorxiv"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test** — `tests/test_sources_biorxiv.py`

```python
import datetime
import json
import pathlib
from litreview.sources.biorxiv import BioRxivSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "biorxiv_details.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self._payload)


def test_biorxiv_filters_by_category_and_maps_fields():
    payload = json.loads(FIX.read_text())
    src = BioRxivSource({"category": "biochemistry"}, client=FakeClient(payload))
    cands = src.fetch("ignored", since=datetime.date(2026, 7, 1))
    assert src.name == "biorxiv"
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "biorxiv"
    assert c.source_id == "10.1101/2026.07.01.500001"
    assert c.doi == "10.1101/2026.07.01.500001"
    assert c.authors == ["Roe, J.", "Doe, J."]
    assert c.abstract == "We solved the structure."
    assert c.is_oa is True     # preprints are open
    assert c.url == "https://www.biorxiv.org/content/10.1101/2026.07.01.500001"


def test_biorxiv_no_category_returns_all():
    payload = json.loads(FIX.read_text())
    src = BioRxivSource({}, client=FakeClient(payload))
    cands = src.fetch("ignored", since=datetime.date(2026, 7, 1))
    assert len(cands) == 2


def test_biorxiv_builds_dated_details_url():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    BioRxivSource({}, client=fake).fetch("x", since=datetime.date(2026, 7, 1))
    url, _ = fake.calls[0]
    assert "/details/biorxiv/2026-07-01/" in url
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_sources_biorxiv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.sources.biorxiv'`

- [ ] **Step 4: Implement `src/litreview/sources/biorxiv.py`**

```python
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
        start = (since or (datetime.date.today() - datetime.timedelta(days=7))).isoformat()
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
```

- [ ] **Step 5: Register the source** — modify `src/litreview/sources/__init__.py`

```python
from .biorxiv import BioRxivSource
from .openalex import OpenAlexSource
from .pubmed import PubMedSource

SOURCES: dict[str, type] = {
    "openalex": OpenAlexSource,
    "pubmed": PubMedSource,
    "biorxiv": BioRxivSource,
}
```

Add `"BioRxivSource"` to `__all__`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_sources_biorxiv.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/litreview/sources/biorxiv.py src/litreview/sources/__init__.py tests/test_sources_biorxiv.py tests/fixtures/biorxiv_details.json
git commit -m "feat: bioRxiv source"
```

---

### Task 7: Slot allocation + Ranker (interface, fake, Claude impl)

**Files:**
- Create: `src/litreview/llm.py`, `src/litreview/ranking.py`
- Test: `tests/test_ranking.py`

**Interfaces:**
- Consumes: `Candidate` (Task 2), `Profile` (Task 1).
- Produces:
  - `litreview.ranking.allocate_slots(picks: int, classic_fraction: float, n_classic_available: int, n_fresh_available: int) -> tuple[int, int]` returns `(classic_slots, fresh_slots)`. `classic_slots = min(round(picks * classic_fraction), n_classic_available)`; remaining slots go to fresh, capped at `n_fresh_available`; if fresh is short, unused slots go back to classic (capped again). Total never exceeds `picks` nor the combined availability.
  - `litreview.ranking.Ranker` (Protocol): `select(self, candidates: list[Candidate], profile: Profile, n: int) -> list[Candidate]` — returns up to `n` chosen from `candidates` (a subset, order = best first).
  - `litreview.ranking.FakeRanker(Ranker)`: returns `candidates[:n]` (deterministic, for tests/pipeline wiring).
  - `litreview.ranking.ClaudeRanker(Ranker)`: uses `litreview.llm.get_client()` + structured output to pick indices.
  - `litreview.llm.get_client() -> anthropic.Anthropic` and `litreview.llm.MODEL = "claude-opus-4-8"` (overridable via `LITREVIEW_MODEL` env var).

- [ ] **Step 1: Write the failing test** — `tests/test_ranking.py`

```python
from litreview.models import Candidate
from litreview.ranking import allocate_slots, FakeRanker


def _c(i, kind="fresh"):
    return Candidate(source="s", source_id=f"W{i}", title=f"t{i}", authors=[], kind=kind)


def test_allocate_standard_30_70():
    assert allocate_slots(5, 0.30, n_classic_available=10, n_fresh_available=10) == (2, 3)


def test_allocate_reallocates_when_classics_exhausted():
    # no classics available -> all slots go to fresh
    assert allocate_slots(5, 0.30, n_classic_available=0, n_fresh_available=10) == (0, 5)


def test_allocate_reallocates_when_fresh_short():
    # only 1 fresh available -> its 3 fresh slots shrink; spare goes to classics (capped)
    c, f = allocate_slots(5, 0.30, n_classic_available=10, n_fresh_available=1)
    assert f == 1
    assert c == 4
    assert c + f == 5


def test_allocate_never_exceeds_availability():
    c, f = allocate_slots(5, 0.30, n_classic_available=1, n_fresh_available=1)
    assert (c, f) == (1, 1)


def test_fake_ranker_takes_first_n():
    cands = [_c(i) for i in range(5)]
    picked = FakeRanker().select(cands, profile=None, n=2)
    assert [c.source_id for c in picked] == ["W0", "W1"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_ranking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.ranking'`

- [ ] **Step 3: Implement `src/litreview/llm.py`**

```python
from __future__ import annotations

import os

import anthropic

MODEL = os.environ.get("LITREVIEW_MODEL", "claude-opus-4-8")


def get_client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY (or an `ant auth login` profile) from the env.
    return anthropic.Anthropic()
```

- [ ] **Step 4: Implement `src/litreview/ranking.py`**

```python
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
            f"[{i}] {c.title}\n    {(c.abstract or '')[:600]}"
            for i, c in enumerate(candidates)
        )
        system = (
            "You select the most relevant scientific papers for a specific "
            "researcher. Return only indices, best first."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n"
            f"Portable-ML interest: {profile.portable_ml}\n\n"
            f"Pick the {n} best of these {len(candidates)} candidates. "
            f"Return their 0-based indices, best first, at most {n}.\n\n"
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
        chosen = msg.parsed_output.indices[:n]
        return [candidates[i] for i in chosen if 0 <= i < len(candidates)]
```

Add `pydantic>=2` to `pyproject.toml` `dependencies` (the `anthropic` SDK already
pulls it in, but declare it explicitly).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_ranking.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/litreview/llm.py src/litreview/ranking.py tests/test_ranking.py pyproject.toml
git commit -m "feat: slot allocation + Ranker (fake + Claude)"
```

---

### Task 8: Summarizer (interface, fake, Claude impl)

**Files:**
- Create: `src/litreview/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `Candidate`, `Summary` (Task 2), `Profile` (Task 1), `litreview.llm` (Task 7).
- Produces:
  - `litreview.summarize.Summarizer` (Protocol): `summarize(self, candidate: Candidate, profile: Profile) -> Summary`.
  - `litreview.summarize.FakeSummarizer`: returns a deterministic `Summary` echoing the title (for tests/pipeline).
  - `litreview.summarize.ClaudeSummarizer`: structured output producing the four fields + axes; uses `candidate.full_text` when present, else `abstract`.

- [ ] **Step 1: Write the failing test** — `tests/test_summarize.py`

```python
from litreview.models import Candidate
from litreview.summarize import FakeSummarizer


def test_fake_summarizer_returns_summary():
    c = Candidate(source="s", source_id="W1", title="Cool Paper", authors=[],
                  abstract="We did science.")
    s = FakeSummarizer().summarize(c, profile=None)
    assert s.approach
    assert "Cool Paper" in s.relevance
    assert isinstance(s.why_relevant_axes, list)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.summarize'`

- [ ] **Step 3: Implement `src/litreview/summarize.py`**

```python
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from .config import Profile
from .llm import MODEL, get_client
from .models import Candidate, Summary


class Summarizer(Protocol):
    def summarize(self, candidate: Candidate, profile: Profile) -> Summary:
        ...


class FakeSummarizer:
    def summarize(self, candidate: Candidate, profile) -> Summary:
        return Summary(
            approach=f"Approach of {candidate.title}.",
            result="Key result.",
            novelty="Why it is novel.",
            relevance=f"Why {candidate.title} is relevant to you.",
            why_relevant_axes=["domain"],
        )


class _SummaryOut(BaseModel):
    approach: str
    result: str
    novelty: str
    relevance: str
    why_relevant_axes: list[str]


class ClaudeSummarizer:
    def __init__(self, client=None) -> None:
        self._client = client or get_client()

    def summarize(self, candidate: Candidate, profile: Profile) -> Summary:
        body = candidate.full_text or candidate.abstract or "(no abstract available)"
        system = (
            "You summarize a scientific paper for a specific researcher. Be "
            "concrete and concise. 'relevance' must explain why THIS researcher "
            "should care. 'why_relevant_axes' is a subset of "
            "['domain', 'portable_ml', 'classic']."
        )
        prompt = (
            f"Researcher profile:\n{profile.description}\n"
            f"Domain focus: {', '.join(profile.domain_focus)}\n"
            f"Portable-ML interest: {profile.portable_ml}\n\n"
            f"Paper title: {candidate.title}\n"
            f"Venue: {candidate.venue or 'unknown'}\n"
            f"Kind: {candidate.kind}\n"
            f"Content:\n{body[:6000]}"
        )
        msg = self._client.messages.parse(
            model=MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=_SummaryOut,
        )
        out = msg.parsed_output
        return Summary(
            approach=out.approach,
            result=out.result,
            novelty=out.novelty,
            relevance=out.relevance,
            why_relevant_axes=out.why_relevant_axes,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_summarize.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/litreview/summarize.py tests/test_summarize.py
git commit -m "feat: Summarizer (fake + Claude)"
```

---

### Task 9: Pipeline orchestration

**Files:**
- Create: `src/litreview/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Profile`, `Archive`, `PaperSource` list, `Ranker`, `Summarizer`, `allocate_slots`, `Candidate`, `ClassicEntry`.
- Produces `litreview.pipeline.Pipeline`:
  - `__init__(self, profile, archive, sources, ranker, summarizer)`.
  - `run(self) -> dict` — executes the weekly run, returns `{"run_id", "n_candidates", "n_selected", "status"}`. Records a failed `runs` row and re-raises on unexpected error.
  - Fresh candidates = union of each source's `fetch(query, since=last_successful_run_date)`; `query` per source from `profile.sources_config[name].get("query", "")`.
  - Classic candidates come from `archive.pending_classics(limit=picks_per_run)` converted to `Candidate(kind="classic")`.
  - Dedupe both pools via `archive.filter_new`.
  - `allocate_slots(picks_per_run, classic_fraction, len(classic_pool), len(fresh_pool))`, then `ranker.select` within each pool, then `summarizer.summarize` each selected, then `archive.store_selection` + `finish_run`.

- [ ] **Step 1: Write the failing test** — `tests/test_pipeline.py`

```python
import datetime
from litreview.archive import Archive
from litreview.models import Candidate, ClassicEntry
from litreview.pipeline import Pipeline
from litreview.ranking import FakeRanker
from litreview.summarize import FakeSummarizer


class StubSource:
    def __init__(self, name, cands):
        self.name = name
        self._cands = cands
        self.seen_since = "unset"
    def fetch(self, query, since):
        self.seen_since = since
        return list(self._cands)


def _fresh(i):
    return Candidate(source="openalex", source_id=f"F{i}", title=f"Fresh {i}",
                     authors=[], doi=f"10.1/f{i}", kind="fresh",
                     abstract="abs")


def test_pipeline_selects_and_stores(profile, tmp_path):
    archive = Archive(str(tmp_path / "p.db"))
    archive.initialize()
    archive.add_classics([
        ClassicEntry(title="Classic A", note="x", doi="10.9/ca", rank=1),
        ClassicEntry(title="Classic B", note="x", doi="10.9/cb", rank=2),
    ])
    src = StubSource("openalex", [_fresh(i) for i in range(10)])
    pipe = Pipeline(profile, archive, [src], FakeRanker(), FakeSummarizer())
    result = pipe.run()

    assert result["status"] == "ok"
    assert result["n_selected"] == 5          # picks_per_run
    unread = archive.unread_summaries()
    assert len(unread) == 5
    kinds = sorted(r["kind"] for r in unread)
    assert kinds.count("classic") == 2        # 30% of 5 -> 2
    assert kinds.count("fresh") == 3


def test_pipeline_dedups_across_runs(profile, tmp_path):
    archive = Archive(str(tmp_path / "p.db"))
    archive.initialize()
    src = StubSource("openalex", [_fresh(i) for i in range(10)])
    Pipeline(profile, archive, [src], FakeRanker(), FakeSummarizer()).run()
    first = {r["title"] for r in archive.unread_summaries()}
    # second run: same source output, none of the already-surfaced papers return
    Pipeline(profile, archive, [src], FakeRanker(), FakeSummarizer()).run()
    for r in archive.unread_summaries():
        # a paper never appears in two runs
        pass
    total_titles = [r["title"] for r in archive.unread_summaries()]
    assert len(total_titles) == len(set(total_titles))


def test_pipeline_passes_last_run_date_to_sources(profile, tmp_path):
    archive = Archive(str(tmp_path / "p.db"))
    archive.initialize()
    src = StubSource("openalex", [_fresh(i) for i in range(3)])
    Pipeline(profile, archive, [src], FakeRanker(), FakeSummarizer()).run()
    # first run: no prior successful run, so since is None
    assert src.seen_since is None
    src2 = StubSource("openalex", [_fresh(i + 100) for i in range(3)])
    Pipeline(profile, archive, [src2], FakeRanker(), FakeSummarizer()).run()
    assert src2.seen_since == datetime.date.today()


def test_pipeline_records_failure(profile, tmp_path):
    archive = Archive(str(tmp_path / "p.db"))
    archive.initialize()

    class Boom:
        name = "boom"
        def fetch(self, query, since):
            raise RuntimeError("network down")

    pipe = Pipeline(profile, archive, [Boom()], FakeRanker(), FakeSummarizer())
    try:
        pipe.run()
    except RuntimeError:
        pass
    last = archive.last_run()
    assert last["status"] == "error"
    assert "network down" in last["error"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.pipeline'`

- [ ] **Step 3: Implement `src/litreview/pipeline.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–9)

- [ ] **Step 6: Commit**

```bash
git add src/litreview/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestration (fetch -> allocate -> rank -> summarize -> store)"
```

---

### Task 10: init-classics (LLM drafts the backlog)

**Files:**
- Create: `src/litreview/classics.py`
- Test: `tests/test_classics.py`

**Interfaces:**
- Consumes: `Profile`, `Archive`, `ClassicEntry`, `litreview.llm`.
- Produces:
  - `litreview.classics.ClassicsDrafter` (Protocol): `draft(self, profile: Profile, n: int) -> list[ClassicEntry]`.
  - `litreview.classics.FakeClassicsDrafter`: returns `n` deterministic entries.
  - `litreview.classics.ClaudeClassicsDrafter`: structured output producing `n` foundational papers ranked by importance.
  - `litreview.classics.init_classics(profile: Profile, archive: Archive, drafter: ClassicsDrafter, n: int = 20) -> list[ClassicEntry]` — drafts, persists via `archive.add_classics`, returns the entries (so the CLI can print them for review).

- [ ] **Step 1: Write the failing test** — `tests/test_classics.py`

```python
from litreview.archive import Archive
from litreview.classics import FakeClassicsDrafter, init_classics
from litreview.models import ClassicEntry


def test_init_classics_persists_and_returns(profile, tmp_path):
    archive = Archive(str(tmp_path / "c.db"))
    archive.initialize()
    entries = init_classics(profile, archive, FakeClassicsDrafter(), n=3)
    assert len(entries) == 3
    assert all(isinstance(e, ClassicEntry) for e in entries)
    pending = archive.pending_classics(limit=10)
    assert len(pending) == 3
    assert [e.rank for e in pending] == [1, 2, 3]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_classics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.classics'`

- [ ] **Step 3: Implement `src/litreview/classics.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_classics.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/litreview/classics.py tests/test_classics.py
git commit -m "feat: init-classics (LLM-drafted foundational backlog)"
```

---

### Task 11: Web UI (FastAPI + Jinja + htmx)

**Files:**
- Create: `src/litreview/web/__init__.py`, `src/litreview/web/app.py`, `src/litreview/web/templates/base.html`, `digest.html`, `archive.html`, `status.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `Archive` (Task 3).
- Produces: `litreview.web.app.create_app(archive: Archive) -> fastapi.FastAPI` with routes:
  - `GET /` → digest of unread summaries (200, HTML).
  - `GET /archive?q=` → archived (read) summaries, optional title search.
  - `GET /status` → last run info.
  - `POST /read/{summary_id}` → mark one read; returns empty 200 (htmx swaps the card out).
  - `POST /read-all` → mark all read; 303 redirect to `/`.
  - `POST /rate/{summary_id}` (form field `rating`) → store rating (inert in v1); empty 200.

Add `httpx` is already a dep; FastAPI's `TestClient` needs it.

- [ ] **Step 1: Write the failing test** — `tests/test_web.py`

```python
from fastapi.testclient import TestClient
from litreview.archive import Archive
from litreview.models import Candidate, Summary
from litreview.web.app import create_app


def _seed(tmp_path):
    a = Archive(str(tmp_path / "web.db"))
    a.initialize()
    run = a.create_run()
    a.store_selection(run, [
        (Candidate(source="openalex", source_id="W1", title="Proteomics breakthrough",
                   authors=["J. Roe"], doi="10.1/a", kind="fresh", is_oa=True),
         Summary("The approach.", "The result.", "The novelty.",
                 "Why it matters to you.", ["domain"])),
    ])
    a.finish_run(run, 5, 1, status="ok")
    return a


def test_digest_shows_unread(tmp_path):
    app = create_app(_seed(tmp_path))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Proteomics breakthrough" in resp.text
    assert "The novelty." in resp.text


def test_mark_read_then_appears_in_archive(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    r = client.post(f"/read/{sid}")
    assert r.status_code == 200
    assert "Proteomics breakthrough" not in client.get("/").text
    assert "Proteomics breakthrough" in client.get("/archive").text


def test_archive_search(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    client.post(f"/read/{sid}")
    assert "Proteomics breakthrough" in client.get("/archive?q=proteomics").text
    assert "Proteomics breakthrough" not in client.get("/archive?q=genomics").text


def test_status_page(tmp_path):
    app = create_app(_seed(tmp_path))
    client = TestClient(app)
    resp = client.get("/status")
    assert resp.status_code == 200
    assert "ok" in resp.text.lower()


def test_rate_is_accepted(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    r = client.post(f"/rate/{sid}", data={"rating": "4"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'litreview.web'`

- [ ] **Step 3: Create `src/litreview/web/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `src/litreview/web/app.py`**

```python
from __future__ import annotations

from importlib import resources

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..archive import Archive


def create_app(archive: Archive) -> FastAPI:
    app = FastAPI()
    tpl_dir = resources.files("litreview.web").joinpath("templates")
    templates = Jinja2Templates(directory=str(tpl_dir))

    @app.get("/", response_class=HTMLResponse)
    def digest(request: Request):
        return templates.TemplateResponse(
            request, "digest.html", {"summaries": archive.unread_summaries()}
        )

    @app.get("/archive", response_class=HTMLResponse)
    def archive_view(request: Request, q: str | None = None):
        return templates.TemplateResponse(
            request, "archive.html",
            {"summaries": archive.archived_summaries(query=q), "q": q or ""},
        )

    @app.get("/status", response_class=HTMLResponse)
    def status(request: Request):
        return templates.TemplateResponse(
            request, "status.html", {"run": archive.last_run()}
        )

    @app.post("/read/{summary_id}")
    def read(summary_id: int):
        archive.mark_read(summary_id)
        return Response(status_code=200)

    @app.post("/read-all")
    def read_all():
        archive.mark_all_read()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/rate/{summary_id}")
    def rate(summary_id: int, rating: int = Form(...)):
        archive.set_rating(summary_id, rating)  # reserved; unused in v1
        return Response(status_code=200)

    return app
```

- [ ] **Step 5: Create `src/litreview/web/templates/base.html`**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lit Review</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
    nav a { margin-right: 1rem; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 1rem 1.25rem; margin: 1rem 0; }
    .meta { color: #666; font-size: 0.85rem; }
    .badge { display: inline-block; font-size: 0.7rem; padding: 0.1rem 0.5rem; border-radius: 999px; background: #eef; margin-left: 0.4rem; }
    h3 { margin-bottom: 0.2rem; }
    .field { margin: 0.5rem 0; }
    .field b { display: block; font-size: 0.8rem; text-transform: uppercase; color: #444; }
    button { cursor: pointer; }
  </style>
</head>
<body>
  <nav>
    <a href="/">Digest</a>
    <a href="/archive">Archive</a>
    <a href="/status">Status</a>
  </nav>
  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 6: Create `src/litreview/web/templates/digest.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>This week's papers</h1>
{% if not summaries %}
  <p>Nothing unread. Check back after the next run.</p>
{% else %}
  <form method="post" action="/read-all"><button type="submit">Mark all read</button></form>
  {% for s in summaries %}
  <div class="card" id="card-{{ s.summary_id }}">
    <h3>{{ s.title }}</h3>
    <div class="meta">
      {{ s.authors | join(", ") }} · {{ s.venue or "—" }} · {{ s.published_date or "" }}
      {% if s.is_oa %}<span class="badge">open access</span>{% endif %}
      {% if s.kind == "classic" %}<span class="badge">classic</span>{% endif %}
      {% for ax in s.why_relevant_axes %}<span class="badge">{{ ax }}</span>{% endfor %}
    </div>
    <div class="field"><b>Approach</b>{{ s.approach }}</div>
    <div class="field"><b>Result</b>{{ s.result }}</div>
    <div class="field"><b>Why it's novel</b>{{ s.novelty }}</div>
    <div class="field"><b>Why it's relevant to you</b>{{ s.relevance }}</div>
    {% if s.url %}<p><a href="{{ s.url }}" target="_blank" rel="noopener">Open paper ↗</a></p>{% endif %}
    <div class="field">
      Rate:
      {% for n in [1, 2, 3, 4, 5] %}
      <button hx-post="/rate/{{ s.summary_id }}" hx-vals='{"rating": {{ n }}}' hx-swap="none">{{ n }}</button>
      {% endfor %}
    </div>
    <button hx-post="/read/{{ s.summary_id }}"
            hx-target="#card-{{ s.summary_id }}" hx-swap="outerHTML">
      Mark as read
    </button>
  </div>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Create `src/litreview/web/templates/archive.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Archive</h1>
<form method="get" action="/archive">
  <input type="text" name="q" value="{{ q }}" placeholder="search titles...">
  <button type="submit">Search</button>
</form>
{% if not summaries %}
  <p>No archived papers{% if q %} matching "{{ q }}"{% endif %}.</p>
{% else %}
  {% for s in summaries %}
  <div class="card">
    <h3>{{ s.title }}</h3>
    <div class="meta">
      {{ s.authors | join(", ") }} · {{ s.venue or "—" }} · read {{ s.read_at or "" }}
      {% for ax in s.why_relevant_axes %}<span class="badge">{{ ax }}</span>{% endfor %}
    </div>
    <div class="field"><b>Why it's relevant to you</b>{{ s.relevance }}</div>
    {% if s.url %}<p><a href="{{ s.url }}" target="_blank" rel="noopener">Open paper ↗</a></p>{% endif %}
  </div>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 8: Create `src/litreview/web/templates/status.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Status</h1>
{% if not run %}
  <p>No runs yet. Run <code>litreview run</code>.</p>
{% else %}
  <p>Last run #{{ run.id }} — <b>{{ run.status }}</b></p>
  <ul>
    <li>Started: {{ run.started_at }}</li>
    <li>Finished: {{ run.finished_at or "—" }}</li>
    <li>Candidates: {{ run.n_candidates if run.n_candidates is not none else "—" }}</li>
    <li>Selected: {{ run.n_selected if run.n_selected is not none else "—" }}</li>
    {% if run.error %}<li style="color:#b00">Error: {{ run.error }}</li>{% endif %}
  </ul>
{% endif %}
{% endblock %}
```

- [ ] **Step 9: Ensure templates ship with the package** — modify `pyproject.toml`

Add under `[tool.setuptools]`:

```toml
[tool.setuptools.package-data]
litreview = ["schema.sql", "web/templates/*.html"]
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `pytest tests/test_web.py -v`
Expected: PASS (5 tests)

- [ ] **Step 11: Commit**

```bash
git add src/litreview/web/ pyproject.toml tests/test_web.py
git commit -m "feat: web UI (digest, archive, status, mark-read, inert rating)"
```

---

### Task 12: CLI + launchd template + README

**Files:**
- Create: `src/litreview/cli.py`, `deploy/com.talus.litreview.plist.template`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces `litreview.cli.main(argv: list[str] | None = None) -> int` with subcommands:
  - `run` — build profile+archive+sources+Claude ranker/summarizer, run the pipeline, print a one-line result.
  - `status` — print `archive.last_run()`.
  - `init-classics [-n N]` — draft via `ClaudeClassicsDrafter`, persist, print the list for review.
  - `serve [--host H] [--port P]` — `uvicorn.run(create_app(archive))`.
  - Global `--profile PATH` (default `profile.toml`) and `--db PATH` (default `litreview.db`).
  - Registered as console script `litreview` (already in `pyproject.toml`).
  - CLI wiring is injectable: `run_command(args, *, ranker=None, summarizer=None, drafter=None)` so tests pass fakes.

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`

```python
import textwrap
from litreview import cli
from litreview.ranking import FakeRanker
from litreview.summarize import FakeSummarizer
from litreview.classics import FakeClassicsDrafter


def _profile_file(tmp_path):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent("""
        [identity]
        description = "proteomics DS"
        [axes]
        domain_focus = ["proteomics"]
        portable_ml = "ml"
        [schedule]
        cadence_days = 7
        picks_per_run = 3
        classic_fraction = 0.34
        [sources]
        enabled = ["openalex"]
        [sources.openalex]
        query = "proteomics"
    """))
    return p


def test_cli_init_classics_and_run(tmp_path, capsys, monkeypatch):
    prof = _profile_file(tmp_path)
    db = tmp_path / "cli.db"

    # init-classics with a fake drafter
    rc = cli.main(["--profile", str(prof), "--db", str(db), "init-classics", "-n", "3"],
                  drafter=FakeClassicsDrafter())
    assert rc == 0
    assert "Foundational Paper 1" in capsys.readouterr().out

    # run with a stub source injected via monkeypatch on build_sources
    from litreview.models import Candidate

    class StubSource:
        name = "openalex"
        def fetch(self, query, since):
            return [Candidate(source="openalex", source_id=f"W{i}", title=f"T{i}",
                              authors=[], doi=f"10.1/{i}", abstract="a")
                    for i in range(5)]

    monkeypatch.setattr(cli, "build_sources", lambda profile: [StubSource()])
    rc = cli.main(["--profile", str(prof), "--db", str(db), "run"],
                  ranker=FakeRanker(), summarizer=FakeSummarizer())
    assert rc == 0
    out = capsys.readouterr().out
    assert "selected" in out.lower()


def test_cli_status_before_any_run(tmp_path, capsys):
    prof = _profile_file(tmp_path)
    db = tmp_path / "s.db"
    rc = cli.main(["--profile", str(prof), "--db", str(db), "status"])
    assert rc == 0
    assert "no runs" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `AttributeError: module 'litreview.cli' has no attribute 'main'` (or import error)

- [ ] **Step 3: Implement `src/litreview/cli.py`**

```python
from __future__ import annotations

import argparse
import sys

from .archive import Archive
from .classics import ClaudeClassicsDrafter, init_classics
from .config import Profile
from .pipeline import Pipeline
from .ranking import ClaudeRanker
from .sources import build_sources
from .summarize import ClaudeSummarizer


def _load(args) -> tuple[Profile, Archive]:
    profile = Profile.load(args.profile)
    archive = Archive(args.db)
    archive.initialize()
    return profile, archive


def run_command(args, *, ranker=None, summarizer=None) -> int:
    profile, archive = _load(args)
    sources = build_sources(profile)
    pipe = Pipeline(
        profile, archive, sources,
        ranker or ClaudeRanker(),
        summarizer or ClaudeSummarizer(),
    )
    result = pipe.run()
    print(f"Run #{result['run_id']}: {result['n_selected']} selected "
          f"from {result['n_candidates']} candidates ({result['status']}).")
    return 0


def status_command(args) -> int:
    _, archive = _load(args)
    last = archive.last_run()
    if not last:
        print("No runs yet.")
        return 0
    print(f"Run #{last['id']} status={last['status']} "
          f"started={last['started_at']} finished={last['finished_at']} "
          f"selected={last['n_selected']}")
    if last["error"]:
        print(f"Error: {last['error']}")
    return 0


def init_classics_command(args, *, drafter=None) -> int:
    profile, archive = _load(args)
    entries = init_classics(profile, archive, drafter or ClaudeClassicsDrafter(), n=args.n)
    print(f"Drafted {len(entries)} classics (review, then edit the DB if needed):")
    for e in entries:
        print(f"  {e.rank:>2}. {e.title}"
              + (f" — {', '.join(e.authors)}" if e.authors else ""))
    return 0


def serve_command(args) -> int:
    import uvicorn
    from .web.app import create_app

    _, archive = _load(args)
    uvicorn.run(create_app(archive), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="litreview")
    p.add_argument("--profile", default="profile.toml")
    p.add_argument("--db", default="litreview.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run")
    sub.add_parser("status")

    ic = sub.add_parser("init-classics")
    ic.add_argument("-n", type=int, default=20)

    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    return p


def main(argv: list[str] | None = None, *, ranker=None, summarizer=None,
         drafter=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        return run_command(args, ranker=ranker, summarizer=summarizer)
    if args.cmd == "status":
        return status_command(args)
    if args.cmd == "init-classics":
        return init_classics_command(args, drafter=drafter)
    if args.cmd == "serve":
        return serve_command(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Create `deploy/com.talus.litreview.plist.template`**

Replace `__USER__`, `__REPO__`, and the venv path for your machine. Runs every
Monday at 07:00 local.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.talus.litreview</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/__USER__/__REPO__/.venv/bin/litreview</string>
    <string>--profile</string><string>/Users/__USER__/__REPO__/profile.toml</string>
    <string>--db</string><string>/Users/__USER__/__REPO__/litreview.db</string>
    <string>run</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>ANTHROPIC_API_KEY</key><string>__YOUR_KEY__</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/__USER__/__REPO__/litreview.log</string>
  <key>StandardErrorPath</key><string>/Users/__USER__/__REPO__/litreview.err</string>
</dict>
</plist>
```

- [ ] **Step 6: Create `README.md`**

````markdown
# litreview

A local weekly literature-review digest. Fetches relevant papers, LLM-ranks and
summarizes the best 3–6, and serves them in a local web UI you read and
acknowledge into a searchable archive.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
cp profile.example.toml profile.toml   # then edit it
litreview init-classics                # review the drafted foundational list
litreview run                          # do one run by hand
litreview serve                        # read at http://localhost:8000
```

## Commands

- `litreview run` — one weekly execution (fetch → rank → summarize → store)
- `litreview serve` — start the web UI
- `litreview status` — last run + any error
- `litreview init-classics [-n N]` — draft the foundational-paper backlog

Global flags: `--profile PATH` (default `profile.toml`), `--db PATH`
(default `litreview.db`).

## Weekly scheduling (macOS)

Copy `deploy/com.talus.litreview.plist.template`, fill in the placeholders, save
to `~/Library/LaunchAgents/com.talus.litreview.plist`, then:

```bash
launchctl load ~/Library/LaunchAgents/com.talus.litreview.plist
```

Your Mac must be awake at the scheduled time (or the job runs at next wake).
Linux users: run `litreview run` from a weekly cron entry instead.

## Configuration

Everything personal lives in `profile.toml` (git-ignored). See
`profile.example.toml` for the full shape: your research description, the
domain/portable-ML axes, cadence, and per-source query settings.

## Cost

~$0.20–0.55 per weekly run on current Claude pricing. Set `LITREVIEW_MODEL` to
override the default model (`claude-opus-4-8`).

## Tests

```bash
pip install -e ".[dev]"
pytest
```
````

- [ ] **Step 7: Run the whole suite**

Run: `pytest -v`
Expected: PASS (all tests, Tasks 1–12)

- [ ] **Step 8: Commit**

```bash
git add src/litreview/cli.py deploy/com.talus.litreview.plist.template README.md tests/test_cli.py
git commit -m "feat: CLI (run/status/init-classics/serve) + launchd template + README"
```

---

### Task 13: End-to-end smoke test (optional live) + final verification

**Files:**
- Create: `tests/test_smoke_live.py`
- Test: itself (skipped unless a flag is set)

**Interfaces:**
- Consumes: real `OpenAlexSource`, `ClaudeRanker`, `ClaudeSummarizer`, `Pipeline`.
- Produces: a single opt-in test that exercises the real network + real API so you can eyeball output. Skipped by default so the suite stays offline/free.

- [ ] **Step 1: Create `tests/test_smoke_live.py`**

```python
import os
import textwrap
import pytest
from litreview.archive import Archive
from litreview.config import Profile
from litreview.pipeline import Pipeline
from litreview.ranking import ClaudeRanker
from litreview.sources.openalex import OpenAlexSource
from litreview.summarize import ClaudeSummarizer


@pytest.mark.skipif(
    os.environ.get("LITREVIEW_LIVE") != "1",
    reason="set LITREVIEW_LIVE=1 (and ANTHROPIC_API_KEY) to run the live smoke test",
)
def test_live_end_to_end(tmp_path):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent("""
        [identity]
        description = "I work on proteomics and ML for mass spectrometry."
        [axes]
        domain_focus = ["proteomics", "mass spectrometry"]
        portable_ml = "ML methods relevant to proteomics."
        [schedule]
        cadence_days = 7
        picks_per_run = 3
        classic_fraction = 0.0
        [sources]
        enabled = ["openalex"]
        [sources.openalex]
        query = "proteomics deep learning"
    """))
    profile = Profile.load(p)
    archive = Archive(str(tmp_path / "live.db"))
    archive.initialize()
    pipe = Pipeline(profile, archive, [OpenAlexSource(profile.sources_config["openalex"])],
                    ClaudeRanker(), ClaudeSummarizer())
    result = pipe.run()
    assert result["status"] == "ok"
    assert result["n_selected"] >= 1
    for row in archive.unread_summaries():
        print("\n===", row["title"])
        print("APPROACH:", row["approach"])
        print("RELEVANCE:", row["relevance"])
```

- [ ] **Step 2: Verify it is skipped by default**

Run: `pytest tests/test_smoke_live.py -v`
Expected: SKIPPED (1 skipped)

- [ ] **Step 3: (Manual, optional) run it live once**

Run: `LITREVIEW_LIVE=1 ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_smoke_live.py -v -s`
Expected: PASS, with printed summaries you can eyeball for quality.

- [ ] **Step 4: Full offline suite green**

Run: `pytest -v`
Expected: PASS (all offline tests), 1 skipped (live smoke).

- [ ] **Step 5: Drive the real UI once (manual)**

Run: `litreview serve` → open `http://localhost:8000`, confirm the digest renders
(after a `litreview run`), "Mark as read" removes a card, and `/archive` shows it.

- [ ] **Step 6: Commit**

```bash
git add tests/test_smoke_live.py
git commit -m "test: opt-in live end-to-end smoke test"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- Purpose / weekly digest → Task 9 (Pipeline), Task 12 (`run`).
- Relevance = NL profile → Task 1 (Profile), Tasks 7/8 (prompts read `description`, axes).
- Two axes + 30/70 classics → Task 7 (`allocate_slots`), Task 9 (bucketed selection), Task 10 (classics), spec's "enforced in code" honored.
- Classics exhaust → 100% fresh → `allocate_slots` returns `(0, picks)` when no classics (Task 7 test `test_allocate_reallocates_when_classics_exhausted`).
- Dedup by DOI/source_id, never re-recommend → Task 2 (`dedup_key`), Task 3 (`filter_new`), Task 9 test.
- Data model (papers/summaries/runs/classics + reserved rating) → Task 3.
- Atomic store → Task 3 (`store_selection` single transaction).
- Two judgment points behind interfaces, swappable model → Tasks 7, 8; `LITREVIEW_MODEL`.
- PaperSource extensibility + `full_text` field + per-source config/creds → Task 2 (`full_text`), Task 4 (registry/build_sources), Task 8 (uses `full_text`), Task 1 (`sources_config`).
- Sources: OpenAlex, PubMed, bioRxiv → Tasks 4, 5, 6.
- Web UI: digest, archive+search, mark-read, status, inert rating → Task 11.
- CLI: run/serve/status/init-classics → Task 12.
- Setup/sharing + launchd + profile.example → Tasks 1, 12.
- Testing strategy (fixtures + fakes, offline; opt-in live) → Tasks 4–6 (fixtures), 7–9 (fakes), 13 (live).
- Cost note, default Opus 4.8 → Global Constraints, Task 7 (`llm.py`).

**Placeholder scan:** none — every code step has complete content; no "TBD"/"similar to Task N".

**Type consistency:** `Candidate`/`Summary`/`ClassicEntry` fields used identically across Tasks 2–13; `Archive` method names match between Task 3 definitions and Tasks 9/11/12 call sites; `Ranker.select(candidates, profile, n)` and `Summarizer.summarize(candidate, profile)` signatures consistent in Tasks 7/8/9; `allocate_slots` signature consistent Task 7 ↔ Task 9; `create_app(archive)` consistent Task 11 ↔ Task 12.

**Note carried from spec:** paid/institutional (.edu) sources are an explicit future extension — the `PaperSource` protocol, `sources_config` credential slots, and `Candidate.full_text` are the seams; no task builds a paid source (YAGNI for v1).
