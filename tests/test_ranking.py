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
