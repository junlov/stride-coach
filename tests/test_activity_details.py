"""Synthetic payloads only. Exercise real PostgreSQL and authenticated transports."""

import io
import json
import stat
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from stride_coach.activity_capture import (
    archive_fit,
    capture_pending,
    fit_bytes,
    kilometer_splits,
    normalize_laps,
    normalize_metrics,
    normalize_streams,
    normalize_zones,
)
from stride_coach.activity_models import HeartRateZone, RunMetrics, RunStreams
from stride_coach.activity_storage import (
    pending_ids,
    read_detail,
    read_streams,
    save_details,
    store_gps,
)
from stride_coach.api import ServerConfig, create_app
from stride_coach.cli import app
from stride_coach.database import check_schema, migration_config
from stride_coach.db_models import (
    ActivityDetailRow,
    ActivityLapRow,
    ActivitySplitRow,
    ActivityStreamRow,
    ActivityZoneRow,
)
from stride_coach.garmin import GarminClient, normalize_activity
from stride_coach.models import Activity, ActivityCore
from stride_coach.service import Coach, SyncRequest, read_activities
from stride_coach.sync_models import SyncAttempt

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 9, 1)
TOKEN = "synthetic-run-detail-bearer-token-secret"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def payload(name):
    return json.loads((FIXTURES / f"run-{name}.json").read_text())


def fixture_activity():
    summary = payload("summary")
    activity = normalize_activity({**summary, **summary["summaryDTO"]})
    activity.metrics = normalize_metrics(summary)
    activity.raw_summary = summary
    activity.laps = normalize_laps(payload("laps"))
    activity.hr_zones = normalize_zones(payload("zones"))
    activity.streams = normalize_streams(payload("streams"), gps=True)
    activity.splits = kilometer_splits(activity.streams)
    return activity


def save(store, activity):
    store.save_sync([activity], str(DAY), str(DAY))


@pytest.fixture
def capture_client(monkeypatch, tmp_path):
    monkeypatch.setenv("STRIDE_COACH_FIT_DIR", str(tmp_path / "fit"))
    monkeypatch.setattr("stride_coach.activity_capture.time.sleep", Mock())
    api = SimpleNamespace(
        get_activity=Mock(return_value=payload("summary")),
        get_activity_splits=Mock(return_value=payload("laps")),
        get_activity_hr_in_timezones=Mock(return_value=payload("zones")),
        get_activity_details=Mock(return_value=payload("streams")),
        download_activity=Mock(return_value=(FIXTURES / "synthetic-run.fit").read_bytes()),
        ActivityDownloadFormat=SimpleNamespace(ORIGINAL="original"),
    )
    client = object.__new__(GarminClient)
    client.api = api
    client._valid_token = lambda: None
    return client


def test_roundtrip_import_and_summary_resync_preserves_details(store, tmp_path):
    activity = fixture_activity()
    activity.source = "local"
    path = tmp_path / "import.json"
    path.write_text(json.dumps([activity.model_dump(mode="json")]))
    imported = read_activities(path)[0]
    save(store, imported)
    detail = read_detail(store, activity.id)
    assert detail.metrics == activity.metrics
    assert detail.raw_summary == activity.raw_summary
    assert detail.laps == activity.laps
    assert detail.hr_zones == activity.hr_zones
    assert detail.splits == activity.splits
    assert read_streams(store, activity.id) == activity.streams
    assert detail.capture.state == "imported"
    summary_only = Activity(**activity.model_dump(include=set(ActivityCore.model_fields)))
    save(store, summary_only)
    assert read_detail(store, activity.id).laps == activity.laps
    assert read_streams(store, activity.id) == activity.streams
    # Explicit empty arrays replace children; omitted/null arrays preserve them.
    summary_only.laps = []
    save(store, summary_only)
    assert read_detail(store, activity.id).laps == []
    with store.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ActivityDetailRow)) == 1
        stream = session.get(ActivityStreamRow, activity.id)
        assert len(stream.data) < len(activity.streams.model_dump_json())
    assert pending_ids(store, 20, include_legacy=True) == []


def test_capture_is_idempotent_and_paced(store, capture_client, tmp_path):
    activity = fixture_activity()
    activity.streams = activity.laps = activity.splits = activity.hr_zones = None
    save(store, activity)
    result = capture_pending(store, capture_client)
    assert result.model_dump() == {"completed": 1, "failed": 0, "remaining": 0}
    detail = read_detail(store, activity.id)
    assert detail.capture.state == "complete"
    assert detail.capture.attempts == 1
    assert detail.capture.fit_archived
    assert detail.metrics.started_at.isoformat() == "2026-09-01T10:00:00+00:00"
    assert detail.metrics.timezone == "America/Sao_Paulo"
    assert detail.metrics.device == "Synthetic Watch"
    assert detail.metrics.normalized_power_w == 244
    assert detail.splits[0].distance_m == 1000
    assert detail.splits[-1].distance_m == 500
    assert sum(s.duration_s for s in detail.splits) == 900
    assert detail.hr_zones[0].upper_bpm == 120
    files = list((tmp_path / "fit").glob("*.fit"))
    assert len(files) == 1
    assert files[0].read_bytes() == (FIXTURES / "synthetic-run.fit").read_bytes()
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    save(store, activity)
    assert capture_pending(store, capture_client).completed == 0
    capture_client.api.get_activity.assert_called_once()
    from stride_coach.activity_capture import time

    assert time.sleep.call_count == 5
    for table, count in ((ActivityLapRow, 2), (ActivitySplitRow, 3), (ActivityZoneRow, 3)):
        with store.transaction() as session:
            assert session.scalar(select(func.count()).select_from(table)) == count


def test_resume_failure_does_not_lose_summary(store, capture_client):
    activity = fixture_activity()
    save(store, activity)
    capture_client.api.get_activity_details.side_effect = RuntimeError("secret upstream body")
    first = capture_pending(store, capture_client)
    assert first.failed == first.remaining == 1
    detail = read_detail(store, activity.id)
    assert detail.distance_km == 2.5
    assert detail.capture.state == "failed"
    assert "secret" not in detail.capture.error
    capture_client.api.get_activity_details.side_effect = None
    assert capture_pending(store, capture_client).completed == 1
    assert read_detail(store, activity.id).capture.attempts == 2
    for invalid in (0, 1001):
        with pytest.raises(ValueError, match="limit"):
            capture_pending(store, capture_client, limit=invalid)


def test_failed_capture_does_not_starve_unattempted_runs(store, capture_client):
    older = fixture_activity()
    newer = older.model_copy(update={"id": "67890"})
    store.save_sync([older, newer], str(DAY), str(DAY))
    detail = Mock()

    def fetch(activity_id, *, gps):
        if activity_id == older.id:
            raise ValueError("Permanently unavailable FIT")
        return newer, (FIXTURES / "synthetic-run.fit").read_bytes()

    detail.side_effect = fetch
    capture_client.activity_detail = detail
    assert capture_pending(store, capture_client).model_dump() == {
        "completed": 0,
        "failed": 1,
        "remaining": 2,
    }
    assert detail.call_count == 1
    assert pending_ids(store, 20) == [newer.id, older.id]
    assert capture_pending(store, capture_client).model_dump() == {
        "completed": 1,
        "failed": 1,
        "remaining": 1,
    }
    assert read_detail(store, newer.id).capture.state == "complete"
    assert read_detail(store, older.id).capture.attempts == 2


@pytest.mark.parametrize("with_details", [False, True])
def test_garmin_summary_makes_local_import_capture_eligible(store, capture_client, with_details):
    imported = (
        fixture_activity()
        if with_details
        else Activity(**fixture_activity().model_dump(include=set(ActivityCore.model_fields)))
    )
    imported.source = "local"
    save(store, imported)
    summary = normalize_activity({**payload("summary"), **payload("summary")["summaryDTO"]})
    save(store, summary)
    assert pending_ids(store, 20) == [imported.id]
    assert read_detail(store, imported.id).capture.state == "pending"
    if with_details:
        detail = read_detail(store, imported.id)
        assert detail.laps == imported.laps
        assert detail.splits == imported.splits
        assert detail.hr_zones == imported.hr_zones
        assert detail.metrics.device == imported.metrics.device
        assert read_streams(store, imported.id) == imported.streams
    assert capture_pending(store, capture_client).completed == 1
    save(store, summary)
    assert pending_ids(store, 20) == []
    assert read_detail(store, imported.id).capture.state == "complete"


@pytest.mark.parametrize(
    ("times", "distances", "durations"),
    [
        ([0, 360, 420], [0, 1000, 1000], [420]),
        ([0, 360, 720, 780], [0, 1000, 2000, 2000], [360, 420]),
        ([0, 720, 780], [0, 2000, 2000], [360, 420]),
    ],
)
def test_kilometer_splits_include_stationary_finish(times, distances, durations):
    streams = RunStreams(
        time_s=times, distance_m=distances, heart_rate_bpm=[120] * (len(times) - 1) + [150]
    )
    splits = kilometer_splits(streams)
    assert [split.duration_s for split in splits] == durations
    assert sum(split.duration_s for split in splits) == times[-1]
    assert splits[-1].average_pace_s_km == durations[-1]
    assert splits[-1].max_hr == 150
    assert splits[-1].average_hr == pytest.approx((120 * 360 + 150 * 60) / 420)


def test_capture_prefers_provider_kilometer_laps(capture_client):
    laps = payload("laps")
    laps["lapDTOs"] = [
        laps["lapDTOs"][0],
        laps["lapDTOs"][0],
        {**laps["lapDTOs"][1], "distance": 500, "duration": 200},
    ]
    capture_client.api.get_activity_splits.return_value = laps
    activity, _ = capture_client.activity_detail("12345")
    assert activity.splits == normalize_laps(laps)
    assert activity.splits[-1].duration_s == 200
    assert activity.splits != kilometer_splits(activity.streams)


def test_gps_opt_out_includes_raw_summary_fit_and_import(
    store, capture_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("STRIDE_COACH_STORE_GPS", "false")
    activity = fixture_activity()
    save(store, activity)
    assert capture_pending(store, capture_client).completed == 1
    assert read_detail(store, activity.id).raw_summary is None
    assert not read_detail(store, activity.id).capture.fit_archived
    streams = read_streams(store, activity.id)
    assert streams.latitude_deg is None and streams.longitude_deg is None
    assert streams.heart_rate_bpm
    capture_client.api.download_activity.assert_not_called()
    assert not (tmp_path / "fit").exists()
    imported = fixture_activity()
    imported.source = "local"
    save(store, imported)
    assert read_detail(store, activity.id).raw_summary is None
    assert read_streams(store, activity.id).latitude_deg is None
    monkeypatch.setenv("STRIDE_COACH_STORE_GPS", "invalid")
    with pytest.raises(ValueError, match="true or false"):
        store_gps()


def test_sync_fetches_details_and_backfill_legacy(store, capture_client, monkeypatch):
    activity = fixture_activity()
    capture_client.activities = Mock(return_value=[activity])
    coach = Coach(store, client_factory=lambda _: capture_client)
    result = coach.sync(SyncRequest(since=DAY, until=DAY))
    assert result.details.completed == 1
    # Legacy records have no source metadata and require an explicit operator opt-in.
    with store.transaction() as session:
        session.query(ActivityDetailRow).delete()
    assert pending_ids(store, 20) == []
    assert pending_ids(store, 20, include_legacy=True) == [activity.id]
    assert coach.backfill_details(include_legacy=True).completed == 1
    monkeypatch.setattr("stride_coach.service.GarminClient", lambda _: capture_client)
    monkeypatch.setattr(
        "stride_coach.cli.Coach", lambda s, _: Coach(s, client_factory=lambda _: capture_client)
    )
    response = CliRunner().invoke(app, ["backfill-details", "--limit", "2"])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["completed"] == 0


def test_http_import_detail_and_streams(database, tmp_path):
    activity = fixture_activity()
    activity.source = "local"
    config = ServerConfig(token=TOKEN, database_url=database, tokens=tmp_path / "tokens")

    def no_client(_):
        raise AssertionError("Import must not contact Garmin")

    with TestClient(create_app(config, client_factory=no_client)) as api:
        for path in (f"/activities/{activity.id}", f"/activities/{activity.id}/streams"):
            assert api.get(path).status_code == 401
        response = api.post(
            "/sync",
            headers=HEADERS,
            json={
                "since": str(DAY),
                "until": str(DAY),
                "activities": [activity.model_dump(mode="json")],
            },
        )
        assert response.status_code == 200, response.text
        detail = api.get(f"/activities/{activity.id}", headers=HEADERS).json()
        assert "streams" not in detail
        assert detail["metrics"]["max_power_w"] == 340
        assert len(detail["laps"]) == 2
        streams = api.get(f"/activities/{activity.id}/streams", headers=HEADERS).json()
        assert streams["version"] == 1 and len(streams["time_s"]) == 6
        assert api.get("/activities/missing", headers=HEADERS).status_code == 400


def test_archive_zip_path_safety_and_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("STRIDE_COACH_FIT_DIR", str(tmp_path))
    data = (FIXTURES / "synthetic-run.fit").read_bytes()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../../elsewhere.fit", data)
    name = archive_fit("../../activity", archive.getvalue())
    assert "/" not in name
    assert archive_fit("../../activity", data) == name
    with pytest.raises(ValueError, match="Invalid"):
        fit_bytes(b"invalid FIT")
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as zipped:
        zipped.writestr("other.txt", b"not fit")
    with pytest.raises(ValueError, match="one FIT"):
        fit_bytes(empty.getvalue())
    modified = data[:-1] + bytes([data[-1] ^ 1])
    with pytest.raises(ValueError, match="differs"):
        archive_fit("../../activity", modified)


def test_optional_channels_bounds_and_km_interpolation():
    assert normalize_metrics({}) == RunMetrics()
    assert normalize_streams({}, gps=True) == RunStreams()
    assert normalize_zones([]) == []
    assert normalize_laps({}) == []
    minimal = {
        "metricDescriptors": [
            {"key": "sumElapsedDuration", "metricsIndex": 0},
            {"key": "directHeartRate", "metricsIndex": 4},
        ],
        "activityDetailMetrics": [{"metrics": [0]}, {"metrics": [10]}],
    }
    assert normalize_streams(minimal, gps=True).heart_rate_bpm == [None, None]
    missing_time = {**minimal, "metricDescriptors": []}
    with pytest.raises(ValueError, match="time axis"):
        normalize_streams(missing_time, gps=True)
    minimal["activityDetailMetrics"][0]["metrics"] = []
    with pytest.raises(ValueError, match="timestamps"):
        normalize_streams(minimal, gps=True)
    for values in (
        {"time_s": [1, 0]},
        {"time_s": [0], "power_w": [1, 2]},
        {"time_s": [0], "latitude_deg": [91]},
    ):
        with pytest.raises(ValueError):
            RunStreams(**values)
    with pytest.raises(ValueError):
        HeartRateZone(zone=1, seconds=0, lower_bpm=150, upper_bpm=100)
    streams = RunStreams(time_s=[0, 600], distance_m=[0, 2500])
    splits = kilometer_splits(streams)
    assert [s.duration_s for s in splits] == [240, 240, 120]
    assert splits[0].average_hr is None
    assert kilometer_splits(RunStreams()) == []
    assert kilometer_splits(RunStreams(time_s=[0, 1], distance_m=[1, 0])) == []


def test_summary_only_unknown_format_and_cascade(store):
    activity = Activity(id="plain", day=DAY, distance_km=1, duration_min=10)
    save(store, activity)
    assert read_streams(store, "plain") is None
    for reader in (read_detail, read_streams):
        with pytest.raises(ValueError, match="not found"):
            reader(store, "missing")
    with store.transaction() as session:
        session.add(ActivityStreamRow(activity_id="plain", format="future", data=b""))
    with pytest.raises(ValueError, match="Unsupported"):
        read_streams(store, "plain")
    store.save_sync([], str(DAY), str(DAY))
    with store.transaction() as session:
        assert session.get(ActivityDetailRow, "plain") is None
        assert session.get(ActivityStreamRow, "plain") is None


def test_capture_mismatched_id_and_delay_validation(store, capture_client, monkeypatch):
    save(store, fixture_activity())
    capture_client.api.get_activity.return_value["activityId"] = 999
    assert capture_pending(store, capture_client).failed == 1
    monkeypatch.setenv("STRIDE_COACH_DETAIL_DELAY_SECONDS", "0")
    with pytest.raises(ValueError, match="delay"):
        capture_client.activity_detail("12345")


def test_summary_endpoint_aliases_and_malformed_payload(store, capture_client):
    result = normalize_metrics(
        {
            "summaryDTO": {
                "averageRunCadence": 176,
                "maxRunCadence": 190,
                "averagePower": 240,
                "normalizedPower": 255,
                "aerobicTrainingEffect": 3.2,
                "vo2MaxValue": 50,
            },
            "metadataDTO": {"deviceId": 123},
            "timeZoneUnitDTO": {"unitKey": "Europe/Paris"},
        }
    )
    assert result.average_cadence_spm == 176
    assert result.average_power_w == 240
    assert result.normalized_power_w == 255
    assert result.aerobic_training_effect == 3.2
    assert result.vo2_max == 50
    assert result.device == "123" and result.timezone == "Europe/Paris"
    save(store, fixture_activity())
    capture_client.api.get_activity.return_value = {}
    assert capture_pending(store, capture_client).failed == 1
    assert read_detail(store, "12345").capture.state == "failed"


def test_stream_descriptor_units_and_double_cadence():
    data = {
        "metricDescriptors": [
            {"key": "sumElapsedDuration", "metricsIndex": 0, "unit": {"key": "ms"}},
            {"key": "sumDistance", "metricsIndex": 1, "unit": {"key": "km"}},
            {"key": "directRunCadence", "metricsIndex": 2},
            {"key": "directDoubleCadence", "metricsIndex": 3},
            {"key": "directSpeed", "metricsIndex": 4, "unit": {"unitKey": "kph"}},
        ],
        "activityDetailMetrics": [
            {"metrics": [0, 0, 85, 170, 10.8]},
            {"metrics": [1000, 0.003, 86, 172, 10.8]},
        ],
    }
    result = normalize_streams(data, gps=False)
    assert result.time_s == [0, 1]
    assert result.distance_m == [0, 3]
    assert result.cadence_spm == [170, 172]
    assert result.speed_m_s == pytest.approx([3, 3])


def test_run_data_then_sync_migration_preserves_data(store):
    activity = fixture_activity()
    save(store, activity)
    with store.connection.begin():
        command.downgrade(migration_config(store.connection), "0002")
        command.upgrade(migration_config(store.connection), "0003_run_data")
    with store.transaction() as session:
        save_details(session, activity)
    with store.connection.begin():
        command.upgrade(migration_config(store.connection), "head")
        check_schema(store.connection)
    assert read_detail(store, activity.id).laps == activity.laps
    assert read_detail(store, activity.id).metrics == activity.metrics
    assert read_streams(store, activity.id) == activity.streams
    attempt = SyncAttempt(
        id="migration-import",
        source="history",
        started_at=datetime.now(UTC),
        since=DAY,
        until=DAY,
        history_range="12-weeks",
    )
    store.save_history_page(attempt, [activity])
    assert store.sync_status().history.id == attempt.id
    assert store.sync_status().history.next_page == 0


def test_history_pages_preserve_run_details_and_capture_checkpoints(store, capture_client):
    activity = fixture_activity()
    summary = activity.model_copy(
        update={"laps": None, "splits": None, "hr_zones": None, "streams": None}
    )
    attempt = SyncAttempt(
        id="detail-import",
        source="history",
        started_at=datetime.now(UTC),
        since=DAY,
        until=DAY,
        history_range="12-weeks",
        next_page=1,
        activity_count=1,
    )
    store.save_history_page(attempt, [summary])
    assert read_detail(store, activity.id).metrics == activity.metrics
    assert pending_ids(store, 20) == [activity.id]
    assert capture_pending(store, capture_client).completed == 1
    captured = read_detail(store, activity.id)
    store.save_history_page(attempt, [summary])
    assert read_detail(store, activity.id) == captured
    assert read_streams(store, activity.id) == activity.streams
    assert store.sync_status().history.next_page == 1
    assert store.sync_window(complete=True) == {}
