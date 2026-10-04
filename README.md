# stride-coach

An open source running coach with deterministic training plans, structured Garmin workouts,
and weekly adaptation from completed runs.
The [iOS and Android app](app/README.md) connects to your own server.
The server requires Python 3.11+. The project is MIT licensed.

**stride-coach is not affiliated with, endorsed by, or a replacement product from Runna,
Garmin, or V.O2.** It contains original rules and session descriptions, with no imported
commercial plans or copied interfaces. There are no LLM API calls or API keys in this package.
Claude can discuss your plan through local or remote read-only MCP using your existing access.

## 15-minute quickstart

Stride Coach creates a plan, shows today's workout, imports completed Garmin runs, and
explains weekly adjustments. Uploads require your confirmation. You own the single-user
server and its data. It does not provide medical advice, multi-user accounts, a web UI,
or support for other watch vendors.

Allow about 15 minutes **after** installing Docker with Compose, Git, Python 3, and a compatible
mobile app, and preparing an HTTPS hostname/proxy. Image downloads, DNS, app builds, Apple
provisioning, and Garmin MFA can take longer. There is no public hosted service or promised
store download. Use [Expo Go](app/README.md#local-development) with Node 22.13+ to try the app,
or [build your own installable copy](app/README.md#build-your-own-app-copy).

1. Clone and configure the server:

   ```sh
   git clone https://github.com/junlov/stride-coach.git
   cd stride-coach
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))'
   ```

   Edit `.env`: put the first secret in `STRIDE_COACH_API_TOKEN`, the second in
   `POSTGRES_PASSWORD`, and set `TZ` to your IANA timezone (for example `America/Sao_Paulo`).
   Keep both secrets private. Before the first sync, review the
   [run data privacy controls](docs/activity-data.md#original-files-and-privacy).

2. Start the server with one command and check readiness:

   ```sh
   docker compose up -d --build --wait
   curl --fail http://127.0.0.1:8000/health
   ```

   Expect `{"status":"ready"}`. Put the server behind [HTTPS](docs/self-hosting.md#environment-and-https).
   A phone cannot reach your computer through the phone's `localhost`.

3. Open the app. For Expo Go, run the following in a second terminal from the repository root,
   then scan the QR code with an SDK-compatible Expo Go:

   ```sh
   cd app
   npm ci
   npm start -- --go
   ```

4. Follow the [mobile connection guide](app/README.md#connect-your-server) to pair with a QR code and your HTTPS server URL.
5. Continue through Garmin connection and goal setup in that guide. See [goal constraints](#plan-and-review).
   To use recent history for the initial estimate, follow the
   [first-run sync instructions](docs/self-hosting.md#first-run-and-garmin) before creating the goal.
6. Review **Today** and **Plan**. Preview a workout before confirming any Garmin upload.
   Use the [first live check](#garmin-authentication-and-first-live-check) for watch delivery.

If startup fails, run `docker compose logs --tail=80 api postgres` and check `.env` and port
availability. If port 8000 is occupied (or `/health` reaches another service), set `PORT=18000`
in `.env`, rerun the Compose command, and check `curl --fail http://127.0.0.1:18000/health`.
Update the HTTPS proxy target to that port. Redact logs before sharing. A failed Garmin login is not a failed server health
check; follow the connection recovery guide instead of repeatedly retrying.

[Self-hosting and backups](docs/self-hosting.md) · [Mobile app](app/README.md) ·
[Contributing and one-command development](CONTRIBUTING.md) · [Roadmap](ROADMAP.md) ·
[Report a vulnerability](SECURITY.md)

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
git clone https://github.com/junlov/stride-coach.git
cd stride-coach
uv sync --locked
uv run stride-coach --help
```

Linux and macOS are supported. PostgreSQL is the only runtime store. Set `DATABASE_URL`
(or global `--database-url`) and run `uv run stride-coach db upgrade` before using standalone stdio MCP.
The CLI and API startup apply pending migrations automatically. Use one database per active
plan; `init` refuses to overwrite one. Keep activity exports, backups, and tokens private.

For one-command deployment after configuring secrets, run `docker compose up -d --build --wait`.
See [self-hosting](docs/self-hosting.md) for Compose setup, HTTPS, Openship-equivalent settings,
SQLite import, upgrades, backup/restore, and the disposable PostgreSQL test setup.

## Plan and review

A plan starts on a Monday and defaults to today if today is Monday, or the next Monday otherwise.
The end date must be 8 to 52 weeks after the start. Choose your own future dates for the examples below.
Goal values are `5k`, `10k`,
`half`, `marathon`, and `return-to-running`. For return to running, the date is the program
completion date, and 2 or 3 days per week are supported. Other goals support 2 to 6 days.
Long-run day uses Monday=0 through Sunday=6.

```sh
uv run stride-coach init 10k 2027-01-03 --start 2026-10-05 --days 3 --long-run-day 6 \
  --resting-hr 60 --max-hr 190
uv run stride-coach plan --week 1
uv run stride-coach status
```

Set resting and maximum heart rates to your own values. Defaults are placeholders for initial
planning, not measurements. Weekly volume is **total session minutes**, including walking and
recoveries. Race day is excluded from training workouts. The plan does not guarantee race
readiness, especially for a half or marathon with little recent running.

For a better baseline, pull the previous four weeks **before init**:

```sh
uv run stride-coach sync --since 2026-09-07 --until 2026-10-04
# Then run init. It uses the locally stored activities.
```

Alternatively, `init --recent-runs PATH` accepts a normalized JSON array with this shape
(synthetic example). Only mark a true race or time trial as `best_effort`:

```json
[
  {"id": "example-run", "day": "2026-09-27", "distance_km": 5,
   "duration_min": 30, "average_hr": 150, "sport": "running", "best_effort": true}
]
```

A recent marked effort provides a VDOT-style estimate. Garmin averages are not automatically
classified as maximal efforts. Without one, the engine uses recent easy paces or HR targets.
`sync --activities PATH --since DATE --until DATE` imports normalized data offline.

Each successful regular sync replaces stored activities within the inclusive date range,
including removal of activities absent from the result.
For an offline import, supply the complete activity list for that range.
An empty list clears that range.

## Garmin authentication and first live check

The server owns the Garmin connection. Follow the [mobile connection guide](app/README.md#connect-your-server)
for first-run setup, Garmin sign-in, and connection management. No separate token-export tool is needed.

Operators can use the same connection from the CLI, with hidden password/MFA prompts:

```sh
uv run stride-coach garmin login
uv run stride-coach garmin status
uv run stride-coach garmin logout
```

Each explicit login submits the password once, without transport retries or automatic login
fallbacks. The password and MFA code are never saved to disk, PostgreSQL, logs, or API responses.
The app clears its password field immediately on submit. A pending MFA challenge stays only in
server memory for five minutes, and is consumed by one completion attempt. A new login replaces
it; a restart loses it. Run **one server process/worker** so both requests reach the same memory.
The server uses the stored long-lived OAuth1 token to renew an expired or near-expiry access token
(within 60 seconds), at most once per request. Renewal failure asks you to reconnect Garmin;
it never submits a password again. Sync, push, and removal share that connection.

Tokens are secrets. The dedicated directory defaults to `~/.local/share/stride-coach/garmin`;
set `STRIDE_COACH_TOKENS` (or global `--tokens PATH`) to override it. The server creates it with
owner-only permissions and atomically saves tokens plus the account display name in a private
`connection.tokens.json`. These tokens are not encrypted at rest; protect the volume and backups.
It refuses shared stores such as `~/.garminconnect` and nonempty directories
without its ownership marker. Choose a fresh directory, then connect again; do not point it at
another tool's tokens. Disconnect removes token contents and leaves a non-secret generation marker
to invalidate outstanding logins.
Disconnect does not revoke other Garmin sessions.

**Container deployment:** follow the [operator guide](docs/self-hosting.md). The supplied Compose
file persists PostgreSQL and the dedicated Garmin session directory, validates configuration,
and provides a public readiness probe. Run one replica/worker behind HTTPS. Keep proxy and
application request-body logging disabled, including error monitoring that captures login bodies.

The adapter retains pinned `python-garminconnect` **0.2.38** and garth **0.5.21**. Garmin's API is
unofficial. [Garth's maintainer reports broken newer login flows and deprecation](https://github.com/matin/garth/discussions/222).
This pin uses the older SSO flow; synthetic tests do not establish that Garmin will accept it
from a deployed host. Real login/MFA and renewal still need an operator check after deployment.
Do not repeatedly retry rejected logins; check status and investigate the failure first.

**First live verification, after reviewing the plan:**

1. Run `uv run stride-coach plan --week 1` and copy one future workout's `id`.
2. Run `uv run stride-coach push --workout WORKOUT_ID --dry-run`. Replace `WORKOUT_ID`
   with that ID. This is fully local: check the date, step durations, and HR or pace targets.
3. Run `uv run stride-coach push --workout WORKOUT_ID --apply` once. This creates the
   workout and places it on the Garmin Connect calendar.
4. Inspect that single workout in Garmin Connect and on your watch after a normal device sync.
   Verify the target ranges and steps, then repeat the same command to confirm it skips.
5. Only after that check, preview a week with `uv run stride-coach push --week 1 --dry-run`,
   then explicitly upload it with `uv run stride-coach push --week 1 --apply`.

Without `--apply`, every push is a local dry run, including bulk pushes. `--apply` and
`--dry-run` together are rejected. Past workouts are excluded. Garmin device delivery uses
Garmin's normal calendar/device sync; this tool does not force a device message.

Workouts use short runner-facing names, such as `Easy Run 40 min` and `Tempo 3 x 8 min`,
shared with the app. Descriptions explain the effort and targets; step instructions include
pace or heart rate. See [Garmin workout text, ownership, and migration](docs/garmin-workouts.md)
for naming limits, an example payload, and updates to older workouts.

Workouts have an ownership marker and stable per-date identity.
Re-running reconciles remote workouts and calendar entries, updates changed workouts in place,
and skips unchanged ones. PostgreSQL advisory locks serialize writers, and durable intents record uncertain operations
before sending them. If a request might have succeeded but Garmin has not exposed it yet,
the tool stops instead of creating a duplicate. Wait for Garmin visibility and rerun. If a
workout was renamed and its marker removed, the tool refuses to reclaim it. Keep the marker.
These safeguards cannot coordinate separate copies of the database on different machines.

`uv run stride-coach remove --dry-run` previews ownership markers for this plan.
`uv run stride-coach remove --apply` rechecks remote ownership, removes calendar entries in
each workout's planned month, and deletes only this plan's marked workout templates. If you
manually moved calendar entries to another month, inspect those entries in Garmin afterward.
Unrelated workouts are untouched. Do not erase the local ledger to work around an uncertain
upload; inspect Garmin first. An unresolved, invisible upload intentionally blocks retry/removal.

### Use one training plan on your watch

Before your first Stride Coach push, turn off Garmin Daily Suggested Workout
**prompts** and pause or quit any competing Garmin Coach plan. Stride Coach does
not change those settings or detect competing plans. Disabling prompts does not
stop Garmin generating suggestions or delete scheduled workouts.

- **On the watch:** on a Forerunner 255, press START, choose Run, then hold UP.
  Open **Training > Workouts > Daily Suggestions > Settings > Workout Prompt**
  and use START to turn the prompt off. This is the
  [Garmin-documented Forerunner 255 procedure](https://www8.garmin.com/manuals-apac/webhelp/forerunner255series/EN-SG/GUID-D7EE59E8-45FD-4EFF-B627-10D09D77E44F-6878.html).
  Menu names vary by model and software; consult your watch manual if they differ.
- **Daily suggestions in Garmin Connect:** a Connect app or web switch for turning
  these off was not confirmed in Garmin's public help. Use the watch control above.
- **Stop an adaptive running or Garmin Coach plan in Connect:** in the phone app,
  open **More > Training & Planning > Garmin Coach Plans**, open the active plan,
  then its three-dot menu. Choose **Pause Plan** for a temporary break or
  **Quit Plan** to end it. On the website, open **Training & Planning > Garmin
  Coach Plans**, then the gear beside the plan name and choose **Pause Plan** or
  **Quit Plan**. Quitting cannot be undone; resuming requires a new plan. Completed
  workouts stay in your calendar, while unfinished workouts for today and later
  are removed. Self-guided plans cannot be paused. See
  [Garmin's running plan help](https://support.garmin.com/en-US/?faq=IkvWNeIoSd48GIYCjkhlo7&productID=707538&tab=topics)
  and [plan management help](https://support.garmin.com/en-AU/?faq=o21H5a4cSU52FwFAy0R6Z5&productID=707538&tab=topics).
- **Stop a Coach plan on the watch:** a watch-only pause/quit procedure was not
  confirmed in those public help pages. Stop the plan in Connect, then sync your
  watch and check its upcoming workouts before sending Stride Coach workouts.

Garmin settings and every push confirmation in the app include a reminder,
including the first push. Check Garmin's calendar and the watch yourself to make
sure you are following only the plan you intend.

## Weekly loop

On Monday, sync through the completed Sunday, review the proposal, then apply it locally.
Replace `FINGERPRINT` with `inputs.proposal_fingerprint` from the reviewed proposal.
If the server rejects a stale preview, request and review a new proposal.

```sh
uv run stride-coach sync
uv run stride-coach status
uv run stride-coach adapt 2
uv run stride-coach adapt 2 --apply --proposal-fingerprint FINGERPRINT
uv run stride-coach push --week 2 --dry-run
uv run stride-coach push --week 2 --apply
```

`adapt` requires the target week's Monday and one successful sync covering the previous two full weeks.
Sync again after Sunday ends, even if you synced on Sunday.
The `status.sync` and sync response dates describe the fetched range, which can include today.
Today's activities are stored, but today does not count as a complete day for adaptation.

Adaptation compares completion, total duration, easy-run targets, and running Banister TRIMP from
average HR. Missing HR is reported as unknown. Walking and other sports do not count as runs.
Garmin does not reliably return a planned session type, so date plus running matches are
explicitly labeled **inferred**. A normalized activity's optional `kind` supplies an exact type.
Matches are one-to-one, preferring exact type and closest duration.

Every applied adjustment retains its reasons and before/after volume. Applying the same week
again returns the saved adjustment. Reductions also scale later weeks to preserve progression;
if those weeks were already pushed, push them again to update Garmin. There is no automatic
Garmin write from sync or adapt. See [training rules](docs/training-rules.md) for the thresholds
and limitations, and [architecture](docs/architecture.md) for storage and recovery behavior.

## Connect Claude to your coach

The deployed API serves read-only MCP over Streamable HTTP at
`https://coach.example.com/mcp/`. Use your own HTTPS hostname and the same
`STRIDE_COACH_API_TOKEN` configured for the API. No separate MCP process or database
access is needed on your laptop. The [self-hosting guide](docs/self-hosting.md) covers HTTPS.

For **Claude Desktop**, install Node.js and open **Settings > Developer > Edit Config**.
Merge this entry into `claude_desktop_config.json`, replace the hostname and token,
then restart Claude Desktop. The [mcp-remote bridge](https://github.com/punkpeye/mcp-remote)
passes the bearer header from Desktop's local stdio connection to the remote server:

```json
{
  "mcpServers": {
    "stride-coach": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://coach.example.com/mcp/",
        "--transport", "http-only", "--header", "Authorization:${COACH_AUTH_HEADER}"
      ],
      "env": {
        "COACH_AUTH_HEADER": "Bearer YOUR_SERVER_TOKEN"
      }
    }
  }
}
```

Keep that config private and untracked. This uses a static bearer header, with no OAuth
login. A connector that only accepts an OAuth login cannot use this endpoint directly.

For **Claude Code**, use this remote entry in your MCP configuration. Set
`STRIDE_COACH_API_TOKEN` in Claude Code's environment using your secret manager:

```json
{
  "mcpServers": {
    "stride-coach": {
      "type": "http",
      "url": "https://coach.example.com/mcp/",
      "headers": {"Authorization": "Bearer ${STRIDE_COACH_API_TOKEN}"}
    }
  }
}
```

See [Claude Code's MCP configuration](https://code.claude.com/docs/en/mcp) for setup.
Every remote MCP request requires the bearer header except browser CORS preflight requests.
Tokens in URLs or cookies do not authenticate requests.
Browser clients also need their exact Origin in `STRIDE_COACH_CORS_ORIGINS`.
Preflight permits the `Authorization`, `Content-Type`, and `MCP-Protocol-Version` headers.

The **local stdio option** still works on a host with database access. Register it using
the absolute repository path and supply `DATABASE_URL` in the MCP process environment
(use your client's protected environment configuration):

```sh
claude mcp add stride-coach -- uv run --directory /absolute/path/to/stride-coach \
  stride-coach-mcp
```

Both transports expose `plan`, `week`, `compliance`, `load`, `propose_adjustment`,
`today_workout`, `current_week`, and `status`.
Ask Claude: "What is today's workout, how did this week go, and why did my plan change?"
`today_workout` distinguishes a workout, a rest day, and a date outside the plan.
`current_week` returns workouts and measured completion, or a null week outside the plan.
Both use the server's `TZ` (UTC by default). `status` includes stored sync coverage and
applied adjustments with reasons and before/after minutes. Empty adjustments mean no saved
changes; null sync means no stored coverage. Coverage is not the time of the last sync attempt.
The `sync_status` field returns stored sync-attempt details and history import progress.
See [automatic sync and import recovery](docs/self-hosting.md#automatic-sync-and-import-recovery)
for their meaning.

The MCP tools open PostgreSQL transactions read-only, never invoke Garmin, and make no LLM calls.
It exposes training data to your MCP client, so use a client/account you trust with that data.
Proposals are previews and can include an incomplete week. Follow the [weekly loop](#weekly-loop)
to apply a reviewed proposal. MCP cannot sync, upload, remove, or apply.
It reads changes after the app or CLI saves them.

## JSON API for a phone client

The package includes FastAPI. CLI, MCP, and API
use the same `service.Coach` operations. The API is single-user and requires a bearer token
on every data operation, including the schema endpoint. The non-sensitive `/health` probe and one-time `/pairing/exchange` endpoint are public. It accepts the token only in the
`Authorization: Bearer ...` header, never a query parameter or cookie.

Generate a secret, save it securely in the server configuration, then start:

```sh
export STRIDE_COACH_API_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Optional, only for browser clients. Exact origins, separated by commas, no trailing slash.
export STRIDE_COACH_CORS_ORIGINS="https://your-browser-client.example"
uv run stride-coach serve --host 127.0.0.1 --port 8000
```

### Pair your phone without typing the token

Pairing transfers the server token to your phone without manual token entry.
Follow the [mobile pairing guide](app/README.md#pair-with-a-qr-code) to scan a QR code or enter a pairing code.
For CLI commands, environment variables, and security limits, see [phone pairing](docs/self-hosting.md#phone-pairing).

### API authentication and HTTPS

The server refuses to start without a token of at least 32 characters. Keep the same secret
in your process manager's protected environment configuration across restarts. To rotate it,
replace the configured value, restart your server, and update the client. Never commit it or
put it in a URL. CORS is disabled by default; native phone requests do not need CORS. Browser
origins must be explicitly configured; wildcards are rejected.

For phone access, terminate HTTPS at a reverse proxy and keep port 8000 private. For example,
with a domain pointing to your server, a Caddyfile can contain:

```caddyfile
coach.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Replace the domain with your own and follow [Caddy's reverse proxy setup](
https://caddyserver.com/docs/quick-starts/reverse-proxy) for HTTPS certificates and network
requirements. The phone uses `https://your-domain` as its API base URL. Do not send the bearer
token over public plaintext HTTP. FastAPI documents this [TLS termination arrangement](
https://fastapi.tiangolo.com/deployment/https/). Avoid logging Authorization headers or request bodies in the proxy.
Set the server's timezone to the athlete's local timezone, since plan/adaptation dates use it.
Run one server instance using the same PostgreSQL database and session directory as the CLI.

| Method and route | Operation |
| --- | --- |
| `POST /goal` | Initialize with `{setup: {...}, recent_runs: [...]}`; history is optional |
| `GET /plan` | Full typed plan |
| `GET /weeks/{number}` | Workouts with total minutes and week metrics |
| `GET /status`, `/compliance`, `/load` | Sync coverage, adjustments, completion, and TRIMP |
| `POST /push` | Optional `week`/`workout`; defaults to dry run, `apply: true` writes Garmin |
| `POST /sync` | Pull Garmin, or pass normalized `activities` plus date range |
| `POST /adapt` | `{week: 2}` proposes; add `apply: true` and the reviewed `inputs.proposal_fingerprint` as `proposal_fingerprint` to save locally |
| `POST /adjustments/propose/{number}` | Read-only preview, including incomplete-week caveat |
| `POST /remove` | Preview owned removal; `apply: true` removes from Garmin |
| `POST /garmin/login` | Submit `email` and `password` once; may return `challenge_id` and `mfa_required` |
| `POST /garmin/mfa` | Complete pending login with `challenge_id` and `code` |
| `POST /pairing/codes` | Bearer-authenticated creation of a one-time, ten-minute pairing code |
| `POST /pairing/exchange` | Public, rate-limited code exchange for the existing API token |
| `GET /garmin/status` | Connection state, optional display name, access-token expiry (Unix seconds); may renew once |
| `POST /garmin/logout` | Delete stored Garmin tokens and cancel pending MFA |
| `GET /openapi.json` | Authenticated generated client contract |

See [run data storage and import](docs/activity-data.md) for activity detail endpoints, normalized imports, and resumable backfill.

All command bodies are JSON. For example, `POST /push` with `{"week": 1}` previews a week.
An explicit `apply: true` is required for writes, and conflicting `dry_run: true` is rejected.
Unknown fields and invalid typed inputs return 422, missing/bad authentication returns 401,
application precondition failures return 400, and sanitized Garmin failures return 502.
No route accepts a filesystem path from a remote client.

The committed [OpenAPI 3.1 schema](docs/openapi.json) is the mobile client handoff. It includes
stable operation IDs, enums, request/response models, and the `CoachBearer` security scheme.
Regenerate it after API changes with `uv run python examples/export_openapi.py`; tests fail
if it differs from the application. See [automatic sync](docs/self-hosting.md#automatic-sync-and-import-recovery)
for background activity reads. Garmin writes require explicit confirmation.

## iOS and Android app

The [Expo mobile app](app/README.md) connects to your own server for daily workouts, plans,
goal setup, training progress, and preview-first Garmin actions. See its guide for Expo Go,
secure connection settings, offline tests, and EAS builds.

## Development and offline proof

Start the [disposable PostgreSQL](docs/self-hosting.md#local-offline-tests-and-synthetic-proof)
and export `TEST_DATABASE_URL` before running tests or demos.

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=stride_coach --cov-fail-under=90
uv run python examples/offline_demo.py --directory .local/demo
uv run python examples/api_demo.py --directory .local/api-demo
```

The CLI demo exercises initialization, plan inspection, dry-run push, synthetic activity sync,
and adaptation with a simulated Monday. It uses no Garmin account or requests; PostgreSQL is the only external service. The API demo starts the real server on loopback,
checks auth, creates a synthetic goal, and previews one workout. It sends no Garmin requests.
Tests use real PostgreSQL while blocking Garmin traffic, including fake lost-response cases.
Run `uv run python examples/garmin_demo.py --directory .local/garmin-proof` with a fresh directory
for real loopback HTTP login, MFA, renewal, and disconnect backed by synthetic Garmin replies.
Outbound Garmin requests are blocked in this proof; it does not establish live SSO compatibility.
GitHub Actions runs lint and tests on Python 3.11, 3.12, and 3.13 without secrets.
Garmin payloads follow upstream API shapes but **have not been verified with live writes**;
the single-workout check above is required before relying on device delivery.

The project has no web UI, multi-user hosting, other watch vendors, commercial-plan import, or integration
that changes an existing Garmin analytics project. These are generic training heuristics,
not clinical return-to-sport clearance. Stop a session if symptoms make running unsafe.

### Daily sync, past runs, and plan-change reasons

The HTTP server automatically reads Garmin activities daily and when the app opens or resumes.
Settings, Today, and Actions show the last successful sync and any sync error. Before creating
a goal, use **Import past runs** after Connect Garmin (also in Settings): choose **12 weeks**,
**6 months**, or **Everything**, and wait for Complete so those runs inform the fitness estimate.
Imports continue on the server, survive restarts, and offer Resume after a connection error.
Reconnect Garmin if token renewal fails; no password login is retried automatically.

Sync reads runs only. Applying a proposed adjustment still requires explicit confirmation;
**Progress** shows the saved reasons for every applied adjustment. See [saved adjustment evidence](docs/self-hosting.md#automatic-sync-and-import-recovery)
for the retained inputs and reasons.

See [automatic sync and import recovery](docs/self-hosting.md#automatic-sync-and-import-recovery)
for API endpoints, restart behavior, range semantics, and configuration limits. A synthetic
loopback proof is available with `uv run python examples/sync_demo.py` and a disposable
`TEST_DATABASE_URL`; it makes no live Garmin calls.
