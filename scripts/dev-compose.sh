#!/usr/bin/env bash
# Use the same checkout-scoped project for every dev database operation.
set -euo pipefail
cd -P "$(dirname "$0")/.."
project="${DEV_PROJECT_NAME:-}"
if [ -z "$project" ]; then
  checkout_hash="$(python3 -c 'import hashlib, os; print(hashlib.sha256(os.fsencode(os.getcwd())).hexdigest()[:12])')"
  project="stride-dev-$checkout_hash"
fi
exec docker compose -p "$project" -f compose.dev.yaml "$@"
