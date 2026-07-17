from litreview.models import Candidate
from litreview.ranking import allocate_slots, FakeRanker, ClaudeRanker


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


class _FakeParsed:
    def __init__(self, indices):
        self.parsed_output = type("P", (), {"indices": indices})()


class _FakeMessages:
    def __init__(self, indices):
        self._indices = indices

    def parse(self, **kwargs):
        return _FakeParsed(self._indices)


class _FakeClient:
    def __init__(self, indices):
        self.messages = _FakeMessages(indices)


class _FakeProfile:
    description = "test researcher"
    domain_focus = ["x"]
    portable_ml = "y"


def test_claude_ranker_dedups_and_drops_out_of_range():
    cands = [_c(i) for i in range(3)]  # valid indices: 0, 1, 2
    ranker = ClaudeRanker(client=_FakeClient([2, 2, 0, 5]))
    picked = ranker.select(cands, profile=_FakeProfile(), n=3)
    # 2 deduped, 0 kept in order, out-of-range 5 dropped
    assert [c.source_id for c in picked] == ["W2", "W0"]
