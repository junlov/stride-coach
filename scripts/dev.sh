#!/usr/bin/env bash
# Local synthetic environment only. Never read deployment .env credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in docker uv; do
  command -v "$tool" >/dev/null || { echo "Install $tool first; see CONTRIBUTING.md" >&2; exit 1; }
done
umask 077
mkdir -p .local/dev
export DATABASE_URL="postgresql://postgres:synthetic-dev-password@127.0.0.1:${DEV_DATABASE_PORT:-55440}/stride_dev"
export STRIDE_COACH_TOKENS="$PWD/.local/dev/garmin"
export STRIDE_COACH_CORS_ORIGINS=""
uv sync --locked
if [ ! -s .local/dev/api-token ]; then
  uv run python -c 'import secrets; print(secrets.token_urlsafe(32))' > .local/dev/api-token
fi
export STRIDE_COACH_API_TOKEN="$(cat .local/dev/api-token)"
bash scripts/dev-compose.sh up -d --wait
uv run stride-coach db upgrade
uv run python scripts/seed_dev.py
echo "Synthetic API: http://127.0.0.1:${DEV_API_PORT:-8001}"
echo "Phone/simulator token: .local/dev/api-token (keep private). Ctrl-C stops the API."
exec uv run stride-coach serve --host 127.0.0.1 --port "${DEV_API_PORT:-8001}"
