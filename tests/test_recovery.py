import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin import GarminClient, GarminError
from stride_coach.mcp import create_server
from stride_coach.models import Kind
from stride_coach.recovery import parse_readiness, poor_recovery
from stride_coach.recovery_models import DailyAdaptRequest, DailyReadiness
from stride_coach.service import AdaptRequest, Coach, PushRequest, SyncRequest


@pytest.fixture
def recovery_day(store):
    return next(w.day for w in store.plan().workouts if w.kind == Kind.TEMPO) - timedelta(days=1)


def reading(day, **kwargs):
    return DailyReadiness(day=day, fetched_at=datetime.now(UTC), **kwargs)


def test_parse_optional_and_invalid_fields(setup):
    day = setup.start
    result = parse_readiness(day)
    assert result.training_readiness is result.hrv_status is result.sleep_score is None
    for invalid in [
        None,
        [],
        "missing",
        {"score": False},
        {"score": -1},
        {"score": 101},
        {"score": float("nan")},
    ]:
        assert parse_readiness(day, invalid, invalid, invalid).training_readiness is None
    result = parse_readiness(
        day,
        [
            {"calendarDate": str(day - timedelta(days=1)), "score": 0},
            {"score": 80},
            {"inputContext": "AFTER_WAKEUP_RESET", "score": 24},
        ],
        {"hrvSummary": {"calendarDate": str(day), "status": "LOW"}},
        {"dailySleepDTO": {"calendarDate": str(day), "sleepScores": {"overall": {"value": 49}}}},
    )
    assert (result.training_readiness, result.hrv_status, result.sleep_score) == (24, "LOW", 49)
    assert len(poor_recovery(result)) == 3
    assert (
        parse_readiness(day, {"calendarDate": "2000-01-01", "score": 0}).training_readiness is None
    )
    assert parse_readiness(day, hrv={"hrvSummary": {"status": "new-status"}}).hrv_status is None
    assert (
        parse_readiness(
            day, sleep={"dailySleepDTO": {"sleepScores": {"overall": {"value": "49"}}}}
        ).sleep_score
        is None
    )


@pytest.mark.parametrize(
    ("values", "triggered"),
    [
        ({}, False),
        ({"training_readiness": 0}, True),
        ({"training_readiness": 24}, True),
        ({"training_readiness": 25}, False),
        ({"sleep_score": 49}, True),
        ({"sleep_score": 50}, False),
        ({"hrv_status": "LOW"}, True),
        ({"hrv_status": "POOR"}, True),
        ({"hrv_status": "UNBALANCED"}, False),
        ({"hrv_status": "UNKNOWN"}, False),
    ],
)
def test_rule_thresholds(setup, values, triggered):
    assert bool(poor_recovery(reading(setup.start, **values))) is triggered


def test_optional_garmin_endpoints_and_sleep_identifier(setup):
    client = GarminClient.__new__(GarminClient)
    client._valid_token = lambda: None
    api = SimpleNamespace(
        get_training_readiness=Mock(return_value=[{"score": 20}]),
        get_hrv_data=Mock(side_effect=GarminError("not supported")),
        connectapi=Mock(
            return_value={"displayName": "synthetic-id", "fullName": "Synthetic Runner"}
        ),
        get_sleep_data=Mock(
            return_value={"dailySleepDTO": {"sleepScores": {"overall": {"value": 40}}}}
        ),
    )
    client.api = api
    result = client.readiness(setup.start)
    assert result.training_readiness == 20
    assert result.hrv_status is None
    assert result.sleep_score == 40
    assert api.display_name == "synthetic-id"
    api.get_sleep_data.assert_called_once_with(str(setup.start))
    api.connectapi.side_effect = GarminError("profile missing")
    assert client.readiness(setup.start).sleep_score is None


def test_sync_missing_readiness_is_successful_and_replaces_old_data(store, recovery_day):
    client = SimpleNamespace(
        activities=lambda *args: [], readiness=lambda day: reading(day, sleep_score=10)
    )
    coach = Coach(store, client_factory=lambda _: client)
    request = SyncRequest(since=recovery_day, until=recovery_day)
    coach.sync(request, today=recovery_day)
    assert coach.readiness()[0].sleep_score == 10
    client.readiness = Mock(side_effect=GarminError("secret provider exception"))
    coach.sync(request, today=recovery_day)
    assert store.sync_status().latest.result == "success"
    assert store.readiness(recovery_day).sleep_score is None
    assert coach.daily_adjustment(today=recovery_day).after is None


def test_daily_confirmation_idempotency_and_garmin_preview(store, recovery_day):
    store.save_readiness(reading(recovery_day, sleep_score=20))
    coach = Coach(store, client_factory=lambda _: pytest.fail("No Garmin call expected"))
    before_plan = coach.plan()
    proposal = coach.daily_adjustment(today=recovery_day)
    assert proposal.after.kind == Kind.EASY
    assert proposal.before.minutes == proposal.after.minutes
    assert coach.plan() == before_plan
    assert store.daily_adjustments() == []
    with pytest.raises(ValueError, match="missing or stale"):
        coach.daily_adjustment(DailyAdaptRequest(apply=True), today=recovery_day)
    store.save_remote(proposal.before.id, "123", "old", True)
    with pytest.raises(ValueError, match="missing or stale"):
        coach.daily_adjustment(
            DailyAdaptRequest(apply=True, proposal_fingerprint=proposal.proposal_fingerprint),
            today=recovery_day,
        )
    proposal = coach.daily_adjustment(today=recovery_day)
    assert proposal.garmin_update_required
    request = DailyAdaptRequest(apply=True, proposal_fingerprint=proposal.proposal_fingerprint)
    result = coach.daily_adjustment(request, today=recovery_day)
    assert result.applied
    assert coach.daily_adjustment(request, today=recovery_day + timedelta(days=1)) == result
    assert len(store.daily_adjustments()) == 1
    after_plan = coach.plan()
    for before, after in zip(before_plan.workouts, after_plan.workouts, strict=True):
        assert before.minutes == after.minutes
        if before.id != proposal.before.id:
            assert before == after
    assert store.scheduled(proposal.before.id)["remote_id"] == "123"
    push = coach.push(PushRequest(workout=proposal.before.id), today=recovery_day)
    assert push[0].action == "preview"
    assert store.scheduled(proposal.before.id)["fingerprint"] == "old"
    assert coach.status().daily_adjustments == [result]
    assert coach.daily_adjustment(today=recovery_day).after is None


def test_daily_stale_readiness_date_plan_and_weekly_safeguards(store, recovery_day):
    coach = Coach(store)
    store.save_readiness(reading(recovery_day - timedelta(days=1), sleep_score=1))
    assert coach.daily_adjustment(today=recovery_day).after is None
    store.save_readiness(reading(recovery_day, training_readiness=24))
    proposal = coach.daily_adjustment(today=recovery_day)
    request = DailyAdaptRequest(apply=True, proposal_fingerprint=proposal.proposal_fingerprint)
    with pytest.raises(ValueError, match="missing or stale"):
        coach.daily_adjustment(request, today=recovery_day + timedelta(days=1))
    store.save_readiness(reading(recovery_day, training_readiness=80))
    with pytest.raises(ValueError, match="missing or stale"):
        coach.daily_adjustment(request, today=recovery_day)
    with pytest.raises(ValueError, match="Monday"):
        coach.adapt(AdaptRequest(week=proposal.before.week, apply=True), today=recovery_day)
    store.save_readiness(reading(recovery_day, training_readiness=24))
    proposal = coach.daily_adjustment(today=recovery_day)
    from sqlalchemy import update

    from stride_coach.db_models import StepRow

    with store.transaction() as session:
        session.execute(
            update(StepRow).where(StepRow.workout_id == proposal.before.id).values(minutes=5)
        )
    with pytest.raises(ValueError, match="missing or stale"):
        coach.daily_adjustment(
            DailyAdaptRequest(apply=True, proposal_fingerprint=proposal.proposal_fingerprint),
            today=recovery_day,
        )


def test_api_and_mcp_preview_never_apply(store, recovery_day, tmp_path):
    token = "synthetic-recovery-token-with-32-characters"
    headers = {"Authorization": f"Bearer {token}"}
    config = ServerConfig(
        token=token, database_url=store.url, tokens=tmp_path / "tokens", sync_enabled=False
    )
    store.save_readiness(reading(recovery_day, sleep_score=30))
    app = create_app(config, client_factory=lambda _: pytest.fail("Garmin must not be called"))
    app.state.sync_worker.now = lambda: datetime.combine(recovery_day, datetime.min.time(), UTC)
    with TestClient(app) as api:
        assert api.get("/readiness").status_code == 401
        assert api.get("/adjustments/daily").status_code == 401
        assert api.post("/adapt/daily", json={}).status_code == 401
        assert api.get("/readiness", headers=headers).json()[0]["sleep_score"] == 30
        proposal = api.get("/adjustments/daily", headers=headers).json()
        assert proposal["after"]["kind"] == "easy"
        assert not api.post("/adapt/daily", headers=headers, json={}).json()["applied"]
        assert api.post("/adapt/daily", headers=headers, json={"apply": True}).status_code == 400
        response = api.post(
            "/adapt/daily",
            headers=headers,
            json={"apply": True, "proposal_fingerprint": proposal["proposal_fingerprint"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"]

    async def exercise():
        server = create_server(store.url)
        for name in ["readiness", "propose_daily_adjustment"]:
            assert await server.call_tool(name, {})

    asyncio.run(exercise())
    assert len(store.daily_adjustments()) == 1


def test_monday_volume_reduction_preserves_daily_softening(store, recovery_day):
    """A daily change cannot restore volume or stop the normal weekly reduction."""
    from stride_coach.db_models import WorkoutRow

    coach = Coach(store)
    hard = next(w for w in coach.plan().workouts if w.kind == Kind.TEMPO)
    monday = hard.day - timedelta(days=hard.day.weekday())
    # Use a Monday hard workout to exercise Sunday daily softening followed by weekly apply.
    with store.transaction() as session:
        session.get(WorkoutRow, hard.id).day = monday
    sunday = monday - timedelta(days=1)
    store.save_readiness(reading(sunday, sleep_score=20))
    preview = coach.daily_adjustment(today=sunday)
    assert preview.after.id == hard.id
    coach.daily_adjustment(
        DailyAdaptRequest(apply=True, proposal_fingerprint=preview.proposal_fingerprint),
        today=sunday,
    )
    coach.sync(
        SyncRequest(since=monday - timedelta(days=14), until=sunday, activities=[]), today=monday
    )
    weekly = coach.adapt(AdaptRequest(week=hard.week), today=monday)
    coach.adapt(
        AdaptRequest(
            week=hard.week, apply=True, proposal_fingerprint=weekly.inputs["proposal_fingerprint"]
        ),
        today=monday,
    )
    changed = next(w for w in coach.plan().workouts if w.id == hard.id)
    assert changed.kind == Kind.EASY
    assert changed.minutes == pytest.approx(hard.minutes * weekly.factor)
    assert changed.minutes < hard.minutes


def test_sync_rejects_wrong_day_recovery_without_failing(store, recovery_day):
    client = SimpleNamespace(
        activities=lambda *args: [],
        readiness=lambda day: reading(day - timedelta(days=1), sleep_score=10),
    )
    Coach(store, client_factory=lambda _: client).sync(
        SyncRequest(since=recovery_day), today=recovery_day
    )
    assert store.readiness(recovery_day).sleep_score is None
    assert store.sync_status().latest.result == "success"


def test_confirmed_daily_change_updates_same_owned_garmin_workout_only_on_apply(
    store, recovery_day
):
    from test_garmin import FakeGarmin

    from stride_coach.service import RemoveRequest

    fake = FakeGarmin()
    coach = Coach(store, client_factory=lambda _: fake)
    hard = next(w for w in coach.plan().workouts if w.day == recovery_day + timedelta(days=1))
    coach.push(PushRequest(workout=hard.id, apply=True), today=recovery_day)
    remote_id = store.scheduled(hard.id)["remote_id"]
    assert fake.writes == ["create", "schedule"]
    store.save_readiness(reading(recovery_day, sleep_score=10))
    preview = coach.daily_adjustment(today=recovery_day)
    coach.daily_adjustment(
        DailyAdaptRequest(apply=True, proposal_fingerprint=preview.proposal_fingerprint),
        today=recovery_day,
    )
    assert fake.writes == ["create", "schedule"]
    coach.push(PushRequest(workout=hard.id, dry_run=True), today=recovery_day)
    coach.remove(RemoveRequest(dry_run=True))
    assert fake.writes == ["create", "schedule"]
    result = coach.push(PushRequest(workout=hard.id, apply=True), today=recovery_day)
    assert result[0].action == "updated"
    assert store.scheduled(hard.id)["remote_id"] == remote_id
    assert fake.writes == ["create", "schedule", "update"]
