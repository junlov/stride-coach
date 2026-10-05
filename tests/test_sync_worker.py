from datetime import UTC, date, datetime, timedelta
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from stride_coach.adaptation import adapt
from stride_coach.api import ServerConfig, create_app
from stride_coach.db_models import SyncAttemptRow
from stride_coach.garmin import GarminClient, GarminError
from stride_coach.garmin_auth import GarminConnection
from stride_coach.models import Activity
from stride_coach.service import AdaptRequest, Coach, SyncRequest
from stride_coach.storage import Store
from stride_coach.sync_models import HistoryRequest, SyncAttempt
from stride_coach.sync_worker import SyncWorker, history_start

TOKEN = "synthetic-api-token-at-least-32-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 10, 12, 7, tzinfo=UTC)


@pytest.fixture
def worker(database, tmp_path, monkeypatch):
    config = ServerConfig(token=TOKEN, database_url=database, tokens=tmp_path / "tokens")
    connection = GarminConnection(config.tokens, database_url=database)
    with connection.vault.locked():
        connection.vault.write({"tokens": "synthetic-session", "generation": "test"})
    factory = Mock()
    factory.return_value.activities.return_value = []
    worker = SyncWorker(config, connection, factory)
    monkeypatch.setattr(worker, "now", lambda: NOW)
    yield worker
    worker.close()
    connection.close()


def run(id, day=None):
    return Activity(id=str(id), day=day or NOW.date(), distance_km=5, duration_min=30)


def test_daily_single_run_and_interval_survive_new_worker(worker, store):
    worker.tick()
    worker.tick()
    assert worker.client_factory.call_count == 1
    last = store.sync_status().latest
    assert last.source == "daily" and last.result == "success"
    assert last.started_at == NOW and last.finished_at
    other = SyncWorker(worker.config, worker.connection, worker.client_factory)
    assert other.automatic(store, "app-open", NOW + timedelta(hours=5)).skipped
    other.automatic(store, "app-open", NOW + timedelta(hours=6))
    assert worker.client_factory.call_count == 2
    assert store.sync_status().latest.source == "app-open"


def test_time_and_disabled_daily_still_process_history(worker, monkeypatch):
    worker.config.sync_time = "08:00"
    worker.tick()
    assert not worker.client_factory.called
    worker.config.sync_enabled = False
    worker.config.sync_time = "06:00"
    worker.tick()
    assert not worker.client_factory.called


@pytest.mark.parametrize("source", ["daily", "app-open"])
def test_automatic_sync_preserves_non_runs(worker, store, source):
    activities = [
        run(sport).model_copy(update={"sport": sport})
        for sport in ("walking", "cycling", "strength_training")
    ]
    store.save_sync(activities, str(NOW.date()), str(NOW.date()), today=NOW.date())
    worker.client_factory.return_value.activities.return_value = [run("new-run")]
    result = worker.automatic(store, source, NOW)
    assert result.latest.result == "success"
    assert result.latest.activity_count == 1
    assert {a.id for a in store.activities()} == {"new-run", *(a.id for a in activities)}
    assert all(a in store.activities() for a in activities)


def test_disconnected_skips_silently_without_adapter_or_plan(worker, database):
    worker.connection.logout()
    store = Store(database)
    try:
        result = worker.automatic(store, "app-open", NOW)
        assert result.skipped and result.latest is None
        assert not worker.client_factory.called
        with pytest.raises(ValueError, match="Connect Garmin"):
            worker.enqueue(store, HistoryRequest(range="12-weeks"))
    finally:
        store.close()


def test_overlapping_workers_skip_and_regular_lock_blocks_import(worker, store, database):
    entered, release = Event(), Event()

    def slow(*args):
        entered.set()
        assert release.wait(5)
        return []

    worker.client_factory.return_value.activities.side_effect = slow
    thread = Thread(target=worker.tick)
    thread.start()
    try:
        assert entered.wait(5)
        other = Store(database)
        try:
            assert worker.automatic(other, "app-open", NOW).skipped
            worker.history_page(other)
        finally:
            other.close()
    finally:
        release.set()
        thread.join(5)
    assert worker.client_factory.call_count == 1
    assert store.sync_status().latest.result == "success"


def test_expired_session_records_safe_error_and_no_password_retry(worker, store):
    worker.client_factory.side_effect = GarminError("synthetic token must not leak")
    result = worker.automatic(store, "daily", NOW)
    assert result.latest.result == "error"
    assert result.latest.finished_at
    assert "reconnect Garmin" in result.latest.error
    assert "synthetic token" not in result.latest.error
    worker.automatic(store, "daily", NOW)
    assert worker.client_factory.call_count == 1


def test_manual_status_persisted_even_on_failure(store):
    coach = Coach(store)
    coach.sync(SyncRequest(activities=[run(1)], since=NOW.date()), today=NOW.date())
    status = store.sync_status()
    assert status.latest.activity_count == 1
    assert status.latest.since == status.latest.until == NOW.date()
    coach.client_factory = Mock(side_effect=GarminError("secret"))
    with pytest.raises(GarminError):
        coach.sync(SyncRequest(since=NOW.date()), today=NOW.date())
    reopened = Store(store.url)
    try:
        result = reopened.sync_status()
        assert result.latest.result == "error"
        assert result.last_success == status.last_success
        assert result.latest.error and "secret" not in result.latest.error
    finally:
        reopened.close()


def test_paced_history_resumes_after_restart_and_is_idempotent(worker, store, monkeypatch):
    worker.config.sync_enabled = False
    first = [run(i) for i in range(100)]
    worker.client_factory.return_value.activity_page.side_effect = [first, [run(100)]]
    job = worker.enqueue(store, HistoryRequest(range="12-weeks"))
    assert worker.enqueue(store, HistoryRequest(range="everything")).id == job.id
    worker.tick()
    partial = store.sync_status().history
    assert partial.next_page == partial.activity_count == 100
    worker.tick()  # Persisted pacing also protects against another worker's immediate tick.
    assert worker.client_factory.return_value.activity_page.call_count == 1
    restarted = SyncWorker(worker.config, worker.connection, worker.client_factory)
    monkeypatch.setattr(restarted, "now", lambda: NOW + timedelta(seconds=2))
    restarted.tick()
    finished = store.sync_status().history
    assert finished.result == "success" and finished.finished_at
    assert finished.activity_count == 101
    assert len(store.activities()) == 101
    assert worker.client_factory.return_value.activity_page.call_args.args[2] == 100
    assert worker.enqueue(store, HistoryRequest(range="12-weeks")) == finished
    worker.tick()
    assert worker.client_factory.return_value.activity_page.call_count == 2
    assert store.sync_window(complete=True) == {}  # Partial import never authorizes adaptation.


def test_failed_page_cursor_is_not_advanced_and_can_resume(worker, store, monkeypatch):
    worker.config.sync_enabled = False
    worker.client_factory.return_value.activity_page.side_effect = [
        [run(i) for i in range(100)],
        GarminError("private upstream error"),
        [run(100)],
    ]
    worker.enqueue(store, HistoryRequest(range="everything"))
    worker.tick()
    monkeypatch.setattr(worker, "now", lambda: NOW + timedelta(seconds=2))
    worker.tick()
    failed = store.sync_status().history
    assert failed.result == "error" and failed.next_page == 100
    assert "private" not in failed.error
    worker.enqueue(store, HistoryRequest(range="everything"))
    worker.tick()
    assert store.sync_status().history.result == "success"
    assert len(store.activities()) == 101


def test_import_page_and_cursor_roll_back_together(worker, store, monkeypatch):
    worker.client_factory.return_value.activity_page.return_value = [run(1)]
    worker.enqueue(store, HistoryRequest(range="6-months"))
    original = store._refresh_matches
    monkeypatch.setattr(store, "_refresh_matches", Mock(side_effect=RuntimeError("crash")))
    worker.history_page(store)
    assert not store.activities()
    # A failed transaction must preserve the database cursor, not the in-memory increment.
    assert store.sync_status().history.next_page == 0
    monkeypatch.setattr(store, "_refresh_matches", original)
    worker.enqueue(store, HistoryRequest(range="6-months"))
    worker.history_page(store)
    assert len(store.activities()) == 1


def test_ranges():
    assert history_start("12-weeks", NOW.date()) == date(2026, 7, 20)
    assert history_start("6-months", date(2026, 8, 31)) == date(2026, 2, 28)
    assert history_start("everything", NOW.date()) == date(1970, 1, 1)


def test_reasons_and_inputs_survive_activity_replacement(store):
    monday = store.plan().setup.start + timedelta(weeks=1)
    store.save_sync([], str(monday - timedelta(days=14)), str(monday), today=monday)
    applied = adapt(
        store,
        2,
        monday,
        apply=True,
        proposal_fingerprint=adapt(store, 2, monday).inputs["proposal_fingerprint"],
    )
    store.save_sync([run(1, monday)], str(monday), str(monday), today=monday)
    recovered = store.adjustment(2)
    assert recovered.reasons == applied.reasons
    assert recovered.inputs == applied.inputs
    assert recovered.inputs["current_week"]["matched_sessions"] == 0
    assert recovered.inputs["complete_sync_window"]["until"] == str(monday - timedelta(days=1))


def test_history_api_auth_validation_and_no_plan_needed(database, tmp_path, monkeypatch):
    config = ServerConfig(token=TOKEN, database_url=database, tokens=tmp_path / "tokens")
    app = create_app(config, client_factory=Mock())
    monkeypatch.setattr(app.state.sync_worker, "start", lambda: None)
    with TestClient(app) as api:
        for method, path in [
            ("get", "/sync/status"),
            ("post", "/sync/open"),
            ("post", "/sync/history"),
        ]:
            assert getattr(api, method)(path).status_code == 401
        assert api.post("/sync/open", headers=HEADERS).json()["skipped"]
        assert api.get("/sync/status", headers=HEADERS).json()["latest"] is None
        assert (
            api.post("/sync/history", headers=HEADERS, json={"range": "wrong"}).status_code == 422
        )
        with app.state.garmin_connection.vault.locked():
            app.state.garmin_connection.vault.write({"tokens": "synthetic", "generation": "test"})
        result = api.post("/sync/history", headers=HEADERS, json={"range": "6-months"})
        assert result.status_code == 200
        assert result.json()["result"] == "running"
        assert (
            api.get("/sync/status", headers=HEADERS).json()["history"]["id"] == result.json()["id"]
        )
    store = Store(database)
    try:
        with store.transaction() as session:
            assert session.scalar(select(func.count()).select_from(SyncAttemptRow)) == 1
    finally:
        store.close()


def test_scheduler_env_validation(monkeypatch, database):
    monkeypatch.setenv("STRIDE_COACH_API_TOKEN", TOKEN)
    monkeypatch.setenv("STRIDE_COACH_SYNC_ENABLED", "false")
    monkeypatch.setenv("STRIDE_COACH_SYNC_TIME", "23:59")
    monkeypatch.setenv("STRIDE_COACH_SYNC_OPEN_HOURS", "3")
    monkeypatch.setenv("STRIDE_COACH_IMPORT_PAGE_DELAY", "2")
    config = ServerConfig.from_env()
    assert not config.sync_enabled and config.sync_time == "23:59"
    assert config.sync_open_hours == 3 and config.import_page_delay == 2
    with pytest.raises(ValidationError):
        ServerConfig.from_env(sync_time="25:00")


def test_adapter_uses_one_bounded_ascending_page():
    client = GarminClient.__new__(GarminClient)
    client.api = Mock()
    client.api.garmin_connect_activities = "/activities"
    client._call = Mock(
        return_value=[
            {
                "activityId": 1,
                "startTimeLocal": "2026-10-12T10:00:00",
                "distance": 5000,
                "duration": 1800,
                "activityType": {"typeKey": "running"},
            }
        ]
    )
    assert client.activity_page(NOW.date(), NOW.date(), 100)[0].id == "1"
    params = client._call.call_args.kwargs["params"]
    assert params["start"] == "100" and params["limit"] == "100" and params["sortOrder"] == "asc"
    client._call.return_value = {}
    with pytest.raises(GarminError, match="Unexpected"):
        client.activity_page(NOW.date(), NOW.date(), 0)


def test_interrupted_regular_attempt_recovers_when_lock_is_free(worker, store):
    store.save_attempt(
        SyncAttempt(
            id="interrupted",
            source="app-open",
            started_at=NOW,
            since=NOW.date() - timedelta(days=28),
            until=NOW.date(),
        )
    )
    status = worker.automatic(store, "app-open", NOW + timedelta(minutes=1))
    assert status.skipped and status.latest.result == "error"
    assert status.latest.finished_at == NOW + timedelta(minutes=1)
    assert "interrupted" in status.latest.error
    assert not worker.client_factory.called


def test_start_is_single_instance_and_shutdown_interrupts_wait(worker, monkeypatch):
    factory = Mock()
    monkeypatch.setattr("stride_coach.sync_worker.Thread", factory)
    worker.start()
    worker.start()
    assert factory.call_count == 1
    factory.return_value.start.assert_called_once()
    worker.close()
    assert worker.stop.is_set()
    factory.return_value.join.assert_called_once()


def test_daily_sync_invalidates_reviewed_adjustment(worker, store):
    monday = NOW.date()
    plan = store.plan()
    store.save_sync([], str(monday - timedelta(days=14)), str(monday), today=monday)
    coach = Coach(store)
    preview = coach.propose_adjustment(2).adjustment
    assert preview.factor == 0.75
    request = AdaptRequest(
        week=2, apply=True, proposal_fingerprint=preview.inputs["proposal_fingerprint"]
    )
    worker.client_factory.return_value.activities.return_value = [
        Activity(
            id=w.id,
            day=w.day,
            duration_min=w.minutes,
            distance_km=w.minutes / 8,
            average_hr=140,
            kind=w.kind,
        )
        for w in plan.workouts
        if w.week == 1
    ]
    worker.tick()
    with pytest.raises(ValueError, match="review the new proposal"):
        coach.adapt(request, today=monday)
    assert store.plan() == plan
    assert store.adjustment(2) is None
    fresh = coach.propose_adjustment(2).adjustment
    assert fresh.inputs["proposal_fingerprint"] != request.proposal_fingerprint
    assert fresh.factor != preview.factor
    request.proposal_fingerprint = fresh.inputs["proposal_fingerprint"]
    applied = coach.adapt(request, today=monday)
    assert applied.applied
    assert applied.factor == fresh.factor
    assert coach.adapt(request, today=monday) == applied
