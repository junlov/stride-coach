# Project agent memory

- Setup and offline checks: see README.md, pyproject.toml, and .github/workflows/ci.yml.
- PostgreSQL schema, migrations, Compose deployment, legacy import, and backup/restore: see docs/self-hosting.md and src/stride_coach/db_models.py. Tests and demos require a disposable TEST_DATABASE_URL.
- Training rules and provenance: docs/training-rules.md; code lives in src/stride_coach/engine.py and adaptation.py.
- Garmin connection, token storage, and recovery rules: README.md, docs/architecture.md, and src/stride_coach/garmin_auth.py. Tests/CI use synthetic Garmin responses only.
- Keep tokens, personal activity data, database backups, legacy SQLite files, and local demo outputs untracked. The offline demo uses synthetic data only.
- CLI, MCP, and HTTP share src/stride_coach/service.py. MCP stays read-only; CLI/API Garmin writes require explicit apply.
- Mobile API contract: docs/openapi.json, regenerated with uv run python examples/export_openapi.py. See README.md for bearer auth and HTTPS deployment.

- Mobile app setup, generated API types, Expo checks, and synthetic loopback proof: see app/README.md and app/package.json. Keep API types generated from docs/openapi.json.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
