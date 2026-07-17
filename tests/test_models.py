from litreview.models import Candidate, Summary, ClassicEntry


def test_dedup_key_prefers_doi():
    c = Candidate(source="openalex", source_id="W1", title="t", authors=[], doi="10.1/x")
    assert c.dedup_key() == "doi:10.1/x"


def test_dedup_key_falls_back_to_source_id():
    c = Candidate(source="openalex", source_id="W1", title="t", authors=[])
    assert c.dedup_key() == "src:openalex:W1"


def test_candidate_defaults():
    c = Candidate(source="s", source_id="i", title="t", authors=["A"])
    assert c.kind == "fresh"
    assert c.is_oa is False
    assert c.full_text is None


def test_summary_and_classic_fields():
    s = Summary(approach="a", result="r", novelty="n", relevance="v",
                why_relevant_axes=["domain"])
    assert s.why_relevant_axes == ["domain"]
    e = ClassicEntry(title="Seminal Paper", note="foundational")
    assert e.status == "pending"
    assert e.authors == []
