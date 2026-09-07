# Reading List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second page to research-inbox — a reading list, organized by folder and read/unread/not-interested status — separate from the existing inbox page, with a one-click way to send a matched inbox paper straight into it.

**Architecture:** A new `reading_list` SQLite table (independent from the existing `entries` table), two new pure arxiv-lookup functions in `paper_finder.py` (reusing the existing verification machinery), a handful of new Flask routes in `app.py`, and a new server-rendered page (`templates/reading_list.html`) with a small shared nav include added to both pages.

**Tech Stack:** Flask, sqlite3 (stdlib), vanilla JS (no framework, matching the existing `index.html`), pytest + Flask test client.

**Spec:** `docs/superpowers/specs/2026-09-07-reading-list-design.md`

## Global Constraints

- No new third-party dependencies — everything needed (Flask, `sqlite3`, `requests`) is already in `requirements.txt`.
- Folders are a flat string column, created inline by typing a new name — no folders table, no nesting, no folder management UI.
- No re-foldering after add: the `PATCH` endpoint accepts a `folder` field at the API layer, but no UI element in this plan calls it with a new folder value.
- No auth/multi-user handling — stays a local, single-user, laptop-only Flask app.
- No JS test framework is introduced — UI tasks (nav, reading list page, inbox button) are manually browser-tested, per the spec's explicit call-out.
- Backend tasks (DB helpers, routes, `paper_finder.py` functions) follow this project's established TDD discipline: write the failing test, watch it fail for the right reason, write minimal code, watch it pass, then commit.
- Error copy is exact, not paraphrased:
  - `"Couldn't find an arxiv ID in that link/text."` (400, unparseable link)
  - `"That arxiv ID doesn't seem to exist — check the link and try again."` (400, link parses but arxiv has no such paper)
  - `"This entry doesn't have a matched paper yet."` (400, cross-link button on an entry with no paper)
- Button/label copy: "Finished reading", "Not interested", "+ Add to reading list", "✓ Added".

---

### Task 1: `extract_arxiv_id` in `paper_finder.py`

**Files:**
- Modify: `paper_finder.py`
- Test: `tests/test_paper_finder.py`

**Interfaces:**
- Produces: `extract_arxiv_id(text: str) -> str | None` — finds a new-style arxiv id (`\d{4}\.\d{4,5}`, optionally followed by a `vN` version suffix which is stripped) anywhere in `text` — a bare id, an `arxiv.org/abs/...` URL, or an `arxiv.org/pdf/....pdf` URL, with or without a scheme. Returns `None` if no such pattern is found.

- [ ] **Step 1: Write the failing tests**

Add to the top of `tests/test_paper_finder.py`, updating the import line:

```python
from paper_finder import (
    parse_arxiv_feed, fuzzy_title_match, verify_candidate, find_paper_data,
    extract_arxiv_id,
)
```

Add these tests anywhere after the existing `fuzzy_title_match` tests:

```python
def test_extract_arxiv_id_from_bare_id():
    assert extract_arxiv_id("1706.03762") == "1706.03762"


def test_extract_arxiv_id_from_abs_url():
    assert extract_arxiv_id("https://arxiv.org/abs/1706.03762") == "1706.03762"


def test_extract_arxiv_id_from_pdf_url_with_version():
    assert extract_arxiv_id("https://arxiv.org/pdf/1706.03762v2.pdf") == "1706.03762"


def test_extract_arxiv_id_from_url_without_scheme():
    assert extract_arxiv_id("arxiv.org/abs/1706.03762") == "1706.03762"


def test_extract_arxiv_id_returns_none_for_garbage_text():
    assert extract_arxiv_id("this is not a link at all") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_paper_finder.py -k extract_arxiv_id -v`
Expected: FAIL with `ImportError: cannot import name 'extract_arxiv_id'`

- [ ] **Step 3: Write minimal implementation**

Add to `paper_finder.py`, near the top with the other imports and the other small pure functions (after `fuzzy_title_match`, before `_format_authors` is fine):

```python
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


def extract_arxiv_id(text):
    match = ARXIV_ID_RE.search(text)
    return match.group(1) if match else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_paper_finder.py -v`
Expected: all tests PASS (the 5 new ones plus all pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add paper_finder.py tests/test_paper_finder.py
git commit -m "Add extract_arxiv_id for parsing arxiv links/ids from free text"
```

---

### Task 2: `fetch_arxiv_by_id` + refactor `verify_candidate` in `paper_finder.py`

**Files:**
- Modify: `paper_finder.py`
- Test: `tests/test_paper_finder.py`

**Interfaces:**
- Consumes: `parse_arxiv_feed(xml_text) -> list[dict]` (already exists), `ARXIV_API` constant (already exists).
- Produces: `fetch_arxiv_by_id(arxiv_id: str, http_get: Callable[[str], str]) -> dict | None` — looks up `arxiv_id` via arxiv's `id_list` endpoint, returns the first parsed entry (`{title, arxiv_id, authors, venue}`) or `None` if the feed is empty. No title-matching — this is a direct "does this id exist" lookup, unlike `verify_candidate`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_paper_finder.py`'s import line (extending Task 1's line):

```python
from paper_finder import (
    parse_arxiv_feed, fuzzy_title_match, verify_candidate, find_paper_data,
    extract_arxiv_id, fetch_arxiv_by_id,
)
```

Add these tests near the existing `verify_candidate` tests:

```python
def test_fetch_arxiv_by_id_returns_entry_when_found():
    http_get = _fake_http_get(id_response=ATTENTION_FEED)

    result = fetch_arxiv_by_id("1706.03762", http_get)

    assert result["title"] == "Attention Is All You Need"
    assert result["arxiv_id"] == "1706.03762"


def test_fetch_arxiv_by_id_returns_none_when_not_found():
    http_get = _fake_http_get(id_response=EMPTY_FEED)

    assert fetch_arxiv_by_id("9999.99999", http_get) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_paper_finder.py -k fetch_arxiv_by_id -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_arxiv_by_id'`

- [ ] **Step 3: Write minimal implementation, refactoring `verify_candidate` to reuse it**

In `paper_finder.py`, add `fetch_arxiv_by_id` and change `verify_candidate`'s id-lookup branch to call it:

```python
def fetch_arxiv_by_id(arxiv_id, http_get):
    xml_text = http_get(f"{ARXIV_API}?id_list={arxiv_id}")
    entries = parse_arxiv_feed(xml_text)
    return entries[0] if entries else None


def verify_candidate(candidate, http_get):
    title = candidate.get("title") or ""
    arxiv_id = candidate.get("arxiv_id")

    if arxiv_id:
        entry = fetch_arxiv_by_id(arxiv_id, http_get)
        if entry and fuzzy_title_match(entry["title"], title):
            return entry

    if title:
        query = urllib.parse.quote(f'ti:"{title}"')
        xml_text = http_get(f"{ARXIV_API}?search_query={query}&max_results=1")
        entries = parse_arxiv_feed(xml_text)
        if entries and fuzzy_title_match(entries[0]["title"], title):
            return entries[0]

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_paper_finder.py -v`
Expected: all tests PASS, including every pre-existing `verify_candidate` and `find_paper_data` test (confirms the refactor didn't change external behavior)

- [ ] **Step 5: Commit**

```bash
git add paper_finder.py tests/test_paper_finder.py
git commit -m "Add fetch_arxiv_by_id, refactor verify_candidate to reuse it"
```

---

### Task 3: Reading list schema + create/list, `POST`/`GET /api/reading-list`

**Files:**
- Modify: `app.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes: `extract_arxiv_id(text) -> str | None`, `fetch_arxiv_by_id(arxiv_id, http_get) -> dict | None` (Tasks 1–2); `_http_get(url) -> str` (already exists in `app.py`); `get_db()`, `DB_PATH` (already exist in `app.py`).
- Produces: `add_reading_list_entry(arxiv_id, title, authors, venue, folder, reason) -> int` (returns new row id), `get_reading_list_entries() -> list[dict]`. Routes: `POST /api/reading-list`, `GET /api/reading-list`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL — `POST`/`GET /api/reading-list` don't exist yet, so Flask's test client gets a 404 (`assert 404 == 201` etc.)

- [ ] **Step 3: Write minimal implementation**

In `app.py`, update the import line to include the two new `paper_finder` functions:

```python
from paper_finder import find_paper_data, extract_arxiv_id, fetch_arxiv_by_id
```

Add the `reading_list` table to `init_db()` (append inside the same `with get_db() as db:` block, after the existing `entries` table's `db.execute(...)`, before `db.commit()`):

```python
        db.execute("""
            CREATE TABLE IF NOT EXISTS reading_list (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id    TEXT NOT NULL,
                title       TEXT NOT NULL,
                authors     TEXT,
                venue       TEXT,
                folder      TEXT,
                reason      TEXT,
                thoughts    TEXT,
                status      TEXT NOT NULL DEFAULT 'to_read',
                added_at    TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
```

Add these DB helpers after `delete_entry` (still in the `# ── Database ──` section):

```python
def add_reading_list_entry(arxiv_id, title, authors, venue, folder, reason):
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        cur = db.execute("""
            INSERT INTO reading_list
                (arxiv_id, title, authors, venue, folder, reason, status, added_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'to_read', ?, ?)
        """, (arxiv_id, title, authors, venue, folder, reason, now, now))
        db.commit()
        return cur.lastrowid

def get_reading_list_entries():
    with get_db() as db:
        rows = db.execute("SELECT * FROM reading_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]
```

Add these routes after the existing `/api/entries/<int:entry_id>` DELETE route:

```python
@app.route("/api/reading-list", methods=["GET"])
def api_reading_list_get():
    return jsonify(get_reading_list_entries())

@app.route("/api/reading-list", methods=["POST"])
def api_reading_list_add():
    data = request.json or {}
    arxiv_link = (data.get("arxiv_link") or "").strip()
    folder = (data.get("folder") or "").strip() or None
    reason = (data.get("reason") or "").strip() or None

    arxiv_id = extract_arxiv_id(arxiv_link)
    if not arxiv_id:
        return jsonify({"error": "Couldn't find an arxiv ID in that link/text."}), 400

    entry = fetch_arxiv_by_id(arxiv_id, _http_get)
    if not entry:
        return jsonify({"error": "That arxiv ID doesn't seem to exist — check the link and try again."}), 400

    row_id = add_reading_list_entry(
        arxiv_id=entry["arxiv_id"], title=entry["title"],
        authors=entry["authors"], venue=entry["venue"],
        folder=folder, reason=reason,
    )
    return jsonify({"id": row_id}), 201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py tests/test_paper_finder.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Add reading_list table and POST/GET /api/reading-list"
```

---

### Task 4: `PATCH`/`DELETE /api/reading-list/<id>`

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `add_reading_list_entry`, `get_reading_list_entries` (Task 3).
- Produces: `get_reading_list_entry(entry_id: int) -> dict | None`, `update_reading_list_entry(entry_id: int, updates: dict) -> None`, `delete_reading_list_entry(entry_id: int) -> None`. Routes: `PATCH /api/reading-list/<id>`, `DELETE /api/reading-list/<id>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py` (reuses the `client` fixture from Task 3):

```python
def test_patch_status_updates_reading_list_entry(client, monkeypatch):
    monkeypatch.setattr(app_module, "_http_get", lambda url: ATTENTION_FEED)
    add_resp = client.post("/api/reading-list", json={"arxiv_link": "1706.03762", "folder": "", "reason": ""})
    entry_id = add_resp.get_json()["id"]

    resp = client.patch(f"/api/reading-list/{entry_id}", json={"status": "read"})

    assert resp.status_code == 200
    listed = client.get("/api/reading-list").get_json()
    assert listed[0]["status"] == "read"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py -k "patch_ or delete_" -v`
Expected: FAIL — routes don't exist yet (404s where 200/400 expected, or errors)

- [ ] **Step 3: Write minimal implementation**

Add after `get_reading_list_entries` in `app.py`:

```python
def get_reading_list_entry(entry_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM reading_list WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None

READING_LIST_PATCHABLE_FIELDS = {"status", "folder", "thoughts"}

def update_reading_list_entry(entry_id, updates):
    fields = {k: v for k, v in updates.items() if k in READING_LIST_PATCHABLE_FIELDS}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [datetime.utcnow().isoformat(), entry_id]
    with get_db() as db:
        db.execute(f"UPDATE reading_list SET {set_clause}, updated_at = ? WHERE id = ?", values)
        db.commit()

def delete_reading_list_entry(entry_id):
    with get_db() as db:
        db.execute("DELETE FROM reading_list WHERE id = ?", (entry_id,))
        db.commit()
```

Add these routes after `api_reading_list_add`:

```python
@app.route("/api/reading-list/<int:entry_id>", methods=["PATCH"])
def api_reading_list_update(entry_id):
    if not get_reading_list_entry(entry_id):
        return jsonify({"error": "not found"}), 404
    update_reading_list_entry(entry_id, request.json or {})
    return jsonify({"ok": True})

@app.route("/api/reading-list/<int:entry_id>", methods=["DELETE"])
def api_reading_list_delete(entry_id):
    if not get_reading_list_entry(entry_id):
        return jsonify({"error": "not found"}), 404
    delete_reading_list_entry(entry_id)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py tests/test_paper_finder.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Add PATCH/DELETE for reading list entries"
```

---

### Task 5: Cross-link — `POST /api/entries/<id>/add-to-reading-list`

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `get_entry(entry_id) -> dict | None` (already exists), `add_entry`, `update_paper` (already exist, used directly by tests), `add_reading_list_entry` (Task 3).
- Produces: route `POST /api/entries/<id>/add-to-reading-list`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py -k add_to_reading_list -v`
Expected: FAIL — route doesn't exist yet (404 where 201/400 expected)

- [ ] **Step 3: Write minimal implementation**

Add to `app.py`, after the existing `/api/entries/<int:entry_id>/refind` route:

```python
@app.route("/api/entries/<int:entry_id>/add-to-reading-list", methods=["POST"])
def api_add_to_reading_list(entry_id):
    entry = get_entry(entry_id)
    if not entry:
        return jsonify({"error": "not found"}), 404
    if entry["status"] != "found":
        return jsonify({"error": "This entry doesn't have a matched paper yet."}), 400

    row_id = add_reading_list_entry(
        arxiv_id=entry["paper_arxiv_id"], title=entry["paper_title"],
        authors=entry["paper_authors"], venue=entry["paper_venue"],
        folder=None, reason=entry["thought"],
    )
    return jsonify({"id": row_id}), 201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/.venvs/research-inbox/bin/python -m pytest tests/test_app.py tests/test_paper_finder.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Add cross-link: POST /api/entries/<id>/add-to-reading-list"
```

---

### Task 6: Reading list page (`templates/reading_list.html`, `templates/_nav.html`, `GET /reading-list`)

**Files:**
- Create: `templates/_nav.html`
- Create: `templates/reading_list.html`
- Modify: `app.py`

**Interfaces:**
- Consumes: `GET/POST /api/reading-list`, `PATCH`/`DELETE /api/reading-list/<id>` (Tasks 3–4) via client-side `fetch`.
- Produces: route `GET /reading-list`; both `index()` and this new route pass an `active_page` template variable (`"inbox"` / `"reading-list"`) for `_nav.html` to highlight the current page.

This task is UI — no automated tests (per the spec's explicit call-out, this project introduces no JS test framework). Verify manually per Step 3.

- [ ] **Step 1: Create the shared nav partial**

Create `templates/_nav.html`:

```html
<nav class="top-nav">
  <a href="/" class="{{ 'active' if active_page == 'inbox' else '' }}">Inbox</a>
  <a href="/reading-list" class="{{ 'active' if active_page == 'reading-list' else '' }}">Reading List</a>
</nav>
```

- [ ] **Step 2: Create the reading list page**

Create `templates/reading_list.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reading List — Research Inbox</title>
<style>
  :root {
    --bg: #f8f7f4;
    --surface: #ffffff;
    --border: #e5e3dd;
    --border-strong: #ccc9c0;
    --text: #1a1a18;
    --text-2: #6b6a65;
    --text-3: #9e9c97;
    --accent: #1a6fd4;
    --accent-bg: #eef4fd;
    --accent-border: #b8d0f0;
    --success: #1a7a4a;
    --success-bg: #eaf5ef;
    --warning: #916a00;
    --warning-bg: #fef9ec;
    --danger: #b83232;
    --danger-bg: #fdf0f0;
    --radius: 8px;
    --radius-lg: 12px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #151513;
      --surface: #1e1e1b;
      --border: #2e2e2a;
      --border-strong: #3e3e3a;
      --text: #e8e6e0;
      --text-2: #9e9c97;
      --text-3: #6b6a65;
      --accent: #5b9fee;
      --accent-bg: #1a2a3e;
      --accent-border: #2a4a6e;
      --success: #4aaa74;
      --success-bg: #162a20;
      --warning: #d4a020;
      --warning-bg: #2a2210;
      --danger: #e06060;
      --danger-bg: #2a1616;
    }
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 15px;
    line-height: 1.6;
    min-height: 100vh;
  }
  .container { max-width: 720px; margin: 0 auto; padding: 2rem 1.25rem; }
  header { margin-bottom: 1.5rem; }
  header h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; }
  header p { font-size: 14px; color: var(--text-2); margin-top: 4px; }

  .top-nav { display: flex; gap: 16px; margin-bottom: 1.5rem; }
  .top-nav a { font-size: 14px; font-weight: 500; color: var(--text-2); text-decoration: none; padding-bottom: 4px; border-bottom: 2px solid transparent; }
  .top-nav a:hover { color: var(--text); }
  .top-nav a.active { color: var(--accent); border-bottom-color: var(--accent); }

  .capture {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.25rem;
    margin-bottom: 2rem;
  }
  .capture label { font-size: 13px; color: var(--text-2); display: block; margin-bottom: 6px; }
  .capture input {
    width: 100%;
    font-family: inherit;
    font-size: 15px;
    padding: 8px 10px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    margin-bottom: 10px;
  }
  .capture input:focus { outline: none; border-color: var(--accent); }
  .capture input::placeholder { color: var(--text-3); }
  .capture-row { display: flex; gap: 8px; margin-top: 10px; align-items: center; }
  .err-msg { font-size: 13px; color: var(--danger); flex: 1; }
  button {
    font-family: inherit;
    font-size: 14px;
    font-weight: 500;
    padding: 7px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border-strong);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    display: inline-flex; align-items: center; gap: 6px;
    white-space: nowrap;
  }
  button:hover { background: var(--bg); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary:hover { opacity: 0.9; }
  button.sm { font-size: 13px; padding: 4px 10px; }
  button:disabled { opacity: 0.6; cursor: default; }

  .section-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-3);
    margin: 1.5rem 0 10px;
  }
  .section-label:first-of-type { margin-top: 0; }
  .folder-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-2);
    margin: 14px 0 8px;
  }
  .entries { display: flex; flex-direction: column; gap: 10px; }
  .entry {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .entry-body { padding: 1rem 1.25rem; }
  .paper-title {
    display: block;
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
    line-height: 1.4;
    margin-bottom: 3px;
  }
  .paper-title:hover { text-decoration: underline; }
  .paper-authors { font-size: 12px; color: var(--text-3); margin-bottom: 12px; }
  .why-box {
    background: var(--bg);
    border-left: 2px solid var(--accent);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding: 10px 14px;
    font-size: 14px;
    color: var(--text-2);
    line-height: 1.6;
    margin-bottom: 12px;
  }
  .why-label { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; font-weight: 600; }
  .thoughts-label { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; font-weight: 600; display: block; }
  .thoughts-box {
    width: 100%;
    font-family: inherit;
    font-size: 14px;
    padding: 8px 10px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    resize: vertical;
    margin-bottom: 10px;
  }
  .thoughts-box:focus { outline: none; border-color: var(--accent); }
  .card-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .btn-icon {
    background: none; border: none; color: var(--text-3); padding: 4px; border-radius: var(--radius); cursor: pointer; font-size: 16px; line-height: 1; display: flex; align-items: center; margin-left: auto;
  }
  .btn-icon:hover { color: var(--danger); background: var(--danger-bg); }
  .empty { text-align: center; padding: 1.5rem 0; color: var(--text-3); font-size: 14px; }
  details summary { cursor: pointer; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); margin: 1.5rem 0 10px; }
</style>
</head>
<body>
<div class="container">
  {% include "_nav.html" %}
  <header>
    <h1>Reading list</h1>
    <p>Papers you've decided to actually read.</p>
  </header>

  <div class="capture">
    <label for="link-input">Arxiv link or id</label>
    <input id="link-input" type="text" placeholder="e.g. https://arxiv.org/abs/1706.03762">
    <label for="folder-input">Folder (optional)</label>
    <input id="folder-input" type="text" list="folder-datalist" placeholder="e.g. ML Theory">
    <datalist id="folder-datalist"></datalist>
    <label for="reason-input">Why do you want to read this? (optional)</label>
    <input id="reason-input" type="text" placeholder="e.g. came up in a talk on attention mechanisms">
    <div class="capture-row">
      <button class="primary" onclick="addPaper()">Add</button>
      <span class="err-msg" id="add-err"></span>
    </div>
  </div>

  <div class="section-label">To read</div>
  <div class="entries" id="to-read-list"></div>

  <div class="section-label">Read</div>
  <div class="entries" id="read-list"></div>

  <details>
    <summary>Not interested</summary>
    <div class="entries" id="not-interested-list"></div>
  </details>
</div>

<script>
let items = [];

async function loadList() {
  try {
    const r = await fetch('/api/reading-list');
    items = await r.json();
    render();
  } catch(e) { console.error(e); }
}

async function addPaper() {
  const link = document.getElementById('link-input');
  const folder = document.getElementById('folder-input');
  const reason = document.getElementById('reason-input');
  const err = document.getElementById('add-err');
  err.textContent = '';
  const linkVal = link.value.trim();
  if (!linkVal) { err.textContent = 'Paste an arxiv link first.'; return; }
  try {
    const r = await fetch('/api/reading-list', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({arxiv_link: linkVal, folder: folder.value.trim(), reason: reason.value.trim()})
    });
    const data = await r.json();
    if (!r.ok) { err.textContent = data.error || 'Failed to add.'; return; }
    link.value = ''; folder.value = ''; reason.value = '';
    await loadList();
  } catch(e) {
    err.textContent = 'Failed to save. Is the server running?';
  }
}

async function setStatus(id, status, e) {
  e.stopPropagation();
  await fetch('/api/reading-list/' + id, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status})
  });
  loadList();
}

async function saveThoughts(id, value) {
  await fetch('/api/reading-list/' + id, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({thoughts: value})
  });
}

async function removeItem(id, e) {
  e.stopPropagation();
  if (!confirm('Remove this paper from your reading list?')) return;
  await fetch('/api/reading-list/' + id, {method: 'DELETE'});
  loadList();
}

function folderOptions() {
  const folders = [...new Set(items.map(i => i.folder).filter(Boolean))].sort();
  return folders.map(f => `<option value="${esc(f)}">`).join('');
}

function paperCard(item, showStatusButtons) {
  const url = `https://arxiv.org/abs/${item.arxiv_id}`;
  return `
    <div class="entry">
      <div class="entry-body">
        <a class="paper-title" href="${url}" target="_blank" rel="noopener">${esc(item.title)}</a>
        <div class="paper-authors">${esc(item.authors || '')}${item.venue ? ' · ' + esc(item.venue) : ''}</div>
        ${item.reason ? `<div class="why-box"><div class="why-label">Why</div>${esc(item.reason)}</div>` : ''}
        <label class="thoughts-label" for="thoughts-${item.id}">Thoughts</label>
        <textarea class="thoughts-box" id="thoughts-${item.id}" rows="2"
          onblur="saveThoughts(${item.id}, this.value)">${esc(item.thoughts || '')}</textarea>
        <div class="card-actions">
          ${showStatusButtons ? `
            <button class="sm" onclick="setStatus(${item.id}, 'read', event)">Finished reading</button>
            <button class="sm" onclick="setStatus(${item.id}, 'not_interested', event)">Not interested</button>
          ` : ''}
          <button class="btn-icon" onclick="removeItem(${item.id}, event)" title="Remove" aria-label="Remove">✕</button>
        </div>
      </div>
    </div>
  `;
}

function render() {
  document.getElementById('folder-datalist').innerHTML = folderOptions();

  const toRead = items.filter(i => i.status === 'to_read');
  const read = items.filter(i => i.status === 'read');
  const notInterested = items.filter(i => i.status === 'not_interested');

  const groups = {};
  toRead.forEach(i => {
    const key = i.folder || '';
    (groups[key] = groups[key] || []).push(i);
  });
  const folderNames = Object.keys(groups).filter(k => k !== '').sort();

  let toReadHTML = '';
  if (groups['']) {
    toReadHTML += `<div class="folder-name">Uncategorized</div>` + groups[''].map(i => paperCard(i, true)).join('');
  }
  folderNames.forEach(f => {
    toReadHTML += `<div class="folder-name">${esc(f)}</div>` + groups[f].map(i => paperCard(i, true)).join('');
  });
  document.getElementById('to-read-list').innerHTML = toReadHTML || '<div class="empty">Nothing queued yet.</div>';

  document.getElementById('read-list').innerHTML =
    read.map(i => paperCard(i, false)).join('') || '<div class="empty">No finished papers yet.</div>';
  document.getElementById('not-interested-list').innerHTML =
    notInterested.map(i => paperCard(i, false)).join('') || '<div class="empty">Nothing here.</div>';
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadList();
</script>
</body>
</html>
```

- [ ] **Step 3: Add the route**

In `app.py`, add after the existing `index()` route:

```python
@app.route("/reading-list")
def reading_list_page():
    return render_template("reading_list.html", active_page="reading-list")
```

Also update the existing `index()` route to pass `active_page` (needed by `_nav.html`):

```python
@app.route("/")
def index():
    entries = get_entries()
    return render_template("index.html", entries=entries, active_page="inbox")
```

- [ ] **Step 4: Manually verify in the browser**

Run: `cd /home/jonathon/Box/programming/personal/research-inbox && DB_PATH=/tmp/manual-test.db GEMINI_API_KEY= TELEGRAM_TOKEN= ~/.venvs/research-inbox/bin/python app.py`

Open `http://localhost:5000/reading-list`. Confirm:
- The nav shows "Inbox" / "Reading List" with "Reading List" highlighted.
- Pasting a real arxiv link (e.g. `https://arxiv.org/abs/1706.03762`) with a new folder name and a reason, then clicking Add, produces a card under a new folder heading in "To read".
- Pasting garbage text shows the inline error `Couldn't find an arxiv ID in that link/text.`
- "Finished reading" moves the card to the "Read" section; "Not interested" moves it under the collapsed "Not interested" `<details>`.
- Typing into the Thoughts box and clicking elsewhere (blur) persists after a page reload.
- The ✕ button removes a card after confirming.

Stop the server (Ctrl+C) and delete `/tmp/manual-test.db` when done.

- [ ] **Step 5: Commit**

```bash
git add app.py templates/_nav.html templates/reading_list.html
git commit -m "Add reading list page with folders, status sections, and thoughts"
```

---

### Task 7: Inbox page — nav + "Add to reading list" button

**Files:**
- Modify: `templates/index.html`
- Modify: `app.py` (already done in Task 6, Step 3 — no change needed here)

**Interfaces:**
- Consumes: `POST /api/entries/<id>/add-to-reading-list` (Task 5), `_nav.html` (Task 6), `active_page` template variable (already passed by Task 6, Step 3).

This task is UI — no automated tests, manually verified per Step 3.

- [ ] **Step 1: Add the nav include and its CSS**

In `templates/index.html`, add this CSS rule inside the existing `<style>` block, right after the `header p { ... }` rule (around line 60):

```css
  .top-nav { display: flex; gap: 16px; margin-bottom: 1.5rem; }
  .top-nav a { font-size: 14px; font-weight: 500; color: var(--text-2); text-decoration: none; padding-bottom: 4px; border-bottom: 2px solid transparent; }
  .top-nav a:hover { color: var(--text); }
  .top-nav a.active { color: var(--accent); border-bottom-color: var(--accent); }
  .card-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
```

Then, in the body, insert the include right after `<div class="container">` and before `<header>`:

```html
<div class="container">
  {% include "_nav.html" %}
  <header>
```

- [ ] **Step 2: Add the "Add to reading list" button and its JS**

Replace the `found` branch of the `render()` function's `bodyHTML` assignment (the block starting `} else if (entry.status === 'found' && entry.paper_title) {`) with:

```javascript
    } else if (entry.status === 'found' && entry.paper_title) {
      const url = entry.paper_arxiv_id
        ? `https://arxiv.org/abs/${entry.paper_arxiv_id}`
        : `https://scholar.google.com/scholar?q=${encodeURIComponent(entry.paper_title)}`;
      bodyHTML = `<div class="entry-body">
        <a class="paper-title" href="${url}" target="_blank" rel="noopener">${esc(entry.paper_title)}</a>
        <div class="paper-authors">${esc(entry.paper_authors || '')}${entry.paper_venue ? ' · ' + esc(entry.paper_venue) : ''}</div>
        <div class="why-box"><div class="why-label">Why this paper</div>${esc(entry.paper_why || '')}</div>
        <div class="card-actions">
          <button class="sm" onclick="refind(${entry.id}, event)">↺ Find another</button>
          ${addedIds.has(entry.id)
            ? `<button class="sm" disabled>✓ Added</button>`
            : `<button class="sm" onclick="addToReadingList(${entry.id}, event)">+ Add to reading list</button>`}
        </div>
      </div>`;
```

Add this near the top of the `<script>` block, alongside the existing `let entries = [];` / `let expandedIds = new Set();` declarations:

```javascript
let addedIds = new Set();
```

Add this function near `refind`:

```javascript
async function addToReadingList(id, e) {
  e.stopPropagation();
  await fetch('/api/entries/' + id + '/add-to-reading-list', {method: 'POST'});
  addedIds.add(id);
  render();
}
```

- [ ] **Step 3: Manually verify in the browser**

Run: `cd /home/jonathon/Box/programming/personal/research-inbox && DB_PATH=/tmp/manual-test2.db GEMINI_API_KEY= TELEGRAM_TOKEN= ~/.venvs/research-inbox/bin/python app.py`

Log a thought via the web UI. Since `GEMINI_API_KEY` is empty, no paper will be auto-found — to test the button, manually mark an entry `found` for this manual check only:

```bash
~/.venvs/research-inbox/bin/python -c "
import os
os.environ['DB_PATH'] = '/tmp/manual-test2.db'
import app
entries = app.get_entries()
app.update_paper(entries[0]['id'], {
    'title': 'Attention Is All You Need', 'authors': 'Ashish Vaswani et al., 2017',
    'arxiv_id': '1706.03762', 'venue': 'cs.CL', 'why': 'test',
})
"
```

Reload `http://localhost:5000/`, expand the entry, confirm:
- The nav shows "Inbox" / "Reading List" with "Inbox" highlighted.
- "+ Add to reading list" button is visible next to "↺ Find another".
- Clicking it turns the button into a disabled "✓ Added" label.
- Visiting `http://localhost:5000/reading-list` shows the paper under "Uncategorized" in "To read", with the original thought text as the "Why" reason.

Stop the server and delete `/tmp/manual-test2.db` when done.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "Add nav and 'Add to reading list' button to the inbox page"
```

---

## Self-Review Notes

- **Spec coverage:** data model (Task 3), `paper_finder.py` additions + refactor (Tasks 1–2), all 6 API routes (Tasks 3–5), shared nav + reading list page UI (Task 6), inbox cross-link button (Task 7), error copy (Global Constraints + Tasks 3/5), testing plan split between automated backend tests (Tasks 1–5) and manual UI verification (Tasks 6–7) — every spec section maps to a task.
- **Type consistency:** `add_reading_list_entry(arxiv_id, title, authors, venue, folder, reason)` signature is identical at its Task 3 definition and both Task 5 and Task 6-adjacent call sites. `get_reading_list_entry`/`update_reading_list_entry`/`delete_reading_list_entry` (Task 4) match their Task 6/7 non-use (UI only calls through HTTP, not these Python functions directly) — no mismatch.
- **No placeholders:** every step has literal, complete code — no "TBD" or "similar to Task N" shortcuts.
