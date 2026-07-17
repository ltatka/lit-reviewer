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
