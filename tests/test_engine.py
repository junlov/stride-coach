from collections import defaultdict
from datetime import timedelta

import pytest
from pydantic import ValidationError

from stride_coach.engine import estimate_fitness, generate_plan, make_steps, training_days, vdot
from stride_coach.models import Activity, Athlete, Goal, Kind, RepeatGroup, Setup, executable_steps


def volumes(plan):
    result = defaultdict(float)
    for workout in plan.workouts:
        result[workout.week] += workout.minutes
    return list(result.values())


@pytest.mark.parametrize("goal", list(Goal))
@pytest.mark.parametrize("days", range(2, 7))
@pytest.mark.parametrize("long_day", range(7))
def test_planning_invariants(setup, runs, goal, days, long_day):
    if goal == Goal.RETURN and days > 3:
        return
    setup = Setup(
        **{**setup.model_dump(), "goal": goal, "days_per_week": days, "long_run_day": long_day}
    )
    plan = generate_plan(setup, runs)
    assert plan == generate_plan(setup, runs)
    assert len({w.day for w in plan.workouts}) == len(plan.workouts)
    assert all(setup.start <= w.day < setup.race_date for w in plan.workouts)
    assert {w.phase for w in plan.workouts} == {"base", "build", "peak", "taper"}
    volume = volumes(plan)
    assert all(nxt <= prev * 1.1 + 1e-8 for prev, nxt in zip(volume, volume[1:], strict=False))
    assert volume[3] < volume[2]
    assert volume[-1] < volume[-2]
    for week in range(1, max(w.week for w in plan.workouts)):
        sessions = [w for w in plan.workouts if w.week == week]
        assert len(sessions) == days
        assert any(w.day.weekday() == long_day for w in sessions)
    for workout in plan.workouts:
        assert workout.minutes > 0
        assert all(s.pace_min or s.hr_min for s in executable_steps(workout.steps))
    if goal == Goal.RETURN:
        assert all(w.kind == Kind.RUN_WALK for w in plan.workouts)
        assert all(len(w.steps) == 1 and w.steps[0].repetitions == 6 for w in plan.workouts)


def test_return_days_are_spaced():
    for day in range(7):
        days = training_days(3, day)
        assert all((d + 1) % 7 not in days for d in days)


def test_vdot_reference_and_fallback(setup, runs):
    assert vdot(5, 25) == pytest.approx(38.31, abs=0.05)
    with pytest.raises(ValueError):
        vdot(0, 20)
    fitness = estimate_fitness(runs, setup)
    assert fitness.vdot and fitness.easy_pace
    assert estimate_fitness([], setup).easy_pace is None
    regular = [a.model_copy(update={"best_effort": False}) for a in runs]
    assert estimate_fitness(regular, setup).easy_pace >= 420
    assert estimate_fitness([runs[0]], setup).weekly_minutes == 10


def test_old_future_and_walks_do_not_estimate_fitness(setup, runs):
    bad = [
        runs[0].model_copy(update={"sport": "walking"}),
        runs[0].model_copy(update={"day": setup.start + timedelta(days=1)}),
        runs[0].model_copy(update={"day": setup.start - timedelta(days=29)}),
    ]
    assert estimate_fitness(bad, setup).weekly_minutes == 0
    assert estimate_fitness(bad, setup).vdot is None


@pytest.mark.parametrize("kind", list(Kind))
def test_steps_total_and_targets(setup, runs, kind):
    estimated = estimate_fitness(runs, setup)
    for fitness in [estimated, estimate_fitness([], setup)]:
        steps = make_steps(kind, 40, fitness, setup, 5)
        assert sum(s.minutes for s in steps) == pytest.approx(40)
        for s in executable_steps(steps):
            if s.pace_min:
                assert 0 < s.pace_min < s.pace_max
            else:
                assert setup.athlete.resting_hr < s.hr_min < s.hr_max < setup.athlete.max_hr


@pytest.mark.parametrize(
    "updates",
    [
        {"days_per_week": 0},
        {"days_per_week": 7},
        {"long_run_day": 7},
        {"start": "2026-10-06"},
        {"race_date": "2026-10-10"},
        {"race_date": "2028-10-10"},
        {"goal": Goal.RETURN, "days_per_week": 5},
    ],
)
def test_setup_validation(setup, updates):
    with pytest.raises(ValidationError):
        Setup(**{**setup.model_dump(), **updates})


def test_athlete_and_nonfinite_inputs():
    with pytest.raises(ValidationError):
        Athlete(resting_hr=120, max_hr=110)
    with pytest.raises(ValidationError):
        Activity(id="bad", day="2026-10-03", distance_km=5, duration_min=float("nan"))


def test_thin_long_distance_warns(setup):
    plan = generate_plan(Setup(**{**setup.model_dump(), "goal": Goal.MARATHON}), [])
    assert any("readiness" in message for message in plan.warnings)
    assert all(w.kind not in (Kind.TEMPO, Kind.INTERVALS) for w in plan.workouts)


def test_return_running_minutes_progression(setup):
    setup = Setup(**{**setup.model_dump(), "goal": Goal.RETURN, "days_per_week": 3})
    plan = generate_plan(setup, [])
    running = defaultdict(float)
    for workout in plan.workouts:
        running[workout.week] += sum(
            block.repetitions * sum(s.minutes for s in block.steps if s.label == "Run gently")
            for block in workout.steps
            if isinstance(block, RepeatGroup)
        )
    values = list(running.values())
    assert all(b <= a * 1.1 for a, b in zip(values, values[1:], strict=False))
