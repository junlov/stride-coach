"""Structured workouts cross storage, Garmin previews and the plan API."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_garmin import FakeGarmin

from stride_coach.db_models import GarminZoneRow
from stride_coach.engine import estimate_fitness, generate_plan, make_steps
from stride_coach.garmin import GarminClient, normalize_heart_rate_zones, push, workout_payload
from stride_coach.models import (
    GarminHeartRateZone,
    Kind,
    RepeatGroup,
    Step,
    Workout,
    executable_steps,
)


def sample_workout(kind, setup, runs):
    return Workout(
        id=f"synthetic-{kind.value}",
        day=setup.start,
        week=5,
        phase="build",
        kind=kind,
        steps=make_steps(kind, 40, estimate_fitness(runs, setup), setup, 5),
    )


@pytest.mark.parametrize("kind", list(Kind))
def test_payload_snapshot(kind, setup, runs):
    payload = workout_payload(sample_workout(kind, setup, runs))
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "workouts" / f"{kind.value}.json").read_text()
    )
    assert payload == expected


def test_six_distance_reps_with_lap_and_cadence(setup):
    workout = Workout(
        id="distance",
        day=setup.start,
        week=1,
        phase="build",
        kind=Kind.INTERVALS,
        steps=[
            Step(label="Warm up", minutes=10, end_condition="lap", hr_zone=2),
            RepeatGroup(
                label="Intervals",
                repetitions=6,
                skip_last_rest=True,
                steps=[
                    Step(
                        label="Controlled interval",
                        minutes=3.6,
                        end_condition="distance",
                        distance_m=800,
                        pace_min=270,
                        pace_max=290,
                        cadence_min=165,
                        cadence_max=185,
                    ),
                    Step(
                        label="Easy recovery",
                        minutes=3,
                        end_condition="distance",
                        distance_m=400,
                        hr_zone=1,
                    ),
                ],
            ),
            Step(label="Cool down", minutes=10, end_condition="lap", hr_zone=2),
        ],
    )
    payload = workout_payload(workout)
    warm, group, cool = payload["workoutSegments"][0]["workoutSteps"]
    assert [warm["stepOrder"], group["stepOrder"], cool["stepOrder"]] == [1, 2, 5]
    assert group["type"] == "RepeatGroupDTO"
    assert group["numberOfIterations"] == 6 and group["skipLastRestStep"]
    assert [child["stepOrder"] for child in group["workoutSteps"]] == [3, 4]
    assert group["workoutSteps"][0]["endConditionValue"] == 800
    assert group["workoutSteps"][0]["endCondition"]["conditionTypeId"] == 3
    assert group["workoutSteps"][0]["secondaryTargetValueOne"] == 165
    assert group["workoutSteps"][0]["secondaryTargetType"]["workoutTargetTypeId"] == 3
    assert warm["endCondition"] == {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
    assert "endConditionValue" not in warm
    assert warm["zoneNumber"] == 2 and "targetValueOne" not in warm
    assert workout.minutes == pytest.approx(56.6)
    assert payload["estimatedDurationInSecs"] == 3396


def test_repeat_storage_and_adjustment_scaling(store):
    from stride_coach.models import Adjustment

    plan = store.plan()
    assert any(isinstance(s, RepeatGroup) for w in plan.workouts for s in w.steps)
    before = plan.model_copy(deep=True)
    for w in plan.workouts:
        for s in executable_steps(w.steps):
            s.minutes *= 0.75
            if s.distance_m:
                s.distance_m *= 0.75
    store.apply(
        plan,
        Adjustment(
            week=2, factor=0.75, reasons=["synthetic"], before_minutes=100, after_minutes=75
        ),
    )
    loaded = store.plan()
    assert loaded == plan
    for old, new in zip(before.workouts, loaded.workouts, strict=True):
        assert new.minutes == pytest.approx(old.minutes * 0.75)


def test_zone_fallback_freshness_and_push_update(store):
    client = FakeGarmin()
    workouts = store.plan().workouts[:1]
    push(store, workouts, client, False)
    store.save_garmin_zones([GarminHeartRateZone(zone=2, lower_bpm=125, upper_bpm=144)])
    workout = store.plan().workouts[0]
    assert workout.steps[0].hr_zone == 2
    push(store, workouts, client, False)
    assert client.writes == ["create", "schedule", "update"]
    assert client.data["1"]["workoutSegments"][0]["workoutSteps"][0]["zoneNumber"] == 2
    push(store, workouts, client, False)
    assert client.writes.count("update") == 1
    with store.transaction() as session:
        session.get(GarminZoneRow, 2).fetched_at = datetime.now(UTC) - timedelta(days=8)
    fallback = workout_payload(store.plan().workouts[0])["workoutSegments"][0]["workoutSteps"][0]
    assert "zoneNumber" not in fallback
    assert fallback["targetValueOne"] == 138


def test_zone_source_and_validation():
    default = dict(
        sport="DEFAULT",
        zone1Floor=100,
        zone2Floor=120,
        zone3Floor=140,
        zone4Floor=160,
        zone5Floor=180,
        maxHeartRateUsed=200,
    )
    running = {**default, "sport": "RUNNING", "zone2Floor": 125}
    assert normalize_heart_rate_zones([default, running])[1].lower_bpm == 125
    assert normalize_heart_rate_zones([default])[1].lower_bpm == 120
    for payload in [
        None,
        {},
        [],
        [{**default, "sport": "CYCLING"}],
        [default, {**running, "zone2Floor": None}],
        [{**running, "zone2Floor": 99}],
        [{**running, "zone1Floor": "100"}],
    ]:
        assert normalize_heart_rate_zones(payload) == []


def test_garmin_zone_read_uses_existing_guard(monkeypatch):
    client = object.__new__(GarminClient)
    client.api = type("Api", (), {"connectapi": object()})()
    calls = []
    monkeypatch.setattr(client, "_call", lambda *args: calls.append(args) or [])
    assert client.heart_rate_zones() == []
    assert calls == [(client.api.connectapi, "/biometric-service/heartRateZones/")]


@pytest.mark.parametrize(
    "values",
    [
        dict(end_condition="distance"),
        dict(distance_m=400),
        dict(pace_min=270),
        dict(pace_min=300, pace_max=280),
        dict(pace_min=270, pace_max=300, hr_zone=2),
        dict(cadence_min=170),
    ],
)
def test_invalid_steps(values):
    with pytest.raises(ValidationError):
        Step(label="invalid", minutes=1, **values)


def test_minimum_pace_spread_and_strides(setup, runs):
    fitness = estimate_fitness(runs, setup)
    fitness.easy_pace = 180
    for kind in Kind:
        steps = make_steps(kind, 40, fitness, setup, 6)
        assert sum(s.minutes for s in steps) == pytest.approx(40)
        for s in executable_steps(steps):
            if s.pace_min:
                assert s.pace_max - s.pace_min >= 20
    strides = make_steps(Kind.EASY, 40, fitness, setup, 6)[1]
    assert strides.label == "Strides" and strides.repetitions == 4
    assert len(make_steps(Kind.EASY, 10, fitness, setup, 6)) == 1


def test_cadence_uses_runner_history_only(setup, runs):
    from stride_coach.activity_models import RunMetrics

    for run in runs:
        run.metrics = RunMetrics(average_cadence_spm=172)
    plan = generate_plan(setup, runs)
    strides = [
        s for w in plan.workouts for s in executable_steps(w.steps) if s.label == "Relaxed stride"
    ]
    assert strides and all((s.cadence_min, s.cadence_max) == (162, 182) for s in strides)
    for run in runs:
        run.metrics = None
    assert all(
        s.cadence_min is None
        for w in generate_plan(setup, runs).workouts
        for s in executable_steps(w.steps)
    )


def test_sync_refreshes_current_zones_and_falls_back_on_error(store, tmp_path):
    from stride_coach.garmin import GarminError
    from stride_coach.service import Coach, SyncRequest

    class SyntheticGarmin:
        fail = False

        def activities(self, since, until):
            return []

        def heart_rate_zones(self):
            if self.fail:
                raise GarminError("Synthetic unavailable zones")
            return [GarminHeartRateZone(zone=2, lower_bpm=120, upper_bpm=140)]

    client = SyntheticGarmin()
    coach = Coach(store, tmp_path, client_factory=lambda _: client)
    day = store.plan().setup.start
    coach.sync(SyncRequest(since=day, until=day), today=day)
    assert coach.plan().workouts[0].steps[0].hr_zone == 2
    client.fail = True
    coach.sync(SyncRequest(since=day, until=day), today=day)
    assert coach.plan().workouts[0].steps[0].hr_zone is None
    assert store.sync_status().latest.result == "success"


def test_api_step_text_uses_garmin_formatter(store):
    from stride_coach.service import Coach
    from stride_coach.workout_text import step_summary

    plan = Coach(store).plan()
    for workout in plan.workouts:
        payload = workout_payload(workout)
        assert workout.name == payload["workoutName"]
        assert workout.step_descriptions == [step_summary(s) for s in workout.steps]
        for step, text in zip(workout.steps, workout.step_descriptions, strict=True):
            if isinstance(step, RepeatGroup):
                assert f"{step.repetitions} x" in text
            else:
                index = workout.steps.index(step)
                assert text == payload["workoutSegments"][0]["workoutSteps"][index]["description"]


def test_shared_names_distance_and_bounded_cues(setup):
    from stride_coach.workout_text import step_description, workout_name

    effort = Step(
        label="Controlled interval",
        minutes=3.6,
        end_condition="distance",
        distance_m=800,
        pace_min=270,
        pace_max=290,
    )
    workout = Workout(
        id="distance",
        day=setup.start,
        week=1,
        phase="build",
        kind=Kind.INTERVALS,
        steps=[
            RepeatGroup(
                label="Intervals",
                repetitions=6,
                steps=[effort, Step(label="Easy recovery", minutes=3, hr_zone=1)],
            )
        ],
    )
    assert workout_name(workout) == "Reps 6x800 m"
    assert step_description(effort) == "800 m at 4:30 to 4:50 /km. Finish smooth."
    for step in executable_steps(workout.steps):
        assert len(step_description(step).encode("ascii")) <= 200


def test_downgrade_refuses_to_lose_repeat_structure(store):
    from alembic import command

    from stride_coach.database import check_schema, migration_config

    before = store.plan()
    with pytest.raises(RuntimeError, match="pre-upgrade backup"), store.connection.begin():
        command.downgrade(migration_config(store.connection), "0005")
    with store.connection.begin():
        check_schema(store.connection)
    assert store.plan() == before
