#!/usr/bin/env bash
# Loads .env and starts the app
set -e
cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  echo "No .env found. Run setup.sh first."
  exit 1
fi

# Export variables from .env (skip comments and blanks)
set -a
source .env
set +a

VENV_DIR="${VENV_DIR:-$HOME/.venvs/research-inbox}"
if [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

exec python app.py
