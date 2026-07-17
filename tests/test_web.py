from fastapi.testclient import TestClient
from litreview.archive import Archive
from litreview.models import Candidate, Summary
from litreview.web.app import create_app


def _seed(tmp_path):
    a = Archive(str(tmp_path / "web.db"))
    a.initialize()
    run = a.create_run()
    a.store_selection(run, [
        (Candidate(source="openalex", source_id="W1", title="Proteomics breakthrough",
                   authors=["J. Roe"], doi="10.1/a", kind="fresh", is_oa=True,
                   published_date="2026-07-01"),
         Summary("The approach.", "The result.", "The novelty.",
                 "Why it matters to you.", ["domain"],
                 eli12="A kid-friendly explanation.")),
    ])
    a.finish_run(run, 5, 1, status="ok")
    return a


def test_digest_shows_unread(tmp_path):
    app = create_app(_seed(tmp_path))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Proteomics breakthrough" in resp.text
    assert "The novelty." in resp.text
    assert "Published 2026-07-01" in resp.text


def test_publication_date_shows_in_digest_and_archive(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    assert "Published 2026-07-01" in client.get("/").text
    sid = archive.unread_summaries()[0]["summary_id"]
    client.post(f"/read/{sid}")
    assert "Published 2026-07-01" in client.get("/archive").text


def test_eli12_shows_in_digest_and_archive(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    resp = client.get("/")
    assert "Explain Like I'm 12" in resp.text
    assert "A kid-friendly explanation." in resp.text
    sid = archive.unread_summaries()[0]["summary_id"]
    client.post(f"/read/{sid}")
    resp = client.get("/archive")
    assert "Explain Like I'm 12" in resp.text
    assert "A kid-friendly explanation." in resp.text


def test_mark_read_then_appears_in_archive(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    r = client.post(f"/read/{sid}")
    assert r.status_code == 200
    assert "Proteomics breakthrough" not in client.get("/").text
    assert "Proteomics breakthrough" in client.get("/archive").text


def test_archive_search(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    client.post(f"/read/{sid}")
    assert "Proteomics breakthrough" in client.get("/archive?q=proteomics").text
    assert "Proteomics breakthrough" not in client.get("/archive?q=genomics").text


def test_status_page(tmp_path):
    app = create_app(_seed(tmp_path))
    client = TestClient(app)
    resp = client.get("/status")
    assert resp.status_code == 200
    assert "ok" in resp.text.lower()


def test_rate_is_accepted(tmp_path):
    archive = _seed(tmp_path)
    app = create_app(archive)
    client = TestClient(app)
    sid = archive.unread_summaries()[0]["summary_id"]
    r = client.post(f"/rate/{sid}", data={"rating": "4"})
    assert r.status_code == 200
