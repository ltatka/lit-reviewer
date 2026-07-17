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


def test_store_and_read_eli12(archive):
    run = archive.create_run()
    c = _cand("W1", doi="10.1/a", title="Kid friendly paper")
    archive.store_selection(run, [
        (c, Summary("appr", "res", "nov", "rel", ["domain"], eli12="kid friendly")),
    ])
    assert archive.unread_summaries()[0]["eli12"] == "kid friendly"


def test_initialize_migrates_old_db_missing_eli12_column(tmp_path):
    old_ddl = """
    CREATE TABLE runs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at    TEXT NOT NULL,
        finished_at   TEXT,
        n_candidates  INTEGER,
        n_selected    INTEGER,
        status        TEXT NOT NULL DEFAULT 'running',
        error         TEXT
    );
    CREATE TABLE papers (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        dedup_key          TEXT NOT NULL UNIQUE,
        doi                TEXT,
        source             TEXT NOT NULL,
        source_id          TEXT NOT NULL,
        title              TEXT NOT NULL,
        authors            TEXT NOT NULL DEFAULT '[]',
        venue              TEXT,
        published_date     TEXT,
        abstract           TEXT,
        url                TEXT,
        is_oa              INTEGER NOT NULL DEFAULT 0,
        kind               TEXT NOT NULL DEFAULT 'fresh',
        first_surfaced_run INTEGER REFERENCES runs(id)
    );
    CREATE TABLE summaries (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id          INTEGER NOT NULL REFERENCES papers(id),
        approach          TEXT NOT NULL,
        result            TEXT NOT NULL,
        novelty           TEXT NOT NULL,
        relevance         TEXT NOT NULL,
        why_relevant_axes TEXT NOT NULL DEFAULT '[]',
        status            TEXT NOT NULL DEFAULT 'unread',
        read_at           TEXT,
        rating            INTEGER
    );
    CREATE TABLE classics (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        title   TEXT NOT NULL,
        authors TEXT NOT NULL DEFAULT '[]',
        doi     TEXT,
        note    TEXT NOT NULL DEFAULT '',
        rank    INTEGER NOT NULL DEFAULT 0,
        status  TEXT NOT NULL DEFAULT 'pending'
    );
    """
    import sqlite3
    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(old_ddl)
    conn.commit()
    conn.close()

    a = Archive(db_path)
    a.initialize()

    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(summaries)")}
    conn.close()
    assert "eli12" in cols


def test_set_rating(archive):
    run = archive.create_run()
    archive.store_selection(run, [(_cand("W1", doi="10.1/a"), Summary("a", "r", "n", "v", []))])
    sid = archive.unread_summaries()[0]["summary_id"]
    archive.set_rating(sid, 4)  # stored but unused in v1
    assert archive.unread_summaries()[0]["rating"] == 4


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
