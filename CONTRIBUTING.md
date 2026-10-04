# Contributing to Stride Coach

Small, focused improvements are welcome: docs, reproducible bug reports, tests, accessibility,
and running-coach features. See [ROADMAP.md](ROADMAP.md) for direction and [SECURITY.md](SECURITY.md)
for vulnerabilities. This is an MIT project. Submit only work you have the right to license
under MIT. Do not copy copyleft code (including GPL or AGPL), commercial plans, proprietary
interfaces, or unlicensed assets. Preserve required notices for compatible third-party work.

## One-command development setup

Install Git, Docker with Compose (running), [uv](https://docs.astral.sh/uv/getting-started/installation/),
Python 3.11+, and Make. Linux and macOS are supported. Fork and clone the repository, then from
its root run:

```sh
make dev
```

This installs locked Python dependencies, starts a dedicated PostgreSQL container, applies
migrations, seeds a synthetic 12-week return-to-running plan and one synthetic run, and starts
the API in the foreground at `http://127.0.0.1:8001`. No Garmin account is required. It retains
an existing dev plan on subsequent runs. The generated bearer token is in `.local/dev/api-token`.
Use synthetic data here, never a production database or Garmin credentials.

The Compose project is `stride-dev`, database port `55440`, and persistent volume
`stride-dev_dev-postgres`. The script ignores deployment database/token environment values
and uses its own local token directory. `.env` self-hosting credentials are not needed.
If ports are occupied, run `DEV_DATABASE_PORT=55441 DEV_API_PORT=8002 make dev`; use those same
values on subsequent runs. Run only one `make dev` at a time per checkout/database.

In another terminal:

```sh
curl --fail http://127.0.0.1:8001/health
```

Expect `{"status":"ready"}`. Press Ctrl-C to stop the API. Stop the dev database with:

```sh
make dev-stop
```

To deliberately discard **only the synthetic dev database**, stop the API first, then run
`docker compose -p stride-dev -f compose.dev.yaml down -v`. The next `make dev` seeds a fresh
plan. Never run a volume-deletion command against a self-hosted deployment.

## Run the app

Install Node 22.13+ and follow [app/README.md](app/README.md#local-development):

```sh
cd app
npm ci
npm start -- --go
```

Use an SDK 57-compatible Expo Go. In Settings, set `http://127.0.0.1:8001` for the iOS simulator,
or `http://10.0.2.2:8001` for the Android emulator, and paste the token from `.local/dev/api-token`
at the repository root. Test and save the connection. The dev plan already exists, so open
Today/Plan rather than submitting another goal. To test empty goal onboarding, use a fresh
self-hosting setup instead. For physical phones, provide a trusted HTTPS reverse proxy to
port 8001 and use its hostname; the server intentionally binds to loopback.

## Checks before a PR

Use a separate disposable database for tests. Tests allocate and clean up isolated schemas.
Run these commands from the repository root, as CI does:

```sh
docker compose -p stride-tests -f compose.test.yaml up -d --wait
export TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:55439/stride_test
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=stride_coach --cov-fail-under=90
```

For mobile changes, from `app/`:

```sh
npm ci
npm run generate:api
npm run typecheck
npm run lint
npm test -- --ci
npm run export:mobile
npm run proof
```

`npm run proof` uses `TEST_DATABASE_URL` from the same terminal and real loopback HTTP with
synthetic data. See [offline proofs](docs/self-hosting.md#local-offline-tests-and-synthetic-proof).
After an API change, regenerate `docs/openapi.json` with
`uv run python examples/export_openapi.py`, then regenerate app types. Do not hand-edit generated
types. Keep Garmin calls synthetic in tests. Never commit tokens, activity exports, database
backups, `.env`, or `.local` output.

## Branches and pull requests

Create a descriptive branch such as `docs/setup-guide` or `fix/goal-validation` from the default
branch. Keep each PR focused, explain the user problem and changed behavior, and fill in the
PR template's Job check. Include exact verification commands, relevant results, and screenshots
for UI changes with personal details removed. Documentation-only changes need link/command
checks; run the relevant test suites when behavior changes. Use concise imperative commit
subjects. Maintainers review and merge; do not include unrelated formatting or lockfile changes.
