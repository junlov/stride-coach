from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select

from stride_coach.activity_models import RunLap, RunMetrics, RunStreams
from stride_coach.db_models import ActivityStreamRow, RepeatRow
from stride_coach.engine import make_steps
from stride_coach.models import Activity, Kind, RepeatGroup, executable_steps
from stride_coach.recovery_models import DailyAdaptRequest, DailyReadiness
from stride_coach.service import Coach, GoalRequest, SyncRequest
from stride_coach.storage import Store


@pytest.mark.parametrize("skip_last_rest", [False, True])
def test_import_scores_each_run_walk_lap(database, plan, skip_last_rest):
    workout = plan.workouts[0]
    workout.kind = Kind.RUN_WALK
    workout.steps = make_steps(Kind.RUN_WALK, 30, plan.fitness, plan.setup, 1)
    group = workout.steps[0]
    group.skip_last_rest = skip_last_rest
    children = group.steps * group.repetitions
    if skip_last_rest:
        children = children[:-1]
    activity = Activity(
        id="repeat-laps",
        day=workout.day,
        distance_km=3,
        duration_min=workout.minutes,
        laps=[
            RunLap(
                duration_s=step.minutes * 60,
                distance_m=200,
                average_hr=(step.hr_min + step.hr_max) / 2,
            )
            for step in children
        ],
    )
    with closing(Store(database)) as store:
        store.initialize(plan)
        Coach(store).sync(
            SyncRequest(since=activity.day, until=activity.day, activities=[activity]),
            today=activity.day,
        )
        score = store.step_compliance()[activity.id]
        assert score.scored_steps == len(children)
        assert score.missing_steps == 0
        assert score.score == 100
        assert [step.label for step in score.steps] == [step.label for step in children]
        assert len(Coach(store).activity(activity.id).laps) == len(children)


def test_daily_replacement_removes_old_repeats(database, plan):
    workout = plan.workouts[0]
    workout.kind = Kind.INTERVALS
    workout.steps = make_steps(Kind.INTERVALS, 40, plan.fitness, plan.setup, 5)
    old_group = next(step for step in workout.steps if isinstance(step, RepeatGroup))
    workout.steps = [old_group, *workout.steps]
    today = workout.day - timedelta(days=1)
    with closing(Store(database)) as store:
        store.initialize(plan)
        store.save_readiness(
            DailyReadiness(day=today, fetched_at=datetime.now(UTC), training_readiness=10)
        )
        coach = Coach(store)
        preview = coach.daily_adjustment(today=today)
        assert any(isinstance(step, RepeatGroup) for step in preview.after.steps)
        applied = coach.daily_adjustment(
            DailyAdaptRequest(apply=True, proposal_fingerprint=preview.proposal_fingerprint),
            today=today,
        )
        loaded = store.plan().workouts[0]
        assert loaded.steps == preview.after.steps
        assert loaded.kind == Kind.EASY
        assert loaded.minutes == pytest.approx(preview.before.minutes)
        assert applied.applied
        assert store.daily_adjustment(loaded.id).after.steps == loaded.steps
        with store.transaction() as session:
            rows = list(session.scalars(select(RepeatRow).where(RepeatRow.workout_id == loaded.id)))
            assert [(row.label, row.repetitions) for row in rows] == [("Strides", 4)]
        assert coach.daily_adjustment(
            DailyAdaptRequest(apply=True, proposal_fingerprint=preview.proposal_fingerprint),
            today=today,
        ).applied


def test_initialize_uses_persisted_cadence_without_streams(database, setup, runs):
    for run in runs[:3]:
        run.metrics = RunMetrics(average_cadence_spm=172)
        run.streams = RunStreams(time_s=[0], cadence_spm=[172])
    with closing(Store(database)) as store:
        Coach(store).sync(
            SyncRequest(since=min(run.day for run in runs), until=setup.start, activities=runs),
            today=setup.start,
        )
    with closing(Store(database)) as store:

        def reject_stream_read(connection, clause, *args):
            if getattr(clause, "is_select", False):
                assert ActivityStreamRow.__table__ not in clause.get_final_froms()

        event.listen(store.connection, "before_execute", reject_stream_read)
        Coach(store).initialize(GoalRequest(setup=setup))
        steps = [s for w in store.plan().workouts for s in executable_steps(w.steps)]
        strides = [s for s in steps if s.label == "Relaxed stride"]
        assert strides
        assert all((s.cadence_min, s.cadence_max) == (162, 182) for s in strides)
        assert all(activity.metrics is None for activity in store.activities())


@pytest.mark.parametrize("cache", ["fresh", "empty", "expired"])
def test_daily_targets_agree_through_confirmation_and_push(database, plan, cache):
    from stride_coach.db_models import GarminZoneRow
    from stride_coach.garmin import workout_payload
    from stride_coach.models import GarminHeartRateZone
    from stride_coach.service import PushRequest

    workout = plan.workouts[0]
    workout.kind = Kind.INTERVALS
    workout.steps = make_steps(Kind.INTERVALS, 40, plan.fitness, plan.setup, 5)
    today = workout.day - timedelta(days=1)
    with closing(Store(database)) as store:
        store.initialize(plan)
        if cache != "empty":
            store.save_garmin_zones(
                [
                    GarminHeartRateZone(zone=1, lower_bpm=100, upper_bpm=120),
                    GarminHeartRateZone(zone=2, lower_bpm=120, upper_bpm=140),
                ]
            )
        if cache == "expired":
            with store.transaction() as session:
                for row in session.scalars(select(GarminZoneRow)):
                    row.fetched_at = datetime.now(UTC) - timedelta(days=8)
        store.save_readiness(
            DailyReadiness(day=today, fetched_at=datetime.now(UTC), training_readiness=10)
        )
        coach = Coach(store, client_factory=lambda _: pytest.fail("No Garmin calls expected"))
        preview = coach.daily_adjustment(today=today)
        leaves = list(executable_steps(preview.after.steps))
        easy, recovery = leaves[0], leaves[-1]
        assert (easy.hr_zone, easy.hr_min, easy.hr_max) == (
            (2, 120, 140) if cache == "fresh" else (None, 138, 154)
        )
        assert (recovery.hr_zone, recovery.hr_min, recovery.hr_max) == (
            (1, 100, 120) if cache == "fresh" else (None, 125, 144)
        )
        applied = coach.daily_adjustment(
            DailyAdaptRequest(apply=True, proposal_fingerprint=preview.proposal_fingerprint),
            today=today,
        )
        saved = coach.plan().workouts[0]
        assert preview.after == applied.after == saved
        assert preview.after.step_descriptions == applied.after.step_descriptions
        assert coach.push(PushRequest(workout=saved.id), today=today)[0].payload == workout_payload(
            preview.after
        )
        store.save_garmin_zones([])
        fallback = coach.plan().workouts[0]
        for step in executable_steps(fallback.steps):
            if step.preferred_hr_zone is not None:
                assert step.hr_zone is None
        assert (fallback.steps[0].hr_min, fallback.steps[0].hr_max) == (138, 154)
        target = coach.push(PushRequest(workout=saved.id), today=today)[0].payload[
            "workoutSegments"
        ][0]["workoutSteps"][0]
        assert "zoneNumber" not in target
        assert (target["targetValueOne"], target["targetValueTwo"]) == (138, 154)


@pytest.mark.parametrize("clear_with_error", [False, True])
def test_sync_refreshes_scores_after_zone_changes_and_fallback(database, plan, clear_with_error):
    from stride_coach.garmin import GarminError
    from stride_coach.models import GarminHeartRateZone

    workout = plan.workouts[0]
    workout.kind = Kind.LONG
    workout.steps = make_steps(Kind.LONG, 40, plan.fitness, plan.setup, 1)
    activity = Activity(
        id="zone-score",
        day=workout.day,
        distance_km=6,
        duration_min=40,
        laps=[RunLap(duration_s=2400, distance_m=6000, average_hr=130)],
    )

    class SyntheticGarmin:
        zones = [GarminHeartRateZone(zone=2, lower_bpm=120, upper_bpm=140)]
        fail = False

        def activities(self, since, until):
            return [activity]

        def heart_rate_zones(self):
            if self.fail:
                raise GarminError("Synthetic zone failure")
            return self.zones

    client = SyntheticGarmin()
    with closing(Store(database)) as store:
        store.initialize(plan)
        coach = Coach(store, client_factory=lambda _: client)
        request = SyncRequest(since=workout.day, until=workout.day)
        coach.sync(request, today=workout.day)
        assert store.step_compliance()[activity.id].steps[0].target_score == 100
        client.zones = [GarminHeartRateZone(zone=2, lower_bpm=140, upper_bpm=160)]
        coach.sync(request, today=workout.day)
        assert store.plan().workouts[0].steps[0].hr_min == 140
        assert store.step_compliance()[activity.id].steps[0].target_score == 0
        store.save_garmin_zones([GarminHeartRateZone(zone=2, lower_bpm=120, upper_bpm=140)])
        assert store.step_compliance()[activity.id].steps[0].target_score == 100
        client.zones = []
        client.fail = clear_with_error
        coach.sync(request, today=workout.day)
        step = store.plan().workouts[0].steps[0]
        assert (step.hr_zone, step.hr_min, step.hr_max) == (None, 138, 154)
        assert store.step_compliance()[activity.id].steps[0].target_score == 0
