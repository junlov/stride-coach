# Run data implementation decisions

- Keep detail records and fetch state separate from the scheduled sync lane. Base summaries remain usable after a detail failure.
- Store normalized metrics in typed columns, laps/splits/zones as child rows, streams as versioned zlib-compressed JSON in bytea, and original FIT bytes on a private volume.
- GPS opt-out omits original FIT and raw payloads as they can contain coordinates in unknown vendor fields. It strips latitude/longitude from normalized streams. Existing data is not retroactively erased.
- Fetch detail with a separate durable per-activity checkpoint. A failed endpoint leaves the activity retryable; successfully completed activities are skipped.

## Job check

J3: summaries remain available for activity matching and training-load adaptation even if
Garmin detail capture fails. Re-sync updates core summary fields while preserving previously
captured detail, with explicit retry status. Laps, original zone bounds and streams retain
inputs for a future run-type classifier. This change does not infer run types or change the
training rules, and it adds no app charts or maps.

## Live proof

Command (TEST_DATABASE_URL pointed to this task's disposable PostgreSQL on loopback):

```sh
TEST_DATABASE_URL=postgresql://postgres:synthetic-test-password@127.0.0.1:32768/stride_test \
  uv run python examples/run_data_demo.py
```

Trimmed output:

```json
{
  "capture": {"completed": 1, "failed": 0, "remaining": 0},
  "repeat_capture": {"completed": 0, "failed": 0, "remaining": 0},
  "api": "detail and streams: 200; 2 laps, 3 zones, 6 samples",
  "fixture_run": {"postgres_row_bytes": 2596, "compressed_stream_bytes": 231, "fit_bytes": 84},
  "one_hour_run": {"postgres_row_bytes": 30481, "compressed_stream_bytes": 44448,
                   "stream_json_bytes": 240793}
}
```

The proof uses real PostgreSQL migrations, capture persistence, import, archive filesystem
writes and authenticated FastAPI requests, with synthetic Garmin adapters. No Garmin login,
network call or remote write was made. The schemas and private temporary FIT directory are
removed afterward. This does not prove Garmin's current live endpoint behavior.

## Storage size per run

| Synthetic run | Stream JSON | zlib stream bytes | Sum of Postgres row sizes | Original FIT |
| --- | ---: | ---: | ---: | ---: |
| 15-minute fixture, six samples, two laps, three zones | Small fixture | 231 B | 2,596 B | 84 B |
| One hour, 3,601 samples, all nine stream columns | 240,793 B | 44,448 B | 30,481 B | Not generated |

The one-hour stream is 81.5% smaller than its JSON representation before PostgreSQL's own
TOAST compression. Row sizes are sums of `pg_column_size` for that activity's rows. They
exclude indexes, page overhead, WAL, free space and backups; PostgreSQL may compress them
further, so they are not a disk-capacity forecast. The 84-byte FIT is deliberately minimal,
not representative of a real recording. Actual storage depends on duration, sampling, sensors
and original FIT size. The proof script makes the measurements reproducible.

## Validation

- Full backend suite: 278 passed, 97.40% coverage, including 12 run-detail tests.
- Ruff lint and format, app typecheck and lint passed.
- App tests: 43 passed. iOS and Android production export passed.
- OpenAPI and TypeScript schema regenerated; Compose configuration validates.

## Integration notes

- Detail migration `0003_run_data` descends from `0002`. If the scheduling lane also adds a
  migration from `0002`, serialize those migrations or add an Alembic merge before combining.
- Scheduler integration calls `capture_pending(store, client)` after saving summaries. The
  current hook lives in `Coach.sync`; no scheduler/history-import code is added here.
- GPS opt-out skips raw payloads and originals rather than pretending an unchanged FIT has
  no GPS. It is prospective; existing files/backups remain.
- Summary lists still power coaching without loading streams. No classifier is implemented.
- Copy the Job check, Live proof and measured storage figures into the eventual PR description.
