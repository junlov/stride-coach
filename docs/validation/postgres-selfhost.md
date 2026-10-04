# PostgreSQL and self-hosting validation

Executed on 2026-10-04 in the disposable task worktree with Docker server 29.4.0,
PostgreSQL 17.6, host Python 3.11.16, and image Python 3.13.7. All training and Garmin
records were synthetic. Openship and real Garmin SSO/writes were not exercised.

## Live proof

Exact repeatable packaged proof command:

```sh
uv run python examples/selfhost_proof.py
```

Trimmed output:

```text
clean install: healthy, unauthenticated data rejected, 36 sessions, preview only
synthetic state: one activity, durable pending upload, private session generation
restart: plan, activity, pending upload, and Garmin volume persisted
upgrade: startup migrated 0001 to 0002; plan, activity, and pending intent preserved
CLI: Database schema is current.
backup: pg_dump and pg_restore preserved the synthetic plan
proof complete: zero Garmin calls, no published image, no live account
cleanup: disposable Compose containers, network, and volumes removed
```

The script executes `docker compose up -d --build --wait`, restarts the API and PostgreSQL,
and compares the returned plan/status with the original. It checks the stored activity,
pending intent, and private session generation after restart. To exercise a pending migration,
it stops the API, moves only its disposable schema to packaged revision 0001, then starts the
API and verifies migration to 0002 with the records intact. This is a schema upgrade proof,
not a claim that a previous application release was deployed. It also runs `pg_dump -Fc`
and `pg_restore --clean --if-exists --no-owner --exit-on-error` within that disposable project.
Generated secrets are kept out of the report. No image was pushed to a registry.

The Docker proof initially found a timestamp name error during sync, which was fixed, and
a Path/string mismatch in the proof harness, which was fixed before the successful run.

Additional real CLI and loopback commands against the disposable database:

```sh
export TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:55439/stride_test
uv run python examples/offline_demo.py --directory .local/postgres-offline-proof
uv run python examples/api_demo.py --directory .local/postgres-api-proof
uv run python examples/garmin_demo.py --directory .local/postgres-garmin-proof
cd app
npm run proof
```

Trimmed output:

```text
init: 36 run-walk sessions, synthetic baseline
sync: 1 synthetic completed run
adapt: simulated Monday 2026-09-28, factor 0.75, applied once
status: one persisted adjustment; offline loop complete
server: loopback HTTP workflow complete
renewal: expired token renewed once; no password login
MFA: two HTTP requests completed with one password call
disconnect: stored tokens removed; status disconnected
proof: real loopback HTTP complete; zero live Garmin calls
proof: mobile TypeScript client completed real FastAPI loopback workflow
```

## Automated checks

```sh
uv run ruff check .
uv run ruff format --check .
TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:55439/stride_test \
  uv run pytest --cov=stride_coach --cov-fail-under=90
uv run python examples/export_openapi.py
cd app
npm run generate:api
npm run typecheck
npm run lint
```

Results: Ruff passed, 41 Python files formatted, 265 tests passed, 96.61% coverage;
TypeScript generation, typecheck, and lint passed. Regeneration left `docs/openapi.json`
and `app/src/api/schema.ts` unchanged. The operator health probe is excluded from the
mobile data contract. The existing Starlette/httpx deprecation warning remains.

Focused PostgreSQL checks cover typed constraints, numeric round-trip precision, schema/model
drift, atomic adaptation rollback, prior-revision startup upgrades, unknown-schema refusal,
read-only MCP, non-sensitive readiness failures, and configuration secret redaction. The
legacy importer is exercised through the real CLI against PostgreSQL, including IDs,
activities, applied adjustments, scheduled entries, pending writes, and coverage. Repeated
imports, unknown metadata, and orphan ledger entries are rejected without partial records.
The source SQLite file remains unchanged. The pre-existing Garmin lost-response and sync
concurrency tests also run against PostgreSQL.
