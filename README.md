# Research Inbox

Capture research thoughts from anywhere via Telegram. View your inbox and read papers on your laptop.

## How it works

- **Telegram bot** → message a thought from your phone mid-talk, on the train, anywhere
- **Web app** → open `localhost:5000` on your laptop to see all your entries, with a paper recommended for each one
- **SQLite** → everything persists locally in `inbox.db`

## Setup (5 minutes)

### 1. Get a Telegram bot token

1. Open Telegram and message **@BotFather**
2. Send `/newbot`, give it a name (e.g. "Research Inbox") and a username (e.g. `myresearchinbox_bot`)
3. Copy the token it gives you

### 2. Get your Gemini API key (free)

Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → create an API key. This uses Gemini's free tier — no billing needs to be enabled.

### 3. (Optional) Find your Telegram user ID

Message **@userinfobot** on Telegram. It replies with your numeric user ID. Set this in `.env` so only you can use the bot.

### 4. Install and configure

```bash
cd research-inbox
chmod +x setup.sh run.sh
./setup.sh
```

Edit `.env` with your tokens:

```
TELEGRAM_TOKEN=your_bot_token_here
GEMINI_API_KEY=your_key_here
TELEGRAM_USER_ID=your_numeric_id   # optional but recommended
PORT=5000
```

### 5. Run

```bash
./run.sh
```

Then open **http://localhost:5000** in your browser and bookmark it.

### Or run it with Docker

```bash
docker compose up -d      # build and start in the background
docker compose logs -f    # follow logs
docker compose down       # stop
```

`inbox.db` persists in `./data/` on your machine, so rebuilding the image (e.g. after a code change) doesn't lose your entries.

## Usage

**Capturing a thought (from anywhere):**
- Message your bot on Telegram: *"Feshbach resonance came up in that superconductivity talk — what is it exactly?"*
- The bot replies "Logged. Finding a paper for you…"
- Within ~10 seconds, your inbox has a paper recommendation waiting

**Reading (on your laptop):**
- Open http://localhost:5000
- Each entry shows the paper title (linked to arxiv), authors, and a personalised explanation of why that paper answers your specific question
- Gemini suggests the paper; before it's shown, the app checks it's a real, verifiable paper on arxiv (retrying once if the first suggestion can't be verified)
- Click "Find another" to get a different recommendation

**Auto-start on login (macOS):**

Create `~/Library/LaunchAgents/research-inbox.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>research-inbox</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/path/to/research-inbox/run.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/research-inbox.log</string>
  <key>StandardErrorPath</key><string>/tmp/research-inbox.log</string>
</dict>
</plist>
```

Then: `launchctl load ~/Library/LaunchAgents/research-inbox.plist`

## Files

```
research-inbox/
  app.py          — Flask web app + Telegram bot (one process)
  paper_finder.py — Gemini candidate + arxiv verification (provider-agnostic, unit tested)
  tests/
    test_paper_finder.py
  templates/
    index.html    — the inbox UI
  requirements.txt
  setup.sh        — first-time setup
  run.sh          — start the app
  inbox.db        — your data (created on first run)
  .env            — your secrets (never commit this)
```
