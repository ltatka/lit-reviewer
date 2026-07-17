import os
import textwrap
import pytest
from litreview.archive import Archive
from litreview.config import Profile
from litreview.pipeline import Pipeline
from litreview.ranking import ClaudeRanker
from litreview.sources.openalex import OpenAlexSource
from litreview.summarize import ClaudeSummarizer


@pytest.mark.skipif(
    os.environ.get("LITREVIEW_LIVE") != "1",
    reason="set LITREVIEW_LIVE=1 (and ANTHROPIC_API_KEY) to run the live smoke test",
)
def test_live_end_to_end(tmp_path):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent("""
        [identity]
        description = "I work on proteomics and ML for mass spectrometry."
        [axes]
        domain_focus = ["proteomics", "mass spectrometry"]
        portable_ml = "ML methods relevant to proteomics."
        [schedule]
        cadence_days = 7
        picks_per_run = 3
        classic_fraction = 0.0
        [sources]
        enabled = ["openalex"]
        [sources.openalex]
        query = "proteomics deep learning"
    """))
    profile = Profile.load(p)
    archive = Archive(str(tmp_path / "live.db"))
    archive.initialize()
    pipe = Pipeline(profile, archive, [OpenAlexSource(profile.sources_config["openalex"])],
                    ClaudeRanker(), ClaudeSummarizer())
    result = pipe.run()
    assert result["status"] == "ok"
    assert result["n_selected"] >= 1
    for row in archive.unread_summaries():
        print("\n===", row["title"])
        print("APPROACH:", row["approach"])
        print("RELEVANCE:", row["relevance"])
