#!/usr/bin/env bash
# Install the KCT 24-12 hermes agent on a Linux server.
# Usage: ./deploy/deploy.sh [HERMES_HOME]   (default: $HOME/.hermes)
set -euo pipefail

HERMES_HOME="${1:-$HOME/.hermes}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$HERMES_HOME"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

cd "$REPO_DIR"
uv sync --extra messaging

# Ship non-secret config + persona into the profile home.
cp "$REPO_DIR/deploy/config.yaml" "$HERMES_HOME/config.yaml"
cp "$REPO_DIR/deploy/SOUL.md" "$HERMES_HOME/SOUL.md"

if [ ! -f "$HERMES_HOME/.env" ]; then
  echo "WARNING: $HERMES_HOME/.env not found. Create it with:" >&2
  echo "  OPENROUTER_API_KEY=sk-or-..." >&2
  echo "  TELEGRAM_BOT_TOKEN=..." >&2
  chmod 600 "$HERMES_HOME/.env"
fi

export HERMES_HOME
"$REPO_DIR/.venv/bin/hermes" gateway install 2>/dev/null || true
echo "Done. Start with: HERMES_HOME=$HERMES_HOME hermes gateway start"
echo "First run check:  HERMES_HOME=$HERMES_HOME hermes gateway status"