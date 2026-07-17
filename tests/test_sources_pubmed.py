import datetime
import json
import pathlib
from litreview.sources.pubmed import PubMedSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "europepmc_search.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self._payload)


def test_pubmed_maps_fields():
    payload = json.loads(FIX.read_text())
    src = PubMedSource({"query": "protac"}, client=FakeClient(payload))
    cands = src.fetch("protac", since=datetime.date(2026, 6, 1))
    assert src.name == "pubmed"
    assert len(cands) == 2
    c0 = cands[0]
    assert c0.source == "pubmed"
    assert c0.source_id == "40000001"
    assert c0.doi == "10.9999/pmid1"
    assert c0.authors == ["Roe J", "Doe J"]
    assert c0.venue == "Cell"
    assert c0.abstract == "We describe a new PROTAC."
    assert c0.is_oa is True
    assert c0.url == "https://europepmc.org/article/MED/40000001"
    c1 = cands[1]
    assert c1.abstract is None
    assert c1.is_oa is False


def test_pubmed_builds_date_filtered_query():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    PubMedSource({}, client=fake).fetch("protac", since=datetime.date(2026, 6, 1))
    _, params = fake.calls[0]
    assert "protac" in params["query"]
    assert "FIRST_PDATE:[2026-06-01" in params["query"]
    assert params["format"] == "json"
