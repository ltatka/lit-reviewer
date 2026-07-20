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

    # --reset wipes the prior backlog before drafting (no duplicates accumulate)
    from litreview.archive import Archive
    rc = cli.main(["--profile", str(prof), "--db", str(db), "init-classics", "-n", "3", "--reset"],
                  drafter=FakeClassicsDrafter())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Cleared existing classics backlog." in out
    # 3 drafted, reset first -> exactly 3 pending, not 6
    assert len(Archive(str(db)).pending_classics(limit=100)) == 3

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
