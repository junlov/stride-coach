# Project agent memory

- Setup and offline checks: see CONTRIBUTING.md (`make dev` for synthetic setup), README.md, and .github/workflows/ci.yml.
- PostgreSQL schema, migrations, Compose deployment, legacy import, and backup/restore: see docs/self-hosting.md and src/stride_coach/db_models.py. For test database requirements, see CONTRIBUTING.md.
- Run detail/import schema, GPS privacy, FIT archives, and resumable backfill: docs/activity-data.md. Synthetic end-to-end proof and storage measurements: examples/run_data_demo.py.
- Training rules and provenance: docs/training-rules.md; code lives in src/stride_coach/engine.py and adaptation.py.
- Garmin connection, token storage, and recovery rules: README.md, docs/architecture.md, and src/stride_coach/garmin_auth.py. Tests/CI use synthetic Garmin responses only.
- Keep tokens, personal activity data, database backups, legacy SQLite files, and local demo outputs untracked. The offline demo uses synthetic data only.
- CLI, MCP, and HTTP share src/stride_coach/service.py. MCP stays read-only; CLI/API Garmin writes require explicit apply. Remote MCP and stdio setup: README.md, "Connect Claude to your coach". Synthetic HTTP/MCP proof: examples/api_demo.py.
- Mobile API contract: docs/openapi.json, regenerated with uv run python examples/export_openapi.py. See README.md for bearer auth and HTTPS deployment.

- Automatic sync, resumable history imports, and persisted adjustment evidence: see docs/self-hosting.md#automatic-sync-and-import-recovery and examples/sync_demo.py.

- Mobile app setup, generated API types, Expo checks, and synthetic loopback proof: see app/README.md and app/package.json. Keep API types generated from docs/openapi.json.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
