import datetime
import json
import pathlib
from litreview.sources.openalex import OpenAlexSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "openalex_works.json"


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


def test_openalex_maps_fields_and_reconstructs_abstract():
    payload = json.loads(FIX.read_text())
    src = OpenAlexSource({"query": "proteomics"}, client=FakeClient(payload))
    cands = src.fetch("proteomics", since=datetime.date(2026, 6, 1))
    assert src.name == "openalex"
    assert len(cands) == 2
    c0 = cands[0]
    assert c0.source == "openalex"
    assert c0.source_id == "W123"
    assert c0.doi == "10.1234/abc"          # bare DOI, prefix stripped
    assert c0.title == "A DIA-MS method for fast proteomics"
    assert c0.authors == ["Jane Roe", "John Doe"]
    assert c0.venue == "Nature Methods"
    assert c0.is_oa is True
    assert c0.abstract == "Fast proteomics method."   # reconstructed from inverted index
    c1 = cands[1]
    assert c1.doi is None
    assert c1.venue is None
    assert c1.abstract is None


def test_openalex_passes_since_filter():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    src = OpenAlexSource({"query": "proteomics"}, client=fake)
    src.fetch("proteomics", since=datetime.date(2026, 6, 1))
    _, params = fake.calls[0]
    assert "from_publication_date:2026-06-01" in params["filter"]
