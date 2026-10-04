from copy import deepcopy
from types import SimpleNamespace

import pytest

from stride_coach.garmin import (
    GarminClient,
    GarminError,
    normalize_activity,
    pending,
    push,
    remove,
    workout_payload,
)


class FakeGarmin:
    def __init__(self):
        self.data, self.events, self.writes = {}, [], []
        self.fail_create = False
        self.fail_schedule = False
        self.hide_workouts = False

    def workouts(self):
        return [] if self.hide_workouts else list(self.data.values())

    def workout(self, remote_id):
        return deepcopy(self.data[remote_id])

    def calendar(self, day):
        return deepcopy(self.events)

    def create(self, payload):
        remote_id = str(len(self.data) + 1)
        self.data[remote_id] = {**deepcopy(payload), "workoutId": remote_id}
        self.writes.append("create")
        if self.fail_create:
            raise GarminError("Response lost after upload")
        return remote_id

    def update(self, remote_id, payload):
        self.writes.append("update")
        self.data[remote_id] = {**deepcopy(payload), "workoutId": remote_id}

    def schedule(self, remote_id, day):
        self.writes.append("schedule")
        self.events.append(
            {
                "id": len(self.events) + 1,
                "workoutId": remote_id,
                "date": day.isoformat(),
                "itemType": "workout",
            }
        )
        if self.fail_schedule:
            raise GarminError("Response lost after schedule")

    def unschedule(self, schedule_id):
        self.events = [e for e in self.events if str(e["id"]) != schedule_id]
        self.writes.append("unschedule")

    def delete(self, remote_id):
        self.writes.append("delete")
        del self.data[remote_id]


def test_dry_run_needs_no_client_and_writes_no_ledger(store):
    preview = push(store, store.plan().workouts[:1])
    assert preview[0]["action"] == "preview"
    assert store.scheduled_count() == 0
    assert remove(store)[0]["action"] == "preview removal"


def test_create_rerun_update_and_remove_only_owned(store):
    client = FakeGarmin()
    workouts = store.plan().workouts[:2]
    push(store, workouts, client, False)
    assert client.writes == ["create", "schedule", "create", "schedule"]
    push(store, workouts, client, False)
    assert client.writes == ["create", "schedule", "create", "schedule"]
    plan = store.plan()
    plan.workouts[0].steps[0].minutes *= 0.8
    from stride_coach.db_models import StepRow

    with store.transaction() as session:
        session.get(StepRow, (plan.workouts[0].id, 0)).minutes = plan.workouts[0].steps[0].minutes
    push(store, workouts, client, False)
    assert client.writes[-1] == "update"
    assert client.writes.count("schedule") == 2
    client.data["999"] = {"workoutId": "999", "workoutName": "My personal workout"}
    remove(store, client, False)
    assert set(client.data) == {"999"}
    assert not client.events
    assert store.scheduled_count() == 0


@pytest.mark.parametrize("failure", ["fail_create", "fail_schedule"])
def test_lost_response_reconciles_without_duplicate(store, failure):
    client = FakeGarmin()
    setattr(client, failure, True)
    workouts = store.plan().workouts[:1]
    with pytest.raises(GarminError, match="Response lost"):
        push(store, workouts, client, False)
    setattr(client, failure, False)
    push(store, workouts, client, False)
    assert client.writes.count("create") == 1
    assert client.writes.count("schedule") == 1
    assert len(client.data) == len(client.events) == 1


def test_uncertain_upload_does_not_retry_blindly(store):
    client = FakeGarmin()
    client.fail_create = True
    workouts = store.plan().workouts[:1]
    with pytest.raises(GarminError):
        push(store, workouts, client, False)
    client.hide_workouts = True
    with pytest.raises(GarminError, match="unresolved"):
        push(store, workouts, client, False)
    assert client.writes.count("create") == 1
    assert pending(store, f"create:{workouts[0].id}")


def test_uncertain_schedule_does_not_retry_blindly(store):
    client = FakeGarmin()
    client.fail_schedule = True
    workouts = store.plan().workouts[:1]
    with pytest.raises(GarminError):
        push(store, workouts, client, False)
    client.events.clear()
    with pytest.raises(GarminError, match="calendar write"):
        push(store, workouts, client, False)
    assert client.writes.count("schedule") == 1


def test_altered_tag_never_authorizes_update_or_removal(store):
    client = FakeGarmin()
    workouts = store.plan().workouts[:1]
    push(store, workouts, client, False)
    client.data["1"]["description"] = "Not owned"
    with pytest.raises(GarminError):
        push(store, workouts, client, False)
    remove(store, client, False)
    assert "1" in client.data
    assert "delete" not in client.writes


def test_recovery_without_local_ledger(store):
    client = FakeGarmin()
    workouts = store.plan().workouts[:1]
    push(store, workouts, client, False)
    store.forget_remote(workouts[0].id)
    push(store, workouts, client, False)
    assert client.writes.count("create") == client.writes.count("schedule") == 1


def test_workout_payload_units(plan):
    workout = plan.workouts[0]
    payload = workout_payload(workout)
    step = payload["workoutSegments"][0]["workoutSteps"][0]
    assert step["endConditionValue"] == pytest.approx(workout.steps[0].minutes * 60, abs=0.001)
    assert step["targetType"] == {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
    assert step["targetValueOne"] == workout.steps[0].hr_min
    assert step["targetValueOne"] < step["targetValueTwo"]
    workout.steps[0].hr_min = workout.steps[0].hr_max = None
    workout.steps[0].pace_min, workout.steps[0].pace_max = 270, 290
    step = workout_payload(workout)["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeId"] == 6
    assert step["targetValueOne"] == pytest.approx(1000 / 290)


def test_normalizes_fake_garmin_response():
    activity = normalize_activity(
        {
            "activityId": 123,
            "startTimeLocal": "2026-10-03 08:00:00",
            "distance": 5000,
            "duration": 1800,
            "averageHR": 145,
            "activityType": {"typeKey": "trail_running"},
        }
    )
    assert activity.distance_km == 5 and activity.duration_min == 30
    assert activity.sport == "running" and activity.kind is None


def test_missing_tokens_never_login(tmp_path, monkeypatch):
    import garminconnect

    monkeypatch.setattr(
        garminconnect.Garmin, "login", lambda *a, **k: pytest.fail("implicit login forbidden")
    )
    with pytest.raises(GarminError, match="Connect Garmin"):
        GarminClient(tmp_path / "missing")


def test_adapter_endpoints_and_response_parsing(monkeypatch):
    client = GarminClient.__new__(GarminClient)
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(json=lambda: {"workoutId": 17})

    def connectapi(path):
        calls.append(((path,), {}))
        return {"calendarItems": []}

    client.api = SimpleNamespace(
        garth=SimpleNamespace(
            oauth1_token=True,
            oauth2_token=SimpleNamespace(expired=False),
            request=request,
            post=request,
            delete=request,
        ),
        connectapi=connectapi,
        get_workouts=lambda **kwargs: [],
        get_workout_by_id=lambda remote_id: {"workoutId": remote_id},
        upload_workout=lambda payload: {"workoutId": 17},
        get_activities_by_date=lambda *args, **kwargs: [],
    )
    from datetime import date

    day = date(2026, 10, 5)
    assert client.activities(day, day) == []
    assert client.workouts() == []
    assert client.workout("17") == {"workoutId": "17"}
    assert client.calendar(day) == []
    assert calls[-1][0] == ("/calendar-service/year/2026/month/9",)
    assert client.create({}) == "17"
    client.update("17", {"description": "test"})
    assert calls[-1] == (
        ("PUT", "connectapi", "/workout-service/workout/17"),
        {"api": True, "json": {"description": "test", "workoutId": 17}},
    )
    client.schedule("17", day)
    assert calls[-1][1]["json"] == {"date": "2026-10-05"}
    client.unschedule("18")
    assert calls[-1][0][-1] == "/workout-service/schedule/18"
    client.delete("17")
    assert calls[-1][0][-1] == "/workout-service/workout/17"
    client.api.get_workouts = lambda **kwargs: {}
    with pytest.raises(GarminError, match="Unexpected"):
        client.workouts()
    client.api.connectapi = lambda *args: {}
    with pytest.raises(GarminError, match="Unexpected"):
        client.calendar(day)


@pytest.mark.parametrize("legacy", [False, True])
def test_duplicate_tags_stop_writes(store, legacy):
    client = FakeGarmin()
    workouts = store.plan().workouts[:1]
    payload = workout_payload(workouts[0])
    client.create(payload)
    if legacy:
        from stride_coach.garmin import tag

        payload["description"] = tag(workouts[0])
        payload["workoutName"] = f"SC {workouts[0].id} easy"
    client.create(payload)
    with pytest.raises(GarminError, match="Multiple"):
        push(store, workouts, client, False)
    assert client.writes == ["create", "create"]


def test_remove_cannot_clear_an_unresolved_upload(store):
    client = FakeGarmin()
    workout = store.plan().workouts[0]
    pending(store, f"create:{workout.id}", True)
    with pytest.raises(GarminError, match="unresolved"):
        remove(store, client, False)
    assert pending(store, f"create:{workout.id}")


@pytest.mark.parametrize("old_name", [True, False])
@pytest.mark.parametrize("description_style", ["exact", "embedded", "missing_summary"])
def test_legacy_and_new_workouts_update_in_place(store, old_name, description_style):
    from stride_coach.garmin import fingerprint, tag

    client = FakeGarmin()
    workout = store.plan().workouts[0]
    payload = workout_payload(workout)
    legacy = {**payload, "workoutName": f"SC {workout.id} easy" if old_name else "Renamed run"}
    if description_style == "exact":
        legacy["description"] = tag(workout)
    client.create(legacy)
    client.schedule("1", workout.day)
    store.save_remote(workout.id, "1", fingerprint(legacy), True)
    if description_style == "missing_summary":
        client.workouts = lambda: [{"workoutId": "1", "workoutName": legacy["workoutName"]}]
    result = push(store, [workout], client, False)
    assert result[0]["action"] == "updated"
    assert client.writes == ["create", "schedule", "update"]
    assert client.data["1"] == {**payload, "workoutId": "1"}
    push(store, [workout], client, False)
    assert client.writes == ["create", "schedule", "update"]
    remove(store, client, False)
    assert not client.data


@pytest.mark.parametrize("description", [None, "", "prefix {tag}", "{tag}-other", "{tag} suffix"])
@pytest.mark.parametrize("old_name", [True, False])
def test_name_never_authorizes_ownership(plan, description, old_name):
    from stride_coach.garmin import owned_remote, tag

    workout = plan.workouts[0]
    client = FakeGarmin()
    payload = workout_payload(workout)
    payload["description"] = description.format(tag=tag(workout)) if description else description
    if old_name:
        payload["workoutName"] = f"SC {workout.id} easy"
    client.create(payload)
    assert owned_remote(client, client.workouts(), workout) is None


def test_summary_tag_must_be_verified_in_detail(plan):
    from stride_coach.garmin import owned_remote

    workout = plan.workouts[0]
    client = FakeGarmin()
    client.create(workout_payload(workout))
    inventory = deepcopy(client.workouts())
    client.data["1"]["description"] = "No longer tagged"
    assert owned_remote(client, inventory, workout) is None


@pytest.mark.parametrize("operation", ["push", "remove"])
def test_missing_summary_descriptions_are_loaded_once(store, operation):
    from collections import Counter

    client = FakeGarmin()
    workouts = store.plan().workouts[:4]
    push(store, workouts, client, False)
    client.data["999"] = {"workoutId": "999", "workoutName": "Personal run"}
    client.workouts = lambda: [{"workoutId": remote_id} for remote_id in client.data]
    reads = Counter()
    detail = client.workout

    def counted_detail(remote_id):
        reads[remote_id] += 1
        return detail(remote_id)

    client.workout = counted_detail
    client.writes.clear()
    if operation == "push":
        result = push(store, workouts, client, False)
        assert all(item["action"] == "skipped" for item in result)
        assert client.writes == []
    else:
        result = remove(store, client, False)
        assert len(result) == len(workouts)
        assert set(client.data) == {"999"}
    assert reads == Counter({"1": 2, "2": 2, "3": 2, "4": 2, "999": 1})


@pytest.mark.parametrize("operation", ["push", "remove"])
def test_hydrated_inventory_does_not_authorize_writes(store, operation):
    client = FakeGarmin()
    workouts = store.plan().workouts[:1]
    push(store, workouts, client, False)
    client.workouts = lambda: [{"workoutId": "1"}]
    reads = 0
    detail = client.workout

    def changed_detail(remote_id):
        nonlocal reads
        reads += 1
        if reads == 2:
            client.data[remote_id]["description"] = "No longer tagged"
        return detail(remote_id)

    client.workout = changed_detail
    client.writes.clear()
    store.save_remote(workouts[0].id, "1", "outdated", True)
    if operation == "push":
        with pytest.raises(GarminError, match="no longer discoverable"):
            push(store, workouts, client, False)
    else:
        assert remove(store, client, False) == []
    assert reads == 2
    assert client.writes == []
    assert "1" in client.data
