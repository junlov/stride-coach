# Self-hosting Stride Coach

Run one API instance and PostgreSQL 17. The server owns the Garmin connection, including
login, MFA, and bounded token renewal. There is no background sync: **Sync** pulls the latest
runs when requested. The mobile app connects to the API over HTTPS.

## Install with Compose

Install Docker Engine and Docker Compose, clone this repository, then:

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))'
# Edit .env: use the first generated value as STRIDE_COACH_API_TOKEN,
# the second as POSTGRES_PASSWORD. Set TZ to your local IANA timezone.
docker compose up -d --build --wait
curl --fail http://127.0.0.1:8000/health
```

Expected health response: `{"status":"ready"}`. Startup applies packaged Alembic migrations
before accepting requests. A newer or unknown schema stops startup. Configuration errors
identify the invalid field without printing its value. The server rejects short or placeholder
API secrets, database passwords shorter than 16 characters, invalid timezones, and wildcard
CORS origins. Generate independent random secrets rather than human-chosen passwords.

The API image uses pinned Python and uv versions, installs the locked production dependencies
in a build stage, and runs as UID/GID `10001:10001`. Named volumes persist PostgreSQL and the
private Garmin session directory. PostgreSQL has no published port. The API binds to host
loopback by default. Both services have healthchecks and restart policies.

The Compose file builds locally; this project does not publish an image. Keep the checkout
and its exact commit available so upgrades and rollback use a known version. Do not scale
the API: MFA state is held by one process. All writers must use the same PostgreSQL database
and Garmin session volume. Use a direct PostgreSQL connection or session-mode pooler;
transaction-mode pooling cannot preserve the advisory locks used across committed writes.

## Environment and HTTPS

| Variable | Use |
| --- | --- |
| `STRIDE_COACH_API_TOKEN` | Required generated bearer secret, at least 32 characters |
| `POSTGRES_PASSWORD` | Required independent generated database secret; use hex for Compose URL interpolation |
| `POSTGRES_USER`, `POSTGRES_DB` | Bundled database role and database, default `stride` |
| `DATABASE_URL` | Optional override for external PostgreSQL; otherwise Compose constructs it from the above credentials |
| `STRIDE_COACH_TOKENS` | Dedicated session volume path, default `/data/garmin` in Compose |
| `STRIDE_COACH_SYNC_ENABLED` | Daily automatic Garmin reads, `true` by default; `false` disables the daily schedule only |
| `STRIDE_COACH_SYNC_TIME` | Daily `HH:MM` time in `TZ`, default `06:00`; catches up once after startup if due |
| `STRIDE_COACH_SYNC_OPEN_HOURS` | Minimum interval between app-open sync attempts, default `6` hours, shared across devices |
| `STRIDE_COACH_IMPORT_PAGE_DELAY` | Minimum delay between history pages, default `1` second (range 0.1 to 60) |
| `TZ` | Athlete's IANA timezone, default `UTC`; determines local coaching dates |
| `PORT` | Compose host port, default `8000`; container port stays `8000` |
| `BIND_ADDRESS` | Host bind address, default `127.0.0.1` |
| `STRIDE_COACH_CORS_ORIGINS` | Optional comma-separated exact HTTP(S) web origins without trailing slashes |

Outside Compose, `DATABASE_URL` is required. The CLI also accepts `--database-url`.
Use `postgresql://` or `postgresql+psycopg://`. URL-encode special characters in credentials.
Use provider-required TLS options such as `?sslmode=verify-full&sslrootcert=/path/to/ca.pem`
for a remote database. `PORT` also sets the default port for the direct `serve` command.
Native mobile clients do not need CORS. Browser clients need their exact origin.

Terminate HTTPS at your platform proxy or a reverse proxy on the Docker host. For example,
Caddy on that host can proxy to the loopback binding:

```caddyfile
coach.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Use your own hostname and certificate configuration. A proxy on the same Docker network can
instead reach `api:8000`. Keep PostgreSQL and the API origin private. Disable request-body and
Authorization logging at the proxy. The phone's base URL is `https://coach.example.com`.
All data routes and `/openapi.json` require bearer authentication. Only `GET /health` is public;
it checks database access and the exact schema version and returns only `ready` or `unavailable`
(HTTP 503). It never calls Garmin and does not require an existing plan or Garmin login.

## First run and Garmin

Follow the [mobile connection guide](../app/README.md#connect-your-server) to connect your phone and Garmin during first-run setup.
For terminal sign-in, use the same container and volume:

```sh
docker compose exec api python -m stride_coach.cli garmin login
docker compose exec api python -m stride_coach.cli garmin status
```

Before creating your plan, use **Import past runs** after connecting Garmin or in **Settings**.
Choose 12 weeks, 6 calendar months, or everything. Wait for Complete to include the imported
runs in your initial fitness estimate, then create the goal. You can also import from the CLI
with `sync --since YYYY-MM-DD --until YYYY-MM-DD`. Garmin push and removal remain previews until you explicitly
confirm a live action. Never use real Garmin writes for deployment healthchecks.

Garmin's API is unofficial. The synthetic install proof does not establish live login acceptance
from a hosting provider. Follow the [Garmin connection and recovery guide](../README.md#garmin-authentication-and-first-live-check)
if login or renewal fails. Passwords are never retained, so recovery may require another explicit
login. Losing the session volume requires reconnecting, even if the database is intact.

## Move from SQLite

Stop the old application and all writers first. Preserve a backup of its SQLite file and its
Garmin token directory. Use a fresh PostgreSQL database. Do not create a new goal before import.

```sh
docker compose up -d postgres
docker compose run --rm --user 0 -v /absolute/path/coach.db:/import/coach.db:ro api \
  db import-sqlite /import/coach.db
docker compose up -d --wait api
```

The one-off import runs as root to read the owner-only legacy file through its read-only mount;
the API continues to run as UID 10001. The import reads SQLite without modifying it, validates the records, then imports the plan,
activities, adjustments, scheduled ledger, pending create/schedule intents, and sync coverage in
one PostgreSQL transaction. IDs and ownership markers remain unchanged. Matches are recomputed
from the imported plan and activities. Empty or absent complete-day coverage remains incomplete;
import does not grant permission to adapt unsynced weeks. The target must be empty. A repeated
import, invalid record, unknown metadata, or orphan foreign key stops the import without partial
data. Inspect the count summary, plan, and status before allowing live Garmin writes.

Restore the old dedicated Garmin directory into the new session volume with its `.stride-coach`
ownership marker and `connection.tokens.json`, or connect Garmin again. Adjust ownership to
`10001:10001`, directory permissions to `700`, and file permissions to `600`. Do not run the old
and new deployments at the same time. SQLite paths and `STRIDE_COACH_DB` are no longer runtime
configuration. Keep the legacy backup until the migration has been verified.

## Upgrade

Stop writes, make the backup below, and check out the selected release or commit. Then:

```sh
docker compose stop api
docker compose build api
docker compose run --rm api db upgrade
docker compose up -d --wait api
curl --fail http://127.0.0.1:8000/health
```

The explicit upgrade step is optional because startup applies pending migrations. Upgrades are
serialized with a PostgreSQL advisory lock. The runtime and MCP refuse an incompatible schema;
MCP never performs migrations. Do not downgrade the schema in production. To roll back an
incompatible application upgrade, restore the paired pre-upgrade database and session backups
and run the previous image/commit. Changing `POSTGRES_PASSWORD` in `.env` does not change an
existing PostgreSQL role's password; rotate the database role and connection settings together.
PostgreSQL major-version upgrades need PostgreSQL's own migration procedure, not only a new tag.

## Backup and restore

Stop the API and any external CLI writers so the database ledger and session snapshot describe
the same point in time. Protect backups as secrets and keep copies off the host. Never discard
the scheduled ledger or pending intents to bypass a failed Garmin write.

### Bundled database only

Use the following backup and restore commands only when the API uses the bundled `postgres` service.
If `DATABASE_URL` points elsewhere, use the external database procedure below instead.

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose stop api
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/stride.dump
docker compose run --rm -T --no-deps --entrypoint tar api \
  -C /data/garmin -czf - . > backups/garmin-session.tgz
docker compose start api
```

If you customized `STRIDE_COACH_TOKENS`, replace `/data/garmin` in these commands. Capture the
configured timezone, credentials, and deployed commit securely with the backup. `pg_dump -Fc`
creates a portable custom-format archive; use the same PostgreSQL major version to restore.

To restore into the bundled PostgreSQL database, stop all writers and take a safety backup
first. The following command **replaces existing database objects and data** with the backup:

```sh
docker compose stop api
docker compose exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' \
  < backups/stride.dump
# Empty the dedicated session directory first if it already contains another session.
# Run as root only to set volume ownership; the API continues to run as UID 10001.
docker compose run --rm -T --no-deps --user 0 --entrypoint sh api -c \
  'tar -C /data/garmin -xzf - && chown -R 10001:10001 /data/garmin && chmod 700 /data/garmin && find /data/garmin -type f -exec chmod 600 {} \;' \
  < backups/garmin-session.tgz
docker compose up -d --wait api
```

### External database

Run these commands from the repository on an operator host with uv, PostgreSQL 17 client tools, and network access to the external database.
The API image does not include `pg_dump` or `pg_restore`.
Supply provider-required CA files at the paths specified in the connection URL on this host.

Stop all writers, including the API, before you save either backup:

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose stop api
set +x
```

Use your secret manager to export the deployed API's exact `DATABASE_URL` into this shell.
Do not paste credentials into command arguments or shell history.
Do not substitute the bundled service's credentials or database name.

Create a private PostgreSQL service file, a named connection configuration, from that URL.
The conversion removes the SQLAlchemy driver suffix and preserves encoded credentials and TLS parameters.
The client tools receive only the service name in their arguments.
Keep shell tracing disabled throughout this procedure.

```sh
uv run --locked python - <<'PY'
import configparser
import os
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql")
service = configparser.ConfigParser(interpolation=None)
service["stride_backup"] = conninfo_to_dict(url.render_as_string(hide_password=False))
path = Path("backups/pg_service.conf")
with path.open("w", encoding="utf-8") as output:
    path.chmod(0o600)
    service.write(output, space_around_delimiters=False)
PY
export PGSERVICEFILE="$PWD/backups/pg_service.conf"
unset DATABASE_URL
```

For backup, run `pg_dump` against this service.
After the database backup succeeds, save the paired Garmin session before you restart the API:

```sh
pg_dump --dbname=service=stride_backup --format=custom --file=backups/stride.dump
docker compose run --rm -T --no-deps --entrypoint tar api \
  -C /data/garmin -czf - . > backups/garmin-session.tgz
docker compose start api
rm backups/pg_service.conf
unset PGSERVICEFILE
```

If either backup fails, keep writers stopped and repeat the paired backup before you restart the API.
Protect both archives as secrets. Save the deployed commit and timezone securely with them.
If you customized `STRIDE_COACH_TOKENS`, replace `/data/garmin` in the session commands.

For restore, stop all writers and take a paired safety backup first.
Repeat the external preparation above with the intended deployment's current `DATABASE_URL`.
Make sure that this configuration identifies the intended destination.
The following command replaces existing database objects and data with the backup:

```sh
pg_restore --dbname=service=stride_backup --clean --if-exists --no-owner --exit-on-error \
  backups/stride.dump
rm backups/pg_service.conf
unset PGSERVICEFILE
```

After the database restore succeeds, restore its paired Garmin session archive with the session restore command above.
Preserve its ownership and permissions. Restart the API only after both restores succeed.
Delete the private service file after any failed attempt too.

After restore, inspect the plan and Garmin connection status before syncing or applying changes.
An older backup cannot know about remote writes made after it: inspect Garmin for discrepancies
and unresolved writes before proceeding. Do not run `docker compose down -v` on a deployment
you want to keep; that deletes both named volumes.

## Openship equivalent (untested on this platform)

These are the deployment settings to map to Openship's image, environment, volume, port, and
probe controls. No Openship deployment was performed for this change.

| Setting | Value |
| --- | --- |
| API image | Build this repository's `Dockerfile` at the chosen commit; no published image is provided |
| Command | Image default, one `serve` process and one replica |
| Internal port | `8000` over HTTP on the private platform network |
| Public ingress | HTTPS hostname at the platform proxy, forwarding to port 8000 |
| Readiness and liveness | HTTP `GET /health`, no auth header, allow startup migration time |
| Environment | `DATABASE_URL`, `STRIDE_COACH_API_TOKEN`, `STRIDE_COACH_TOKENS=/data/garmin`, `TZ`; CORS only for web clients |
| API volume | Persistent `/data/garmin`, writable by UID/GID `10001:10001` |
| PostgreSQL | Private PostgreSQL 17 service, strong role password, persistent `/var/lib/postgresql/data` |
| Restart | Restart on failure; keep exactly one service instance |

Use the provider's secret injection for credentials. Supply the database's private hostname in
`DATABASE_URL`. A managed PostgreSQL service can replace the bundled database, but it still
requires backups and session-compatible connections. Mount provider CA certificates if needed.

## Local offline tests and synthetic proof

A separate Compose file starts only a disposable PostgreSQL, exposed on loopback port 55439:

```sh
docker compose -p stride-tests -f compose.test.yaml up -d --wait
export TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:55439/stride_test
uv sync --locked
uv run pytest --cov=stride_coach --cov-fail-under=90
uv run python examples/offline_demo.py --directory .local/offline-proof
uv run python examples/api_demo.py --directory .local/api-proof
uv run python examples/garmin_demo.py --directory .local/garmin-proof
# From app/: npm run proof
```

Tests and demos allocate isolated schemas in `TEST_DATABASE_URL` and remove only those schemas
when finished. Use a disposable database and a role allowed to create schemas. Never point this
variable at production. All Garmin responses in tests and the Garmin demo are synthetic. CI
runs the same suite against a PostgreSQL service container on Python 3.11, 3.12, and 3.13.

For the packaged clean-install, restart, schema-upgrade, and dump/restore proof, run
`uv run python examples/selfhost_proof.py`. It builds the image and creates a randomly named
Compose project with generated secrets, uses synthetic data, then removes only that project
and its volumes. No existing `.env` settings or Garmin credentials are used.

## Automatic sync and import recovery

One in-process worker starts with the HTTP server. Keep the server running for daily sync and
history imports; CLI and MCP invocations do not start a scheduler. Daily sync runs after the
configured local time, at most once that day when a regular sync has already been attempted.
App open/resume requests `POST /sync/open`; the server skips silently without stored Garmin
credentials or while another writer holds the PostgreSQL advisory lock. The server persists
attempt times to enforce the configured interval across app restarts and devices. A failed
attempt also counts toward the interval; **Actions > Sync** is the explicit retry path.

`GET /sync/status` returns the latest attempt, last successful attempt, and history job, without
requiring a plan. Each attempt includes start/finish time, result, requested date range, activity
count, and a safe error message. Running or failed attempts do not claim complete coverage.
If access renewal fails, reconnect in Settings; the worker never retries password login.
Automatic sync only reads activities. It never pushes/removes workouts or applies adjustments.

`POST /sync/history` takes `{"range":"12-weeks"}`, `{"range":"6-months"}`, or
`{"range":"everything"}` and returns a durable job immediately. Everything requests all available
Garmin history from 1970 onward. Ranges are anchored to the request's local date. The worker
fetches ascending pages of 100 activities with the configured delay. Activity upserts and the
page cursor commit together. Restarting the server resumes a running import. A request failure
pauses the job; **Resume import** retries its last uncommitted page after reconnecting if needed.
Repeated requests for the current range return the same job; selecting another range after it
finishes starts another idempotent import. Only one import is active at a time. Garmin does not
provide a snapshot cursor, so avoid editing/deleting old activities during an import, which can
shift offsets. Imported history never grants complete-week coverage for automatic adaptation.
Run a regular sync before applying any adjustment.

Applied adjustments retain reason text and an input snapshot (weekly completion/load, athlete
parameters, target effort counts, rule version, and complete sync coverage). `/status` returns
this evidence; **Progress** shows why each applied week changed. Older adjustments retain their
existing reasons with an empty input snapshot because their original inputs cannot be recovered.
