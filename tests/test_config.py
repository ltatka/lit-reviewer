import textwrap
import pytest
from litreview.config import Profile, ProfileError


def _write(tmp_path, text):
    p = tmp_path / "profile.toml"
    p.write_text(textwrap.dedent(text))
    return p


def test_load_full_profile(tmp_path):
    path = _write(tmp_path, """
        [identity]
        description = "I study proteomics."
        [axes]
        domain_focus = ["proteomics", "DIA-MS"]
        portable_ml = "ML that could transfer."
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.30
        lookback_days = 365
        [sources]
        enabled = ["openalex", "biorxiv"]
        [sources.openalex]
        query = "proteomics"
    """)
    prof = Profile.load(path)
    assert prof.description == "I study proteomics."
    assert prof.domain_focus == ["proteomics", "DIA-MS"]
    assert prof.picks_per_run == 5
    assert prof.classic_fraction == 0.30
    assert prof.lookback_days == 365
    assert prof.sources_enabled == ["openalex", "biorxiv"]
    assert prof.sources_config["openalex"]["query"] == "proteomics"


def test_lookback_days_defaults_to_730(tmp_path):
    path = _write(tmp_path, """
        [identity]
        description = "I study proteomics."
        [axes]
        domain_focus = ["proteomics"]
        portable_ml = "ML that could transfer."
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.30
        [sources]
        enabled = ["openalex"]
    """)
    prof = Profile.load(path)
    assert prof.lookback_days == 730


def test_missing_description_raises(tmp_path):
    path = _write(tmp_path, """
        [axes]
        domain_focus = []
        portable_ml = "x"
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 0.3
        [sources]
        enabled = ["openalex"]
    """)
    with pytest.raises(ProfileError):
        Profile.load(path)


def test_invalid_classic_fraction_raises(tmp_path):
    path = _write(tmp_path, """
        [identity]
        description = "x"
        [axes]
        domain_focus = []
        portable_ml = "x"
        [schedule]
        cadence_days = 7
        picks_per_run = 5
        classic_fraction = 1.5
        [sources]
        enabled = ["openalex"]
    """)
    with pytest.raises(ProfileError):
        Profile.load(path)
