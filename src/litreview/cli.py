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
    if args.reset:
        archive.clear_classics()
        print("Cleared existing classics backlog.")
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
    ic.add_argument("--reset", action="store_true",
                    help="clear the existing classics backlog before drafting")

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
