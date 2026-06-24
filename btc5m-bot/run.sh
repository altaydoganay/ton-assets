#!/usr/bin/env bash
# One-command launcher. Creates a venv, installs deps, starts the bot.
# Usage:
#   ./run.sh            # demo (paper) — safe, no money
#   ./run.sh live       # live (real money) — requires .env + confirmation
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
VENV=.venv

if [ ! -d "$VENV" ]; then
  echo "[setup] creating virtualenv..."
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "[setup] installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# load .env if present (for PRIVATE_KEY / BOT_MODE)
if [ -f .env ]; then set -a; . ./.env; set +a; fi

[ -f config.yaml ] || cp config.example.yaml config.yaml

if [ "${1:-demo}" = "live" ]; then
  echo "[setup] installing live SDK (py-clob-client)..."
  pip install -q "py-clob-client>=0.34.0"
  BOT_MODE=live exec python main.py --config config.yaml --i-understand-live
else
  BOT_MODE=demo exec python main.py --config config.yaml
fi
