"""
Research Inbox
- Telegram bot: send thoughts from anywhere, they land in the DB
- Flask web app: view inbox, trigger paper-finding via Gemini + arxiv
Run: python app.py
"""

import os, sqlite3, threading, time, logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request, redirect, url_for
import requests
import telebot
from google import genai

from paper_finder import find_paper_data, extract_arxiv_id, fetch_arxiv_by_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_KEY      = os.environ.get("GEMINI_API_KEY", "")
DB_PATH         = os.environ.get("DB_PATH", "inbox.db")
PORT            = int(os.environ.get("PORT", 5000))
# If set, only messages from this Telegram user ID are accepted
ALLOWED_USER_ID = os.environ.get("TELEGRAM_USER_ID", "")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thought     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'new',
                paper_title TEXT,
                paper_authors TEXT,
                paper_arxiv_id TEXT,
                paper_venue TEXT,
                paper_why   TEXT
            )
        """)
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
        db.commit()

def add_entry(thought):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO entries (thought, created_at, status) VALUES (?, ?, ?)",
            (thought, datetime.utcnow().isoformat(), "new")
        )
        db.commit()
        return cur.lastrowid

def get_entries():
    with get_db() as db:
        rows = db.execute("SELECT * FROM entries ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

def get_entry(entry_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None

def update_paper(entry_id, paper):
    with get_db() as db:
        db.execute("""
            UPDATE entries SET
                status          = 'found',
                paper_title     = ?,
                paper_authors   = ?,
                paper_arxiv_id  = ?,
                paper_venue     = ?,
                paper_why       = ?
            WHERE id = ?
        """, (
            paper.get("title"), paper.get("authors"),
            paper.get("arxiv_id"), paper.get("venue"),
            paper.get("why"), entry_id
        ))
        db.commit()

def set_status(entry_id, status):
    with get_db() as db:
        db.execute("UPDATE entries SET status = ? WHERE id = ?", (status, entry_id))
        db.commit()

def delete_entry(entry_id):
    with get_db() as db:
        db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        db.commit()

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

# ── Gemini + arxiv paper-finder ───────────────────────────────────────────────
def _llm_call(prompt):
    client = genai.Client(api_key=GEMINI_KEY)
    response = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
    return response.text

def _http_get(url, max_attempts=1, backoff_seconds=1):
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return requests.get(url, timeout=30).text
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(backoff_seconds)
    raise last_exc

def find_paper(entry_id, thought):
    set_status(entry_id, "loading")
    try:
        result = find_paper_data(thought, _llm_call, _http_get)
        if result["status"] == "found":
            update_paper(entry_id, result["paper"])
            log.info(f"Paper found for entry {entry_id}: {result['paper'].get('title')}")
        else:
            set_status(entry_id, "error")
            log.error(f"No verifiable paper found for entry {entry_id}")
    except Exception as e:
        log.error(f"Error finding paper for entry {entry_id}: {e}")
        set_status(entry_id, "error")

def find_paper_async(entry_id, thought):
    t = threading.Thread(target=find_paper, args=(entry_id, thought), daemon=True)
    t.start()

# ── Flask web app ─────────────────────────────────────────────────────────────
app = Flask(__name__)

def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

@app.route("/")
def index():
    entries = get_entries()
    return render_template("index.html", entries=entries, active_page="inbox", gemini_enabled=bool(GEMINI_KEY))

@app.route("/reading-list")
def reading_list_page():
    return render_template("reading_list.html", active_page="reading-list")

@app.route("/api/entries", methods=["GET"])
def api_entries():
    return jsonify(get_entries())

@app.route("/api/entries", methods=["POST"])
def api_add():
    data = request.json
    thought = (data.get("thought") or "").strip()
    if not thought:
        return jsonify({"error": "thought required"}), 400
    entry_id = add_entry(thought)
    return jsonify({"id": entry_id}), 201

@app.route("/api/entries/<int:entry_id>/attach-paper", methods=["POST"])
def api_attach_paper(entry_id):
    entry = get_entry(entry_id)
    if not entry:
        return jsonify({"error": "not found"}), 404

    data = _json_body()
    arxiv_link = (data.get("arxiv_link") or "").strip()
    why = (data.get("why") or "").strip() or None

    arxiv_id = extract_arxiv_id(arxiv_link)
    if not arxiv_id:
        return jsonify({"error": "Couldn't find an arxiv ID in that link/text."}), 400

    try:
        verified = fetch_arxiv_by_id(arxiv_id, _http_get)
    except Exception as e:
        log.error(f"Error reaching arxiv for id {arxiv_id}: {e}")
        return jsonify({"error": "Couldn't reach arxiv to verify that link — check your connection and try again."}), 400
    if not verified:
        return jsonify({"error": "That arxiv ID doesn't seem to exist — check the link and try again."}), 400

    update_paper(entry_id, {
        "title": verified["title"], "authors": verified["authors"],
        "arxiv_id": verified["arxiv_id"], "venue": verified["venue"],
        "why": why,
    })
    return jsonify({"ok": True})

@app.route("/api/entries/<int:entry_id>/refind", methods=["POST"])
def api_refind(entry_id):
    entry = get_entry(entry_id)
    if not entry:
        return jsonify({"error": "not found"}), 404
    if GEMINI_KEY:
        find_paper_async(entry_id, entry["thought"])
    return jsonify({"ok": True})

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

@app.route("/api/entries/<int:entry_id>", methods=["DELETE"])
def api_delete(entry_id):
    delete_entry(entry_id)
    return jsonify({"ok": True})

@app.route("/api/reading-list", methods=["GET"])
def api_reading_list_get():
    return jsonify(get_reading_list_entries())

@app.route("/api/reading-list", methods=["POST"])
def api_reading_list_add():
    data = _json_body()
    arxiv_link = (data.get("arxiv_link") or "").strip()
    folder = (data.get("folder") or "").strip() or None
    reason = (data.get("reason") or "").strip() or None

    arxiv_id = extract_arxiv_id(arxiv_link)
    if not arxiv_id:
        return jsonify({"error": "Couldn't find an arxiv ID in that link/text."}), 400

    try:
        entry = fetch_arxiv_by_id(arxiv_id, _http_get)
    except Exception as e:
        log.error(f"Error reaching arxiv for id {arxiv_id}: {e}")
        return jsonify({"error": "Couldn't reach arxiv to verify that link — check your connection and try again."}), 400
    if not entry:
        return jsonify({"error": "That arxiv ID doesn't seem to exist — check the link and try again."}), 400

    row_id = add_reading_list_entry(
        arxiv_id=entry["arxiv_id"], title=entry["title"],
        authors=entry["authors"], venue=entry["venue"],
        folder=folder, reason=reason,
    )
    return jsonify({"id": row_id}), 201

@app.route("/api/reading-list/<int:entry_id>", methods=["PATCH"])
def api_reading_list_update(entry_id):
    if not get_reading_list_entry(entry_id):
        return jsonify({"error": "not found"}), 404
    update_reading_list_entry(entry_id, _json_body())
    return jsonify({"ok": True})

@app.route("/api/reading-list/<int:entry_id>", methods=["DELETE"])
def api_reading_list_delete(entry_id):
    if not get_reading_list_entry(entry_id):
        return jsonify({"error": "not found"}), 404
    delete_reading_list_entry(entry_id)
    return jsonify({"ok": True})

# ── Telegram bot ──────────────────────────────────────────────────────────────
def _safe_reply(bot, message, text):
    try:
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"Telegram reply failed: {e}")

def run_bot():
    if not TELEGRAM_TOKEN:
        log.warning("No TELEGRAM_TOKEN set — bot disabled")
        return

    bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

    def allowed(message):
        if not ALLOWED_USER_ID:
            return True
        return str(message.from_user.id) == ALLOWED_USER_ID

    @bot.message_handler(commands=["start", "help"])
    def handle_start(message):
        if not allowed(message):
            return
        _safe_reply(bot, message,
            "Research Inbox bot.\n\n"
            "Just send me any thought, question, or idea you want to come back to — "
            "I'll save it and I'll find you a paper to read.\n\n"
            "Open your inbox at http://localhost:{}/".format(PORT)
        )

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def handle_thought(message):
        if not allowed(message):
            _safe_reply(bot, message, "Not authorised.")
            return
        thought = message.text.strip()
        if not thought:
            return
        add_entry(thought)
        _safe_reply(bot, message, "Logged. Attach a paper from your inbox at http://localhost:{}/".format(PORT))

    log.info("Telegram bot starting (polling)…")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            log.error(f"Bot polling error: {e} — restarting in 5s")
            time.sleep(5)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()

    if not GEMINI_KEY:
        log.warning("No GEMINI_API_KEY set — paper-finding disabled")
    if not TELEGRAM_TOKEN:
        log.warning("No TELEGRAM_TOKEN set — Telegram bot disabled")

    # Bot runs in a background thread; Flask runs in the main thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    log.info(f"Web app running at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
