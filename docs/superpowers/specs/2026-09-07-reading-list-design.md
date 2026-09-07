# Reading List page — design

## Purpose

research-inbox currently has one page: capture a thought via Telegram or the
web UI, get a Gemini-suggested, arxiv-verified paper back. This adds a second
page — a reading list — where papers can be organized by folder, tracked as
to-read/read/not-interested, and annotated with notes. The two pages are
independent: the inbox is for capturing ideas and getting a recommendation;
the reading list is a queue of papers you've decided to actually read, however
they got there (copied from an inbox recommendation, or added directly by
pasting an arxiv link).

## Data model

New table in the existing `inbox.db` SQLite database:

```sql
CREATE TABLE reading_list (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    authors     TEXT,
    venue       TEXT,
    folder      TEXT,              -- NULL = uncategorized
    reason      TEXT,               -- "why I want to read this", optional
    thoughts    TEXT,               -- notes, editable any time, optional
    status      TEXT NOT NULL DEFAULT 'to_read',  -- 'to_read' | 'read' | 'not_interested'
    added_at    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
```

Separate table from `entries` (the inbox table) rather than shared columns:
inbox entries always originate from a `thought`; reading-list entries don't
have to (a pasted arxiv link has no associated thought). Mixing the two would
mean a pile of nullable columns and mixed-purpose queries on one table.

`folder` is a flat string, no separate folders table — folders are created
implicitly by typing a new name in the add form. The set of "existing
folders" for autocomplete is `SELECT DISTINCT folder FROM reading_list WHERE
folder IS NOT NULL`.

No foreign key to `entries`. Once a paper is copied into the reading list,
it's an independent row — deleting the inbox entry later doesn't affect it.

## `paper_finder.py` additions

Two new pure functions, unit-tested the same way as the existing ones
(dependency-injected `http_get`, no real network calls in tests):

```python
def extract_arxiv_id(text: str) -> str | None:
    """Bare id ('1706.03762'), an abs/pdf URL, with or without a version
    suffix. Returns None if no id can be found."""

def fetch_arxiv_by_id(arxiv_id: str, http_get) -> dict | None:
    """Direct id_list lookup — no candidate title to fuzzy-match against,
    just: does this id exist? Returns the parsed entry dict, or None if the
    feed is empty."""
```

`fetch_arxiv_by_id` factors out the `id_list`-lookup half of
`verify_candidate`'s current logic. `verify_candidate` is refactored to call
it internally for its id-lookup branch, so there is exactly one
implementation of "fetch an arxiv entry by id," shared by the inbox's
LLM-verification path and the reading list's direct-link path. This is a pure
refactor — `verify_candidate`'s existing tests must keep passing unchanged.

## API routes (`app.py`)

```
GET  /reading-list                          — renders the reading list page
GET  /api/reading-list                      — JSON list of all rows
POST /api/reading-list                      — add a paper
                                               body: {arxiv_link, folder, reason}
                                               → extract_arxiv_id → fetch_arxiv_by_id → insert (status='to_read')
                                               → 400 if either lookup step fails
PATCH /api/reading-list/<id>                — partial update: any of {status, folder, thoughts}
                                               → 404 if id doesn't exist
DELETE /api/reading-list/<id>               — remove a row

POST /api/entries/<id>/add-to-reading-list  — inbox-page cross-link button
                                               reads the inbox entry's paper_* fields + thought
                                               inserts a reading_list row (folder=NULL, reason=entry.thought, status='to_read')
                                               → 400 if the entry's status != 'found' (no matched paper yet)
```

`PATCH` is one generic endpoint for status changes, folder reassignment, and
thoughts edits rather than three separate endpoints — all three are "update
one or two columns on one row," so one handler covers it without
duplication.

## Pages & UI

**Shared nav:** a small header/nav (two links: "Inbox" / "Reading List") via
a shared `templates/_nav.html` include in both pages — plain server-rendered
links, no SPA framework.

**Reading list page (`templates/reading_list.html`):**
- **Add form** at the top: arxiv link (text input), folder (text input with
  `<datalist>` autocomplete populated from existing folder names), reason
  (text input), Add button. Inline error message if the link doesn't
  resolve.
- **To Read** section: grouped by folder — "Uncategorized" group first, then
  other folders alphabetically. Each entry shows title (linked to arxiv),
  authors, reason, a thoughts `<textarea>` (saved via `PATCH` on blur),
  "Finished reading" and "Not interested" buttons.
- **Read** section: flat list, no folder grouping (it's an archive, not an
  active queue) — same thoughts textarea.
- **Not Interested** section: flat list, collapsed by default (`<details>`),
  since it's rarely browsed.

**Inbox page (`templates/index.html`):** one new button per entry, "Add to
reading list," shown once `status == 'found'`. Click →
`POST /api/entries/<id>/add-to-reading-list`, no confirmation dialog (matches
the low-friction goal of the app). On success the button becomes a
disabled "✓ Added" label. Clicking twice is harmless server-side (just
inserts a duplicate row) but the UI discourages it.

## Error handling

- **Bad/unresolvable arxiv link on add:** `extract_arxiv_id` returns `None`
  → 400 "Couldn't find an arxiv ID in that link/text." `fetch_arxiv_by_id`
  returns `None` → 400 "That arxiv ID doesn't seem to exist — check the link
  and try again." Both surface as an inline error in the add form. No
  retry-loop (unlike the LLM path, this is a single deterministic lookup —
  on failure, fix the input and resubmit).
- **Cross-link button on an entry with no matched paper yet:** 400 server-side;
  client-side the button isn't rendered until `status == 'found'`.
- **PATCH/DELETE with an unknown id:** 404, matching the existing
  `/api/entries/<id>/refind` pattern.

## Testing plan (TDD, matching existing project convention)

- **`paper_finder.py` additions**, extending `tests/test_paper_finder.py`:
  - `extract_arxiv_id`: bare id, `abs` URL, `pdf` URL with version suffix,
    garbage text → `None`.
  - `fetch_arxiv_by_id`: found → entry dict; empty feed → `None`.
  - `verify_candidate` refactor: existing tests must keep passing unchanged.
- **`app.py` DB/route logic**, new `tests/test_app.py` using Flask's test
  client against a temp SQLite file (`DB_PATH` pointed at a tmp path per
  test), following the existing project's dependency-injection style (no
  real network calls in tests). Covers: add with a valid link, add with a
  bad link (400), PATCH status transitions, PATCH thoughts, add-to-reading-
  list from an inbox entry (including the 400 for no matched paper yet),
  delete.
- **UI** (`reading_list.html`, nav, inbox button): manual browser testing
  only, matching this project's existing convention — no JS test framework
  is introduced for what remains a personal, single-user tool.

## Out of scope (explicitly, YAGNI)

- Nested folders, a folder management UI, multi-folder-per-paper — flat,
  inline-created, single folder per paper only.
- Re-foldering a paper after it's added — the UI has no "move to folder"
  control in v1. `PATCH` accepts a `folder` field at the API layer (useful
  for a future feature or manual use), but no UI element calls it with a new
  folder value; folder is effectively set once, at add time.
- Undo for "finished reading" / "not interested" — hand-editable later if
  ever needed, no dedicated undo button.
- Any multi-user / auth concerns — this stays a local, laptop-only,
  single-user Flask app, matching the existing project's hosting decision.
