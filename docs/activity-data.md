# Run data storage and import contract

Every Garmin sync stores the summary immediately, then captures detail for up to 20 pending
running activities. This is separate from the scheduler and history-import window. Detail
failure does not discard the summary or prevent its use for plan matching and training load.
The sync response's `details` reports completed, failed, and remaining captures. A failed batch
stops at the first error to avoid hammering Garmin; the next sync or backfill retries it.

```sh
stride-coach backfill-details --limit 20
# Only for existing records from before detail storage was installed:
stride-coach backfill-details --include-legacy --limit 20
```

Repeat until `remaining` is zero. Legacy records have no provider provenance. Use
`--include-legacy` only if those records' IDs are Garmin activity IDs. Imported records with
source metadata are excluded. A run with no downloadable original stays retryable; inspect
its capture status before repeatedly retrying. Other sports can retain summaries only.

Each request waits `STRIDE_COACH_DETAIL_DELAY_SECONDS` (default 1 second, minimum 0.1,
maximum 60). The database write lock serializes captures between API and CLI instances.
There is no automatic immediate retry. Completed activities are skipped on subsequent syncs.
A crash resumes at the first incomplete activity, which may repeat that activity's reads.
An original already saved before a crash is reused without a duplicate file.
A 20-run batch makes up to 100 requests, so sync can take minutes. The app client allows
three minutes; if it times out, check run capture status or resume from the CLI.

## Normalized JSON imports

`stride-coach sync --activities runs.json --since YYYY-MM-DD --until YYYY-MM-DD` and
`POST /sync` accept the same activity objects. The file is a JSON array; the HTTP body puts
that array in `activities`. Neither path contacts Garmin for these objects. The base fields
remain `id`, `day`, `distance_km`, `duration_min`, optional `average_hr`, `sport`, `kind`, and
`best_effort`. `duration_min` remains the coaching duration, not elapsed time.

Optional additions:

| Field | Format |
| --- | --- |
| `metrics` | Object with the fields below; missing sensors are null or omitted |
| `raw_summary` | Original provider summary object, stored as JSONB when GPS storage is enabled |
| `laps` | Ordered array of lap objects |
| `splits` | Ordered array of kilometer split objects, including a final partial kilometer |
| `hr_zones` | Array of `{zone, seconds, lower_bpm, upper_bpm}` |
| `streams` | Version 1 column arrays described below |

`metrics` accepts `moving_time_s`, `elapsed_time_s`, `average_pace_s_km`, `max_pace_s_km`,
`average_speed_m_s`, `max_speed_m_s`, `max_hr`, `average_cadence_spm`, `max_cadence_spm`,
`stride_length_cm`, `vertical_oscillation_cm`, `vertical_ratio_percent`,
`ground_contact_time_ms`, `average_power_w`, `max_power_w`, `normalized_power_w`,
`elevation_gain_m`, `elevation_loss_m`, `min_elevation_m`, `max_elevation_m`,
`average_temperature_c`, `min_temperature_c`, `max_temperature_c`, `calories`,
`aerobic_training_effect`, `anaerobic_training_effect`, `training_load`, `vo2_max`,
`started_at`, `timezone`, and `device`. These are typed PostgreSQL columns.
`max_pace_s_km` is the fastest pace, derived from maximum speed, not the slowest pace.
`started_at` must include an offset, for example `2026-09-01T07:00:00-03:00`.
Postgres retains the instant in UTC; `timezone` retains the source zone name if available.
Unknown zone/device information remains null and is not inferred from the server timezone.

Each lap/split requires `distance_m` and `duration_s`, and optionally accepts
`average_pace_s_km`, `average_hr`, `max_hr`, `average_cadence_spm`, `elevation_gain_m`,
`elevation_loss_m`, `average_power_w`, and `max_power_w`. Laps and splits have their own
ordered child tables. Heart-rate zones use a separate table. Missing zone bounds remain null;
when Garmin supplies only lower bounds, the next zone's lower bound is the exclusive upper
bound. The final zone has no inferred maximum. We never apply today's athlete zones to an old run.

Omitted or null detail sections preserve stored data on a summary-only re-sync. Empty arrays
explicitly clear that section. Non-null metrics supplied by Garmin do not erase previously
captured metrics that a list summary omits. `source` and `capture` are server bookkeeping;
imports are always treated as local and `capture` input does not change the fetch ledger.

Example, without any GPS:

```json
[
  {
    "id": "bridge-run-1", "day": "2026-09-01", "distance_km": 1,
    "duration_min": 6, "average_hr": 140,
    "metrics": {"elapsed_time_s": 370, "max_hr": 160,
                "started_at": "2026-09-01T07:00:00-03:00"},
    "laps": [{"distance_m": 1000, "duration_s": 360, "average_hr": 140}],
    "hr_zones": [{"zone": 2, "seconds": 360, "lower_bpm": 120, "upper_bpm": 150}],
    "streams": {"version": 1, "time_s": [0, 180, 360],
                "heart_rate_bpm": [120, 140, 160], "distance_m": [0, 500, 1000]}
  }
]
```

The complete machine-readable schema is [OpenAPI](openapi.json), also available through the
bearer-authenticated `/openapi.json` endpoint. The generated app types use this same contract.

## Streams and read API

`GET /activities/{id}` returns summary metrics, laps, kilometer splits, zones, and capture
status. `GET /activities/{id}/streams` returns only the streams object, or null if it has not
been supplied/captured. Both require bearer authentication. No stream is loaded during normal
plan calculations. There is no FIT download or export API in this change.

Streams are stored in `activity_streams.data` as PostgreSQL `bytea`. The `format` column is
`stride-streams-v1+json+zlib`. Decode with zlib, UTF-8, then JSON. The object contains
`version: 1`, a nonnegative ordered `time_s` array (elapsed seconds since the first sample),
and optional arrays `distance_m`, `heart_rate_bpm`, `speed_m_s`, `cadence_spm`, `elevation_m`,
`power_w`, `latitude_deg`, and `longitude_deg`. All present arrays have the same length;
missing individual samples are null. Geographic coordinates use decimal degrees.

Garmin samples are mapped by `metricDescriptors.metricsIndex`, never fixed column positions.
The request permits up to 200,000 chart samples; Garmin may still decimate or omit channels.
The original FIT preserves the original recording independently of the chart response.
When present, `directDoubleCadence` supplies steps per minute in preference to the older
`directRunCadence` channel. Descriptor-based parsing follows the pinned client's
[activity detail endpoint](https://github.com/cyberjunky/python-garminconnect/blob/v0.2.38/garminconnect/__init__.py)
and Garmin's [published example descriptor keys](https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-web/338885/connectiq-charts-no-longer-appear-on-connect-web).
Garmin laps supply kilometer splits when each lap covers one kilometer, with an optional final partial kilometer.
Otherwise, Stride Coach derives splits from cumulative distance and elapsed time.
It interpolates boundary crossings and weights sensor averages by time.
These estimates include pauses, including stationary time at the final kilometer boundary, and can differ from Garmin's display.
Missing or decreasing distance produces no derived kilometer splits. Original laps and FIT remain available. Stride Coach infers no run type.

## Original files and privacy

GPS tracks reveal home, work, and other sensitive locations. Raw summaries may also include
coordinates. The private FIT volume and database need the same access control and backup
protection as your Garmin tokens. FIT originals can contain additional personal/device data.

`STRIDE_COACH_STORE_GPS=false` strips normalized latitude/longitude arrays and skips both raw
summary storage and original FIT downloads. Omitting originals is intentional: retaining the
unchanged original and promising not to store its GPS would be contradictory. Normalized
metrics, laps, zones and other stream channels are still stored. Set the flag before initial
sync/import. It does not scrub historical data, existing FIT archives, or backups.

`STRIDE_COACH_FIT_DIR` is the archive directory, default `~/.local/share/stride-coach/fit`
outside Compose and `/data/fit` inside it. Compose mounts `STRIDE_COACH_FIT_VOLUME` there,
which defaults to the `run-originals` named volume. Set an absolute host path to use a bind
mount; make it writable only by container UID/GID `10001:10001`.

Garmin's original ZIP is read in memory; its member paths are never extracted to disk. The FIT
file keeps its exact bytes and is named using SHA-256 of the activity ID. Files are created
atomically with mode 600. Conflicting bytes for an existing ID fail capture rather than replace
the original. Summary deletion does not automatically remove archives; retain them in private
storage and account for them in backups. No personal originals belong in Git.
