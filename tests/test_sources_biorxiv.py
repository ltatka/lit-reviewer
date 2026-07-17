import datetime
import json
import pathlib
from litreview.sources.biorxiv import BioRxivSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "biorxiv_details.json"


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


def test_biorxiv_filters_by_category_and_maps_fields():
    payload = json.loads(FIX.read_text())
    src = BioRxivSource({"category": "biochemistry"}, client=FakeClient(payload))
    cands = src.fetch("ignored", since=datetime.date(2026, 7, 1))
    assert src.name == "biorxiv"
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "biorxiv"
    assert c.source_id == "10.1101/2026.07.01.500001"
    assert c.doi == "10.1101/2026.07.01.500001"
    assert c.authors == ["Roe, J.", "Doe, J."]
    assert c.abstract == "We solved the structure."
    assert c.is_oa is True     # preprints are open
    assert c.url == "https://www.biorxiv.org/content/10.1101/2026.07.01.500001"


def test_biorxiv_no_category_returns_all():
    payload = json.loads(FIX.read_text())
    src = BioRxivSource({}, client=FakeClient(payload))
    cands = src.fetch("ignored", since=datetime.date(2026, 7, 1))
    assert len(cands) == 2


def test_biorxiv_builds_dated_details_url():
    payload = json.loads(FIX.read_text())
    fake = FakeClient(payload)
    BioRxivSource({}, client=fake).fetch("x", since=datetime.date(2026, 7, 1))
    url, _ = fake.calls[0]
    assert "/details/biorxiv/2026-07-01/" in url
