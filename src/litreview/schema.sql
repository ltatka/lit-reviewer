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
