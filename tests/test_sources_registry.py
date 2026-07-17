import dataclasses

import pytest

from litreview.sources import build_sources
from litreview.sources.openalex import OpenAlexSource


def test_build_sources_instantiates_enabled_openalex(profile):
    sources = build_sources(profile)
    assert len(sources) == 1
    src = sources[0]
    assert isinstance(src, OpenAlexSource)
    assert src.name == "openalex"


def test_build_sources_unknown_name_raises(profile):
    bad = dataclasses.replace(profile, sources_enabled=["does_not_exist"])
    with pytest.raises(ValueError):
        build_sources(bad)
