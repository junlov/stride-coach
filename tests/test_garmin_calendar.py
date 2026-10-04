from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_garmin import FakeGarmin

from stride_coach.api import ServerConfig, create_app
from stride_coach.db_models import StepRow
from stride_coach.garmin import GarminError, push, reconcile_calendar, tag, workout_payload
from stride_coach.models import Activity
from stride_coach.service import CalendarRequest, CalendarSettings, Coach, PushRequest
from stride_coach.storage import Store


def test_window_persists_and_limits_ordinary_push(store):
    coach = Coach(store)
    start = store.plan().setup.start
    assert coach.calendar_settings().window_days == 14
    coach.save_calendar_settings(CalendarSettings(window_days=7))
    with pytest.raises(ValueError):
        CalendarSettings(window_days=29)
    with pytest.raises(ValueError):
        CalendarSettings(window_days=7.5)
    with pytest.raises(ValueError):
        store.save_calendar_settings(6)
    reopened = Store(store.url)
    try:
        assert reopened.calendar_settings()["window_days"] == 7
    finally:
        reopened.close()
    preview = coach.push(PushRequest(), today=start)
    assert preview and all(
        start.isoformat() <= p.date < (start + timedelta(days=7)).isoformat() for p in preview
    )
    with pytest.raises(ValueError, match="No future"):
        coach.push(PushRequest(week=3), today=start)


def test_reconcile_preview_confirm_and_no_op(store):
    client = FakeGarmin()
    start = store.plan().setup.start
    preview = reconcile_calendar(store, client, start)
    assert len(preview["changes"]) == 8
    assert {c["action"] for c in preview["changes"]} == {"create"}
    assert not client.writes
    assert not store.scheduled_count()
    with pytest.raises(ValueError, match="preview"):
        reconcile_calendar(store, client, start, apply=True)
    reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert client.writes.count("create") == 8
    assert client.writes.count("schedule") == 8
    assert reconcile_calendar(store, client, start)["changes"] == []
    assert store.calendar_settings()["synced_fingerprint"]


def test_updates_removals_and_unowned_protection(store):
    client = FakeGarmin()
    plan = store.plan()
    start = plan.setup.start
    push(store, plan.workouts[:12], client, False)
    client.data["999"] = {"workoutId": "999", "workoutName": f"SC {plan.workouts[0].id} personal"}
    orphan = workout_payload(plan.workouts[0])
    orphan["description"] = "stride-coach:v1:old-plan-2026-10-01"
    client.data["888"] = {**orphan, "workoutId": "888"}
    with store.transaction() as session:
        session.get(StepRow, (plan.workouts[0].id, 0)).minutes *= 0.8
    client.writes.clear()
    preview = reconcile_calendar(store, client, start)
    assert [c["action"] for c in preview["changes"]].count("update") == 1
    assert [c["action"] for c in preview["changes"]].count("remove") == 5
    assert not client.writes
    reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert client.writes.count("update") == 1
    assert "999" in client.data and "888" not in client.data
    assert len(client.events) == 8
    assert store.scheduled_count() == 8


def test_past_removal_requires_coverage_and_preserves_completed(store):
    client = FakeGarmin()
    plan = store.plan()
    push(store, plan.workouts[:4], client, False)
    today = plan.setup.start + timedelta(days=7)
    before = reconcile_calendar(store, client, today)
    assert not any(c["action"] == "remove" for c in before["changes"])
    completed = plan.workouts[0]
    store.save_sync(
        [Activity(id="finished", day=completed.day, distance_km=5, duration_min=30)],
        str(plan.setup.start),
        str(today - timedelta(days=1)),
        today=today,
    )
    preview = reconcile_calendar(store, client, today)
    removed = [c["workout_id"] for c in preview["changes"] if c["action"] == "remove"]
    assert set(removed) == {w.id for w in plan.workouts[1:4]}
    reconcile_calendar(store, client, today, apply=True, preview_id=preview["preview_id"])
    assert any(r["description"] == tag(completed) for r in client.data.values())


@pytest.mark.parametrize("change", ["setting", "plan", "ownership", "calendar", "day"])
def test_stale_preview_rejected_before_any_write(store, change):
    client = FakeGarmin()
    plan = store.plan()
    start = plan.setup.start
    push(store, plan.workouts[:1], client, False)
    preview = reconcile_calendar(store, client, start)
    if change == "setting":
        store.save_calendar_settings(7)
    elif change == "plan":
        with store.transaction() as session:
            session.get(StepRow, (plan.workouts[0].id, 0)).minutes *= 0.8
    elif change == "ownership":
        client.data["1"]["description"] = "Personal workout"
    elif change == "calendar":
        client.events.append(
            {"id": 999, "workoutId": "999", "date": str(start), "itemType": "workout"}
        )
    else:
        start += timedelta(days=1)
    client.writes.clear()
    with pytest.raises((ValueError, GarminError)):
        reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert not client.writes


def test_lost_create_response_recovers_after_new_preview(store):
    client = FakeGarmin()
    start = store.plan().setup.start
    preview = reconcile_calendar(store, client, start)
    client.fail_create = True
    with pytest.raises(GarminError, match="Response lost"):
        reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert not store.calendar_settings()["synced_fingerprint"]
    client.fail_create = False
    preview = reconcile_calendar(store, client, start)
    reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert client.writes.count("create") == 8


def test_duplicate_tags_and_hidden_cached_workouts_refuse_writes(store):
    client = FakeGarmin()
    start = store.plan().setup.start
    push(store, store.plan().workouts[:1], client, False)
    client.data["999"] = {**client.data["1"], "workoutId": "999"}
    with pytest.raises(GarminError, match="Multiple"):
        reconcile_calendar(store, client, start)
    client.hide_workouts = True
    with pytest.raises(GarminError, match="unresolved"):
        reconcile_calendar(store, client, start)


def test_calendar_api_auth_and_settings_validation(database, store, tmp_path, monkeypatch):
    import stride_coach.service as service

    start = store.plan().setup.start

    class Clock(type(start)):
        @classmethod
        def today(cls):
            return start

    monkeypatch.setattr(service, "date", Clock)
    fake = FakeGarmin()
    token = "synthetic-calendar-token-with-32-characters"
    config = ServerConfig(token=token, database_url=database, tokens=tmp_path)
    with TestClient(create_app(config, client_factory=lambda _: fake)) as api:
        headers = {"Authorization": f"Bearer {token}"}
        assert api.post("/calendar", json={}).status_code == 401
        assert api.post("/calendar/settings", json={"window_days": 7}).status_code == 401
        for days in (6, 29, 14.5, "14"):
            assert (
                api.post(
                    "/calendar/settings", json={"window_days": days}, headers=headers
                ).status_code
                == 422
            )
        assert api.post("/calendar/settings", json={"window_days": 7}, headers=headers).json() == {
            "window_days": 7
        }
        preview = api.post("/calendar", json={}, headers=headers).json()
        assert len(preview["changes"]) == 4 and not fake.writes
        assert api.post("/calendar", json={"apply": True}, headers=headers).status_code == 400
        result = api.post(
            "/calendar", json={"apply": True, "preview_id": preview["preview_id"]}, headers=headers
        )
        assert result.status_code == 200 and result.json()["applied"]
        assert not api.get("/status", headers=headers).json()["garmin_out_of_date"]
        with store.transaction() as session:
            session.get(StepRow, (store.plan().workouts[0].id, 0)).minutes *= 0.8
        assert api.get("/status", headers=headers).json()["garmin_out_of_date"]
        assert (
            Coach(store, client_factory=lambda _: fake)
            .calendar(CalendarRequest(), today=start)
            .changes[0]
            .action
            == "update"
        )


def test_detail_owned_renamed_workout_is_reused_when_summary_omits_tag(store):
    client = FakeGarmin()
    workout = store.plan().workouts[0]
    remote_id = client.create(workout_payload(workout))
    client.data[remote_id]["workoutName"] = "Renamed by runner"
    client.workouts = lambda: [{"workoutId": remote_id, "workoutName": "Renamed by runner"}]
    client.writes.clear()
    preview = reconcile_calendar(store, client, workout.day)
    assert preview["changes"][0]["action"] == "update"
    reconcile_calendar(store, client, workout.day, apply=True, preview_id=preview["preview_id"])
    assert client.writes.count("update") == 1
    assert client.data[remote_id]["description"] == tag(workout)


def test_manual_removal_invalidates_last_confirmed_calendar(store):
    from stride_coach.garmin import remove

    client = FakeGarmin()
    start = store.plan().setup.start
    preview = reconcile_calendar(store, client, start)
    reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert store.calendar_settings()["synced_fingerprint"]
    remove(store, client, False)
    assert store.calendar_settings()["synced_fingerprint"] is None


@pytest.mark.parametrize("failure", ["unschedule", "delete"])
def test_past_cleanup_retries_after_partial_removal(store, failure):
    client = FakeGarmin()
    workout = store.plan().workouts[0]
    push(store, [workout], client, False)
    today = workout.day + timedelta(days=1)
    store.save_sync([], str(workout.day), str(today), today=today)
    preview = reconcile_calendar(store, client, today)
    original = getattr(client, failure)

    def fail(remote_id):
        if failure == "unschedule":
            original(remote_id)
        raise GarminError("Removal interrupted")

    setattr(client, failure, fail)
    with pytest.raises(GarminError, match="Removal interrupted"):
        reconcile_calendar(store, client, today, apply=True, preview_id=preview["preview_id"])
    assert not client.events
    assert store.scheduled(workout.id)
    setattr(client, failure, original)
    preview = reconcile_calendar(store, client, today)
    assert any(c["action"] == "remove" and c["workout_id"] == workout.id for c in preview["changes"])
    reconcile_calendar(store, client, today, apply=True, preview_id=preview["preview_id"])
    assert store.scheduled(workout.id) is None
    assert not any(r["description"] == tag(workout) for r in client.data.values())
    assert client.writes.count("unschedule") == 1


@pytest.mark.parametrize("retry", ["calendar", "push"])
def test_lost_delete_response_allows_recreation_in_window(store, retry):
    client = FakeGarmin()
    plan = store.plan()
    workout = plan.workouts[8]
    start = plan.setup.start
    push(store, [workout], client, False)
    preview = reconcile_calendar(store, client, start)
    original = client.delete

    def lost_response(remote_id):
        original(remote_id)
        raise GarminError("Delete response lost")

    client.delete = lost_response
    with pytest.raises(GarminError, match="Delete response lost"):
        reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert not client.data and not client.events
    assert store.scheduled(workout.id)
    client.delete = original
    if retry == "calendar":
        preview = reconcile_calendar(store, client, workout.day)
        assert store.scheduled(workout.id) is None
        assert any(
            c["action"] == "create" and c["workout_id"] == workout.id for c in preview["changes"]
        )
        reconcile_calendar(
            store, client, workout.day, apply=True, preview_id=preview["preview_id"]
        )
    else:
        push(store, [workout], client, False)
    remote_id = store.scheduled(workout.id)["remote_id"]
    assert client.data[remote_id]["description"] == tag(workout)
    assert sum(str(e["workoutId"]) == remote_id for e in client.events) == 1


@pytest.mark.parametrize("retry", ["calendar", "push"])
@pytest.mark.parametrize("lost_schedule_response", [False, True])
def test_window_advance_recovers_after_unschedule_and_failed_delete(
    store, retry, lost_schedule_response
):
    client = FakeGarmin()
    plan = store.plan()
    workout = plan.workouts[8]
    start = workout.day - timedelta(days=store.calendar_settings()["window_days"])
    client.fail_schedule = lost_schedule_response
    if lost_schedule_response:
        with pytest.raises(GarminError, match="Response lost after schedule"):
            push(store, [workout], client, False)
    else:
        push(store, [workout], client, False)
    client.fail_schedule = False
    cached = store.scheduled(workout.id)
    remote_id = cached["remote_id"]
    preview = reconcile_calendar(store, client, start)
    assert any(
        c["action"] == "remove" and c["workout_id"] == workout.id for c in preview["changes"]
    )

    def fail_delete(remote_id):
        raise GarminError("Deletion failed")

    client.delete = fail_delete
    with pytest.raises(GarminError, match="Deletion failed"):
        reconcile_calendar(store, client, start, apply=True, preview_id=preview["preview_id"])
    assert remote_id in client.data
    assert not client.events
    assert store.scheduled(workout.id) == {**cached, "scheduled": False}
    assert not store.pending(f"schedule:{workout.id}")
    client.writes.clear()
    tomorrow = start + timedelta(days=1)
    if retry == "calendar":
        preview = reconcile_calendar(store, client, tomorrow)
        assert any(
            c["action"] == "schedule" and c["workout_id"] == workout.id
            for c in preview["changes"]
        )
        assert not client.writes
        reconcile_calendar(store, client, tomorrow, apply=True, preview_id=preview["preview_id"])
    else:
        push(store, [workout], client, False)
    assert store.scheduled(workout.id) == {**cached, "scheduled": True}
    assert sum(r["description"] == tag(workout) for r in client.data.values()) == 1
    assert sum(
        str(e["workoutId"]) == remote_id and e["date"] == workout.day.isoformat()
        for e in client.events
    ) == 1
