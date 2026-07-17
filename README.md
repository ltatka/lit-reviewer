# litreview

A local weekly literature-review digest. Fetches relevant papers, LLM-ranks and
summarizes the best 3–6, and serves them in a local web UI you read and
acknowledge into a searchable archive.

## Setup

Uses [uv](https://docs.astral.sh/uv/). `uv sync` creates `.venv` and installs
everything from `uv.lock`; `uv run` executes inside that env.

```bash
uv sync --extra dev                    # create .venv + install (editable) from the lockfile
export ANTHROPIC_API_KEY=sk-ant-...
cp profile.example.toml profile.toml   # then edit it
uv run litreview init-classics         # review the drafted foundational list
uv run litreview run                   # do one run by hand
uv run litreview serve                 # read at http://localhost:8000
```

(Activate the env with `source .venv/bin/activate` if you'd rather drop the
`uv run` prefix. Prefer pip? `pip install -e ".[dev]"` still works against the
same `pyproject.toml`.)

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
uv run pytest
```
