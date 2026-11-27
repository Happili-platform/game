#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export GAME_DB_PATH="${GAME_DB_PATH:-$HOME/.local/share/game/game.db}"
export GAME_AUTH_MODE="${GAME_AUTH_MODE:-password}"
export GAME_DEMO_DATA=false
export GAME_VAULT_KEY_PATH="${GAME_VAULT_KEY_PATH:-$HOME/.config/game/master.key}"
export PYTHONPATH="$ROOT/src"

if [[ ! -f "$GAME_DB_PATH" ]]; then
    echo "ERROR: GAMe database not found: $GAME_DB_PATH"
    echo "Refusing to create a new database."
    exit 1
fi

if [[ ! -f "$GAME_VAULT_KEY_PATH" ]]; then
    echo "ERROR: GAMe vault key not found."
    exit 1
fi

echo "GAMe database: $GAME_DB_PATH"
echo "Starting GAMe on 127.0.0.1:8000"

exec python -m uvicorn game.main:app \
    --host 127.0.0.1 \
    --port 8000
