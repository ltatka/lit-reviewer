from litreview.models import Candidate
from litreview.summarize import FakeSummarizer


def test_fake_summarizer_returns_summary():
    c = Candidate(source="s", source_id="W1", title="Cool Paper", authors=[],
                  abstract="We did science.")
    s = FakeSummarizer().summarize(c, profile=None)
    assert s.approach
    assert "Cool Paper" in s.relevance
    assert isinstance(s.why_relevant_axes, list)
