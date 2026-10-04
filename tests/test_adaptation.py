from datetime import timedelta

import pytest
from sqlalchemy import event

from stride_coach.adaptation import adapt, match_activities, propose, trimp, week_metrics
from stride_coach.engine import generate_plan
from stride_coach.models import Activity, Athlete, Goal, Kind, Setup
from stride_coach.storage import Store


def completed(plan, week, hr=140, factor=1):
    return [
        Activity(
            id=w.id,
            day=w.day,
            distance_km=w.minutes / 8,
            duration_min=w.minutes * factor,
            average_hr=hr,
            kind=w.kind,
        )
        for w in plan.workouts
        if w.week == week
    ]


def test_banister_uses_hr_reserve_and_average():
    activity = Activity(id="1", day="2026-10-03", distance_km=5, duration_min=30, average_hr=150)
    assert trimp(activity, Athlete()) == pytest.approx(50.27, abs=0.1)
    assert trimp(activity, Athlete(resting_hr=90)) < trimp(activity, Athlete(resting_hr=60))
    assert trimp(activity.model_copy(update={"average_hr": None}), Athlete()) is None
    assert trimp(activity.model_copy(update={"average_hr": 50}), Athlete()) == 0


def test_matching_is_one_to_one_with_type_priority(plan):
    runs = completed(plan, 1)
    extra = runs[0].model_copy(update={"id": "extra", "kind": None})
    walk = runs[1].model_copy(update={"id": "walk", "sport": "walking"})
    matches = match_activities(plan, runs + [extra, walk])
    assert len(matches) == len(runs)
    assert all(m["method"] == "date+type" for m in matches)
    assert len({m["activity_id"] for m in matches}) == len(matches)
    assert not match_activities(plan, [walk])
    wrong = runs[0].model_copy(update={"kind": Kind.INTERVALS})
    assert not match_activities(plan, [wrong])
    assert match_activities(plan, [extra])[0]["method"].endswith("(inferred)")


def test_missing_sessions_reduce_and_record_reasons(plan):
    change = propose(plan, [], 2)
    assert change.factor == 0.75
    assert "half" in change.reasons[0]
    assert not change.applied
    assert propose(plan, completed(plan, 1)[:2], 2).factor == 0.85


def test_load_rise_reduces_even_with_compliance(plan):
    runs = completed(plan, 1, hr=120) + completed(plan, 2, hr=170)
    change = propose(plan, runs, 3)
    assert change.factor <= 0.85
    assert any("TRIMP" in r for r in change.reasons)


def test_missing_hr_is_unknown_not_zero(plan):
    runs = completed(plan, 1, hr=None)
    metrics = week_metrics(plan, runs, 1)
    assert metrics["missing_hr"] == metrics["matched_sessions"]
    assert propose(plan, runs, 2).factor < 1


def test_harder_and_easier_targets_hold_or_reduce(plan):
    runs = completed(plan, 1)
    for a in runs:
        a.distance_km = a.duration_min * 60 / 200
    change = propose(plan, runs, 2)
    assert change.factor <= 0.9
    for a in runs:
        a.distance_km = a.duration_min * 60 / 900
    change = propose(plan, runs, 2)
    assert change.after_minutes <= week_metrics(plan, runs, 1)["planned_minutes"] + 1e-7


def test_apply_is_atomic_repeatable_and_scales_future(store):
    plan = store.plan()
    today = plan.setup.start + timedelta(weeks=1)
    store.save_sync([], (today - timedelta(days=14)).isoformat(), today.isoformat(), today=today)
    preview = adapt(store, 2, today)
    assert not preview.applied
    assert store.plan() == plan
    applied = adapt(
        store,
        2,
        today,
        apply=True,
        proposal_fingerprint=preview.inputs["proposal_fingerprint"],
    )
    assert applied.applied
    assert (
        adapt(
            store,
            2,
            today,
            apply=True,
            proposal_fingerprint=preview.inputs["proposal_fingerprint"],
        )
        == applied
    )
    updated = store.plan()
    for old, new in zip(plan.workouts, updated.workouts, strict=True):
        assert new.minutes == pytest.approx(old.minutes * (0.75 if old.week >= 2 else 1))


def test_adapt_rejects_open_week_and_stale_sync(store):
    with pytest.raises(ValueError, match="Monday"):
        adapt(store, 2, store.plan().setup.start)
    with pytest.raises(ValueError, match="Sync"):
        adapt(store, 2, store.plan().setup.start + timedelta(weeks=1))
    with pytest.raises(ValueError):
        propose(store.plan(), [], 1)


def test_return_plan_adaptation_batches_database_calls(database, setup):
    plan = generate_plan(
        Setup(
            goal=Goal.RETURN,
            start=setup.start,
            race_date=setup.start + timedelta(weeks=12),
            days_per_week=3,
            long_run_day=6,
        ),
        [],
    )
    assert sum(len(workout.steps) for workout in plan.workouts) == 432
    calls = []

    def record_call(connection, cursor, statement, parameters, context, executemany):
        calls.append((context.isupdate, executemany))

    store = Store(database)
    try:
        store.initialize(plan)
        monday = plan.setup.start + timedelta(weeks=1)
        store.save_sync([], str(monday - timedelta(days=14)), str(monday), today=monday)
        preview = adapt(store, 2, monday)
        event.listen(store.engine, "before_cursor_execute", record_call)
        try:
            applied = adapt(
                store,
                2,
                monday,
                apply=True,
                proposal_fingerprint=preview.inputs["proposal_fingerprint"],
            )
        finally:
            event.remove(store.engine, "before_cursor_execute", record_call)
        assert len(calls) <= 25
        assert [batch for update, batch in calls if update] == [True]
        assert applied.applied
        assert store.adjustment(2) == applied
        updated = store.plan()
        for old, new in zip(plan.workouts, updated.workouts, strict=True):
            factor = 0.75 if old.week >= 2 else 1
            assert new.id == old.id
            for old_step, new_step in zip(old.steps, new.steps, strict=True):
                assert new_step.minutes == pytest.approx(old_step.minutes * factor)
                assert new_step.model_dump(exclude={"minutes"}) == old_step.model_dump(
                    exclude={"minutes"}
                )
    finally:
        store.close()


def test_apply_requires_preview_and_rejects_changed_plan(store):
    plan = store.plan()
    monday = plan.setup.start + timedelta(weeks=1)
    store.save_sync([], str(monday - timedelta(days=14)), str(monday), today=monday)
    with pytest.raises(ValueError, match="preview is missing or stale"):
        adapt(store, 2, monday, apply=True)
    preview = propose(plan, [], 2)
    changed = plan.model_copy(deep=True)
    changed.workouts[-1].steps[0].minutes += 1
    assert (
        propose(changed, [], 2).inputs["proposal_fingerprint"]
        != preview.inputs["proposal_fingerprint"]
    )
    assert store.plan() == plan
    assert store.adjustment(2) is None
