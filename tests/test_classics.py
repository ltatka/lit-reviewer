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
