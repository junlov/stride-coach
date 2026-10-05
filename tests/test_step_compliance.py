from datetime import timedelta

import pytest

from stride_coach.activity_models import RunLap
from stride_coach.compliance import score_steps
from stride_coach.models import Activity, Kind, Step
from stride_coach.service import Coach, SyncRequest


def workout(plan, *steps):
    result = plan.workouts[0].model_copy(deep=True)
    result.steps = list(steps)
    return result


def test_scores_duration_and_target_separately(plan):
    planned = workout(
        plan,
        Step(label="Warm up", minutes=10, hr_min=120, hr_max=140),
        Step(label="Tempo", minutes=20, pace_min=290, pace_max=310),
    )
    result = score_steps(
        planned,
        [
            RunLap(duration_s=600, distance_m=1500, average_hr=140),
            RunLap(duration_s=1200, distance_m=4000),
        ],
    )
    assert [step.score for step in result.steps] == [100, 100]
    result = score_steps(
        planned,
        [
            RunLap(duration_s=300, distance_m=1000, average_hr=150),
            RunLap(duration_s=1200, distance_m=4000),
        ],
    )
    assert all(step.score is None for step in result.steps)
    assert result.score is None
    assert result.missing_steps == 2


@pytest.mark.parametrize("seconds,expected", [(540, True), (660, True), (539, False), (661, False)])
def test_duration_tolerance_inclusive(plan, seconds, expected):
    planned = workout(plan, Step(label="Easy", minutes=10, hr_min=120, hr_max=140))
    result = score_steps(planned, [RunLap(duration_s=seconds, distance_m=1500, average_hr=120)])
    assert result.steps[0].duration_in_range is expected
    assert result.steps[0].score == (100 if expected else 50)


def test_missing_and_ambiguous_laps_are_not_failures(plan):
    step = Step(label="Interval", minutes=10, hr_min=140, hr_max=160)
    planned = workout(plan, step, step)
    for laps in [[], [RunLap(duration_s=1200, distance_m=3000, average_hr=150)]]:
        result = score_steps(planned, laps)
        assert result.score is None
        assert result.missing_steps == 2
        assert all(
            s.duration_in_range is None and s.score is None and s.missing for s in result.steps
        )
    result = score_steps(
        planned,
        [
            RunLap(duration_s=600, distance_m=1500),
            RunLap(duration_s=600, distance_m=1500, average_hr=150),
        ],
    )
    assert result.steps[0].duration_in_range is True
    assert result.steps[0].score is None
    assert result.score == 100
    assert result.scored_steps == result.missing_steps == 1


def test_single_step_auto_laps_weighted_by_time_and_zero_sensors(plan):
    planned = workout(plan, Step(label="Easy", minutes=10, hr_min=120, hr_max=140))
    result = score_steps(
        planned,
        [
            RunLap(duration_s=400, distance_m=1000, average_hr=130),
            RunLap(duration_s=200, distance_m=500, average_hr=150),
        ],
    )
    assert result.steps[0].target_score == pytest.approx(200 / 3)
    assert result.score == pytest.approx(250 / 3)
    assert (
        score_steps(planned, [RunLap(duration_s=600, distance_m=1500, average_hr=0)]).score is None
    )
    no_target = workout(plan, Step(label="No target", minutes=10))
    assert score_steps(no_target, [RunLap(duration_s=0, distance_m=0)]).score is None
    pace = workout(plan, Step(label="Easy", minutes=10, pace_min=300, pace_max=400))
    assert score_steps(pace, [RunLap(duration_s=600, distance_m=0)]).score is None


def test_scores_persist_refresh_and_clear_with_matches(store):
    coach = Coach(store)
    planned = next(w for w in store.plan().workouts if w.kind == Kind.LONG)
    step = planned.steps[0]
    run = Activity(
        id="compliance-run",
        day=planned.day,
        distance_km=3,
        duration_min=planned.minutes,
        laps=[
            RunLap(
                distance_m=3000,
                duration_s=planned.minutes * 60,
                average_pace_s_km=step.pace_min,
                average_hr=step.hr_min,
            )
        ],
    )
    request = SyncRequest(since=run.day, until=run.day, activities=[run])
    coach.sync(request, today=run.day + timedelta(days=1))
    score = coach.activity(run.id).step_compliance
    assert score.score == 100
    assert score == coach.compliance()[0].matches[0].step_compliance
    summary = run.model_copy(update={"laps": None})
    coach.sync(
        request.model_copy(update={"activities": [summary]}), today=run.day + timedelta(days=1)
    )
    assert coach.activity(run.id).step_compliance == score
    coach.sync(request.model_copy(update={"activities": []}), today=run.day + timedelta(days=1))
    assert coach.activity(run.id).step_compliance == score
    # An explicit sport update removes the workout match; omission preserves it.
    coach.sync(
        request.model_copy(
            update={"activities": [summary.model_copy(update={"sport": "walking"})]}
        ),
        today=run.day + timedelta(days=1),
    )
    assert store.step_compliance() == {}
