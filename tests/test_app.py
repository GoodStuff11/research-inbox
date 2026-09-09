import pytest

import app as app_module

ATTENTION_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <updated>2017-12-06T00:00:00Z</updated>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <summary>...</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
</feed>"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    app_module.init_db()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/reading-list").status_code == 200


def test_add_reading_list_entry_with_valid_link_returns_verified_metadata(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)

    resp = client.post("/api/reading-list", json={
        "arxiv_link": "https://arxiv.org/abs/1706.03762",
        "folder": "ML Theory",
        "reason": "want to understand attention",
    })

    assert resp.status_code == 201

    listed = client.get("/api/reading-list").get_json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Attention Is All You Need"
    assert listed[0]["arxiv_id"] == "1706.03762"
    assert listed[0]["folder"] == "ML Theory"
    assert listed[0]["reason"] == "want to understand attention"
    assert listed[0]["status"] == "to_read"


def test_add_reading_list_entry_with_unparseable_text_returns_400(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: EMPTY_FEED)

    resp = client.post("/api/reading-list", json={
        "arxiv_link": "this is not a link at all",
        "folder": "",
        "reason": "",
    })

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Couldn't find an arxiv ID in that link/text."
    assert client.get("/api/reading-list").get_json() == []


def test_add_reading_list_entry_with_nonexistent_arxiv_id_returns_400(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: EMPTY_FEED)

    resp = client.post("/api/reading-list", json={
        "arxiv_link": "9999.99999",
        "folder": "",
        "reason": "",
    })

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "That arxiv ID doesn't seem to exist — check the link and try again."


def test_http_get_retries_on_failure_then_succeeds(monkeypatch):
    calls = []

    class FakeResponse:
        text = "ok"

    def fake_get(url, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise app_module.requests.exceptions.ConnectionError("boom")
        return FakeResponse()

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)

    result = app_module._http_get("http://example.com", max_attempts=3)

    assert result == "ok"
    assert len(calls) == 3


def test_http_get_uses_a_generous_timeout_for_cold_arxiv_cache_misses(monkeypatch):
    seen_timeouts = []

    class FakeResponse:
        text = "ok"

    def fake_get(url, timeout):
        seen_timeouts.append(timeout)
        return FakeResponse()

    monkeypatch.setattr(app_module.requests, "get", fake_get)

    app_module._http_get("http://example.com")

    assert seen_timeouts == [30]


def test_http_get_defaults_to_a_single_attempt(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        raise app_module.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)

    with pytest.raises(app_module.requests.exceptions.ConnectionError):
        app_module._http_get("http://example.com")

    assert len(calls) == 1


def test_http_get_raises_after_max_attempts(monkeypatch):
    def fake_get(url, timeout):
        raise app_module.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)

    with pytest.raises(app_module.requests.exceptions.ConnectionError):
        app_module._http_get("http://example.com")


def test_add_reading_list_entry_when_arxiv_unreachable_returns_400(client, monkeypatch):
    def _raise(url):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(app_module, "_http_get", _raise)

    resp = client.post("/api/reading-list", json={
        "arxiv_link": "1706.03762",
        "folder": "",
        "reason": "",
    })

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Couldn't reach arxiv to verify that link — check your connection and try again."
    assert client.get("/api/reading-list").get_json() == []


def test_add_reading_list_entry_with_malformed_xml_response_returns_400(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: "not xml at all")

    resp = client.post("/api/reading-list", json={
        "arxiv_link": "1706.03762",
        "folder": "",
        "reason": "",
    })

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Couldn't reach arxiv to verify that link — check your connection and try again."
    assert client.get("/api/reading-list").get_json() == []


def test_patch_status_updates_reading_list_entry(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)
    add_resp = client.post("/api/reading-list", json={"arxiv_link": "1706.03762", "folder": "", "reason": ""})
    entry_id = add_resp.get_json()["id"]

    resp = client.patch(f"/api/reading-list/{entry_id}", json={"status": "read"})

    assert resp.status_code == 200
    listed = client.get("/api/reading-list").get_json()
    assert listed[0]["status"] == "read"


def test_patch_folder_updates_reading_list_entry(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)
    add_resp = client.post("/api/reading-list", json={"arxiv_link": "1706.03762", "folder": "", "reason": ""})
    entry_id = add_resp.get_json()["id"]

    resp = client.patch(f"/api/reading-list/{entry_id}", json={"folder": "ML Theory"})

    assert resp.status_code == 200
    listed = client.get("/api/reading-list").get_json()
    assert listed[0]["folder"] == "ML Theory"


def test_patch_thoughts_updates_reading_list_entry(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)
    add_resp = client.post("/api/reading-list", json={"arxiv_link": "1706.03762", "folder": "", "reason": ""})
    entry_id = add_resp.get_json()["id"]

    resp = client.patch(f"/api/reading-list/{entry_id}", json={"thoughts": "great paper"})

    assert resp.status_code == 200
    listed = client.get("/api/reading-list").get_json()
    assert listed[0]["thoughts"] == "great paper"


def test_patch_unknown_id_returns_404(client):
    resp = client.patch("/api/reading-list/9999", json={"status": "read"})
    assert resp.status_code == 404


def test_delete_removes_reading_list_entry(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)
    add_resp = client.post("/api/reading-list", json={"arxiv_link": "1706.03762", "folder": "", "reason": ""})
    entry_id = add_resp.get_json()["id"]

    resp = client.delete(f"/api/reading-list/{entry_id}")

    assert resp.status_code == 200
    assert client.get("/api/reading-list").get_json() == []


def test_delete_unknown_id_returns_404(client):
    resp = client.delete("/api/reading-list/9999")
    assert resp.status_code == 404


def test_add_to_reading_list_from_found_entry(client):
    entry_id = app_module.add_entry("what is attention?")
    app_module.update_paper(entry_id, {
        "title": "Attention Is All You Need",
        "authors": "Ashish Vaswani et al., 2017",
        "arxiv_id": "1706.03762",
        "venue": "cs.CL",
        "why": "It answers your question.",
    })

    resp = client.post(f"/api/entries/{entry_id}/add-to-reading-list")

    assert resp.status_code == 201
    listed = client.get("/api/reading-list").get_json()
    assert len(listed) == 1
    assert listed[0]["arxiv_id"] == "1706.03762"
    assert listed[0]["folder"] is None
    assert listed[0]["reason"] == "what is attention?"
    assert listed[0]["status"] == "to_read"


def test_add_to_reading_list_from_entry_without_paper_returns_400(client):
    entry_id = app_module.add_entry("some thought")

    resp = client.post(f"/api/entries/{entry_id}/add-to-reading-list")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "This entry doesn't have a matched paper yet."


def test_add_to_reading_list_from_unknown_entry_returns_404(client):
    resp = client.post("/api/entries/9999/add-to-reading-list")
    assert resp.status_code == 404
