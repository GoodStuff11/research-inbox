#!/usr/bin/env bash
# Research Inbox — first-time setup
set -e

echo "=== Research Inbox setup ==="

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found. Install it first."
  exit 1
fi

# venv lives outside this directory: this folder is synced via Box Drive,
# which doesn't support symlinks, and `python3 -m venv` always symlinks lib64 -> lib.
VENV_DIR="${VENV_DIR:-$HOME/.venvs/research-inbox}"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  echo "Created virtual environment at $VENV_DIR."
fi

source "$VENV_DIR/bin/activate"
pip install -q -r requirements.txt
echo "Dependencies installed."

# .env
if [ ! -f ".env" ]; then
  cat > .env << 'ENV'
# Paste your Telegram bot token here (from @BotFather):
TELEGRAM_TOKEN=

# Your Gemini API key (free tier, from https://aistudio.google.com/apikey):
GEMINI_API_KEY=

# Optional: your Telegram user ID (from @userinfobot) to restrict the bot to you only:
TELEGRAM_USER_ID=

# Port for the web app:
PORT=5000
ENV
  echo ""
  echo "Created .env — fill in your TELEGRAM_TOKEN and ANTHROPIC_API_KEY, then run:"
  echo "  ./run.sh"
else
  echo ".env already exists."
  echo ""
  echo "To start: ./run.sh"
fi
