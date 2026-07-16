# Personal Literature Review App — Design

**Date:** 2026-07-16
**Status:** Approved design, pre-implementation
**Author:** Lillian (ltatka@talus.bio) with Claude

## Purpose

A local app that keeps me current with scientific literature in my field. On a
weekly cadence it searches the internet for relevant papers, picks the best 3–6,
and writes a structured summary of each (approach, result, why it's novel, why
it's relevant to me). I read the summaries and acknowledge them; acknowledged
papers move to an archive so (a) the same paper is never recommended twice and
(b) I can refer back to past summaries.

The goal is **broad exposure and building a knowledge base** — not exhaustive
coverage. Determinism is explicitly a non-goal.

## Users & sharing

Single-user, runs locally. "Shareable" means **among Talus coworkers**: each
runs their own local instance, with the same access I have (Anthropic API creds,
paid Claude plans, claude.ai connectors). Design implication: **nothing personal
or machine-specific lives in code** — all of it lives in a per-user config file.
No multi-tenant service is in scope; the design merely must not preclude one.

## Key decisions

- **Cadence:** weekly (better result quality than daily).
- **Relevance model:** a natural-language description of my interests in a config
  file, interpreted by the LLM each run (option C/D from brainstorming).
- **Two axes for "best":**
  - classic/foundational ↔ cutting-edge/preprint
  - domain-specific (proteomics, drug discovery, virtual cell, …) ↔ broadly cool
    ML/AI that could port into the field
- **Classics handling:** a finite, LLM-drafted (human-approved) backlog of
  foundational papers. Each weekly batch is ~30% classics / 70% cutting-edge,
  draining the backlog over time. When the backlog is exhausted, runs become 100%
  fresh feed — the app transitions from "catch me up" to "keep me current."
- **Feedback loop:** reserved in the data model (a `rating` column), inert in v1.
- **Dedup:** by DOI, with `source_id` as fallback when DOI is absent.

## Architecture

Approach: **explicit deterministic pipeline with the LLM injected at exactly two
judgment points.** Chosen over a free-roaming agent (less predictable, harder to
test, more of a black box) and over an MCP-server + headless-Claude-Code design
(depends on a personal Claude Code login → not cleanly shareable).

```
launchd (weekly) ─► litreview run ─► Pipeline
                                      ├─ Profile (profile.toml)
                                      ├─ PaperSource× (OpenAlex / PubMed / bioRxiv)   [det]
                                      ├─ Archive (SQLite: papers/summaries/runs/classics)  [det]
                                      ├─ Ranker (Claude, structured output)          [judgment]
                                      └─ Summarizer (Claude, structured output)      [judgment]
you ─► litreview serve ─► FastAPI/Jinja/htmx ─► reads Archive ─► read / acknowledge / (future) rating
```

The deterministic spine:

```
[det] fetch candidates → [det] dedupe/filter vs archive → [JUDGMENT] rank & pick 3–6
    → [JUDGMENT] summarize each → [det] store → [det] web UI reads DB
```

Only the two `[JUDGMENT]` boxes are non-deterministic, and that is intentional —
hardcoding a relevance score is exactly what makes lit-alert tools bad.

## Tech stack

- **Python** throughout (the team's native language).
- **SQLite** single file (`litreview.db`) — zero-config, portable.
- **FastAPI + Jinja templates + a little htmx** for the local web UI — minimal JS,
  minimal deps.
- **Anthropic Python SDK** with **structured outputs** for the two judgment steps.
  - Default model: **Claude Opus 4.8** (`claude-opus-4-8`) — relevance judgment
    and summary quality are the product; cost is negligible at this volume.
  - The `Summarizer`/`Ranker` sit behind an interface so the model (or a local
    model) is swappable. A reasonable cost optimization later: rank with Sonnet 5,
    summarize with Opus 4.8.
- **Scheduling lives outside the app.** The app exposes `litreview run`; a macOS
  `launchd` job (documented plist template, not baked in) calls it weekly. Keeps
  the core OS-agnostic. "Background" = scheduled, not a 24/7 daemon; the machine
  must be awake at run time (or the job runs at next wake).
- **Auth:** each user sets their own `ANTHROPIC_API_KEY`. No separate key sharing.

### Cost (current pricing, for reference)

Per weekly run ≈ 50K input + 12K output tokens → **~$0.55 on Opus 4.8**
(~$29/yr), **~$0.22 on Sonnet 5**. Prod cost is negligible. Development (heavy
iteration) stays in the low tens of dollars and is minimized by caching fetched
abstracts to disk and saving a few LLM responses as fixtures.

## Components

Each is a small unit with one responsibility, swappable via interface.

| Component | Responsibility | Depends on |
|---|---|---|
| `Profile` | Load per-user config (NL description, axes, classics settings, cadence, sources + credentials) | `profile.toml` |
| `PaperSource` (interface) + impls (`OpenAlexSource`, `PubMedSource`, `BioRxivSource`) | Given a query + since-date, return normalized candidate papers | public HTTP APIs |
| `Archive` (DB layer) | Store papers/summaries/runs/classics; answer "seen this DOI?"; manage read-state and (reserved) ratings | SQLite |
| `Ranker` | **[judgment]** Given candidates + profile + per-bucket slot counts, pick the best within each bucket | Anthropic SDK |
| `Summarizer` | **[judgment]** Given a chosen paper, write approach/result/novelty/relevance | Anthropic SDK |
| `Pipeline` | Orchestrate: fetch → dedupe/filter → allocate slots → rank → summarize → store | all of the above |
| `WebApp` | Read the DB; render digest + archive; handle mark-as-read and (future) rating | `Archive` |

### `PaperSource` contract & extensibility

The interface is the deliberate extension seam. Adding a source later is additive:
implement the interface, register it, add its name to `[sources] enabled`.
Everything downstream is unchanged because it only ever sees the normalized
candidate shape.

Normalized candidate fields: `doi?`, `source_id`, `title`, `authors`, `venue`,
`published_date`, `abstract`, `url`, `is_oa`, `full_text?`.

- `full_text?` is optional and unused by v1's open sources, but present so a
  future licensed source can supply full text; `Summarizer` uses it when present
  and falls back to the abstract otherwise.
- Per-source credentials live in `[sources.<name>]` in `profile.toml` and/or env
  vars — never in code.

## Data model (SQLite)

**`papers`** — the archive and dedup ledger; one row per paper ever surfaced.

| column | notes |
|---|---|
| `id` | PK |
| `doi` | nullable, **unique** — primary dedup key |
| `source_id` | fallback dedup key when DOI absent |
| `title`, `authors`, `venue`, `published_date`, `abstract`, `url`, `is_oa` | fetched metadata |
| `kind` | `classic` \| `fresh` |
| `first_surfaced_run` | FK → `runs.id` |

**`summaries`** — one row per summarized paper (the 3–6 per run).

| column | notes |
|---|---|
| `paper_id` | FK → `papers.id` |
| `approach`, `result`, `novelty`, `relevance` | the four LLM-written fields |
| `why_relevant_axes` | which quadrant(s) it hit |
| `status` | `unread` → `read` |
| `read_at` | set on acknowledge |
| `rating` | nullable int — **reserved for future feedback loop, unused in v1** |

**`runs`** — one row per weekly execution (audit + failure visibility).

| column | notes |
|---|---|
| `id`, `started_at`, `finished_at` | |
| `n_candidates`, `n_selected` | counts |
| `status`, `error` | a failed run is visible, not silent |

**`classics`** — the finite foundational-paper backlog.

| column | notes |
|---|---|
| `id`, `title`, `authors?`, `doi?`, `note` | drafted by LLM, editable by user |
| `rank` | ordering for draining |
| `status` | `pending` → `shown` |

## The weekly run (`litreview run`)

```
1. [det] Load profile.
2. [det] Fetch candidates:
        • fresh:   each enabled source, published since last successful run's date
        • classic: next `pending` items from the classics backlog
3. [det] Dedupe by DOI (source_id fallback); drop anything already in `papers`.
4. [det] Allocate slots: e.g. 5 picks × 30% ≈ 2 classic + 3 fresh
         (round sensibly; if a bucket is short, reallocate to the other).
5. [JUDGMENT] Ranker picks the best within each bucket.
6. [JUDGMENT] Summarizer writes the four fields per selected paper.
7. [det] Write papers + summaries (status=unread) + classics status flips
         + a `runs` row. Papers enter the archive only once summarized & stored,
         so a mid-run crash does not poison dedup with never-seen papers.
```

- **The 30/70 split is enforced in deterministic code**, not left to the LLM. Code
  decides bucket sizes; the LLM picks the best *within* each bucket.
- **When the classics backlog is empty**, the classic fraction is effectively 0 and
  every run is 100% fresh feed.

## Profile & classics mechanism

`profile.toml` (TOML: comments, multi-line strings). Example:

```toml
[identity]
description = """
I'm a data scientist at Talus working on proteomics / TF-focused drug
discovery — DIA mass spec, targeted protein degradation, ML for proteomics.
I also want exposure to broadly cool ML/AI that could port into our field,
and general things a data-science professional should know about.
"""

[axes]
domain_focus = ["proteomics", "targeted protein degradation", "DIA-MS"]
portable_ml  = "New ML/AI methods that could plausibly transfer to proteomics, or that a DS professional should know."

[schedule]
cadence_days     = 7
picks_per_run    = 5
classic_fraction = 0.30

[sources]
enabled = ["openalex", "pubmed", "biorxiv"]
# per-source query terms / categories and credentials in [sources.<name>]
```

**Classics backlog lifecycle:**

- `litreview init-classics` — LLM drafts a ranked foundational list from the
  profile into the `classics` table. **User reviews/edits/approves before any run.**
  (LLM works from training knowledge, so may miss very recent "instant classics" or
  niche Talus must-reads — hence the review step.)
- Each run drains the top `pending` classics into that run's classic slots; once
  summarized they flip to `shown` and land in `papers`.
- Re-running `init-classics` (or hand-adding rows) refills the backlog anytime
  interests shift.

## Web UI

FastAPI + Jinja + htmx, local only (`127.0.0.1`), no auth/accounts.

- `litreview serve` → `http://localhost:8000`.
- **Digest** (`/`): unread summaries as cards, newest run first. Each card: title,
  authors, venue, date, OA/preprint badge, axis tags, the four sections
  (Approach · Result · Why it's novel · Why it's relevant to you), link out.
  "Mark as read" per card (htmx POST → flips status, sets `read_at`, removes from
  unread) + "mark all read."
- **Archive** (`/archive`): everything acknowledged, searchable by title/keyword.
- **Rating**: a 1–5 control wired to `summaries.rating` but **inert in v1** (stores
  the value; nothing consumes it), so the feedback loop is a future enhancement,
  not a schema migration.
- **`/status`**: last run time + any error, so a failed overnight run is visible.

## CLI surface

Thin wrappers over the components:

- `litreview init-classics` — draft & seed the classics backlog (review before use)
- `litreview run` — one weekly execution
- `litreview serve` — start the web UI
- `litreview status` — last run + errors

## Setup & sharing (coworker flow)

1. `git clone` → `pip install -e .` (or `uv`).
2. `export ANTHROPIC_API_KEY=...`
3. Copy `profile.example.toml` → `profile.toml`, edit it.
4. `litreview init-classics`, review the drafted list.
5. `litreview run` once by hand to confirm; `litreview serve` to read.
6. Scheduling: use the documented `launchd` plist template to run `litreview run`
   weekly (the only machine-specific, non-portable piece — deliberately outside the
   app; Linux users swap in a cron line).

## Testing

Deterministic spine unit-tested with no network/API:

- `PaperSource` impls against **recorded API fixtures** (saved JSON) — no live calls.
- `Archive` dedup/read-state against a temp SQLite DB.
- Slot allocator (30/70) and atomic-write behavior tested directly.
- `Ranker`/`Summarizer`: tested with a **fake** implementing the interface (asserts
  pipeline wiring), plus one optional live "smoke" test behind a flag for eyeballing
  real output.

## Explicit non-goals / YAGNI (v1)

- No multi-user / hosted service (design leaves room; doesn't build it).
- No feedback loop consuming ratings (schema reserved only).
- No paid/licensed source integrations (interface, config slot, and `full_text`
  field leave room; not built).
- No 24/7 daemon (scheduled runs only).

## Future extensions (designed-for, not built)

- **Additional paper sources**, including paid/institutional (.edu) access. The
  `PaperSource` interface, `[sources.<name>]` credential slots, and optional
  `full_text` field are the seams. Caveat: institutional access is usually
  SSO/session-based and can't be replayed by a headless job — automation depends
  on the specific publisher offering token/API access; Unpaywall / Europe PMC
  already surface substantial OA full text legally. Auth mechanism is TBD per
  publisher.
- **Feedback loop**: use `summaries.rating` to shape future ranking.
- **Richer scheduling / true background operation** (menu-bar app or daemon).
