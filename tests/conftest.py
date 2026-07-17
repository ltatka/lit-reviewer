import textwrap
import pytest
from litreview.config import Profile


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent("""
        [identity]
        description = "I study proteomics and ML for mass spec."
        [axes]
        domain_focus = ["proteomics", "DIA-MS"]
        portable_ml = "ML methods that could transfer to proteomics."
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.30
        [sources]
        enabled = ["openalex"]
        [sources.openalex]
        query = "proteomics"
    """))
    return Profile.load(p)
