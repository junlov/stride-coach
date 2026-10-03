import json
import sqlite3
from datetime import timedelta

import pytest

from stride_coach.models import Activity
from stride_coach.service import AdaptRequest, Coach, SyncRequest


def test_sync_reconciles_range_and_computes_matches(store):
    plan = store.plan()
    day = plan.workouts[0].day
    run = Activity(id="kept", day=day, distance_km=5, duration_min=30, average_hr=140)
    duplicate = run.model_copy(update={"id": "deleted"})
    reclassified = run.model_copy(update={"id": "changed-sport"})
    before = run.model_copy(update={"id": "before", "day": day - timedelta(days=1)})
    after = run.model_copy(update={"id": "after", "day": day + timedelta(days=1)})
    coach = Coach(store)
    coach.sync(
        SyncRequest(
            since=before.day,
            until=after.day,
            activities=[before, run, duplicate, reclassified, after],
        ),
        today=after.day + timedelta(days=1),
    )

    class Garmin:
        def activities(self, since, until):
            assert (since, until) == (day, day)
            return [run.model_copy(update={"duration_min": 35})]

    coach = Coach(store, client_factory=lambda _: Garmin())
    coach.sync(SyncRequest(since=day, until=day), today=after.day)
    assert {a.id for a in store.activities()} == {"before", "kept", "after"}
    assert next(a for a in store.activities() if a.id == "kept").duration_min == 35
    metrics = coach.week(1).metrics
    assert metrics.completed_minutes == sum(
        a.duration_min for a in store.activities() if a.day >= plan.setup.start
    )
    assert any(m.activity_id == "kept" for m in metrics.matches)
    coach.sync(SyncRequest(since=day, until=day, activities=[]), today=after.day)
    assert {a.id for a in store.activities()} == {"before", "after"}
    assert all(m.activity_id != "kept" for m in coach.week(1).metrics.matches)


def test_sync_rolls_back_reconciliation_and_coverage(store):
    today = store.plan().setup.start
    day = today - timedelta(days=1)
    run = Activity(id="old", day=day, distance_km=5, duration_min=30)
    store.save_sync([run], str(day), str(day), today=today)
    window = store.sync_window()
    complete = store.sync_window(complete=True)
    store.db.execute("""
        CREATE TEMP TRIGGER reject_coverage BEFORE INSERT ON metadata
        WHEN NEW.key = 'sync_complete'
        BEGIN SELECT RAISE(ABORT, 'coverage failure'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match="coverage failure"):
        store.save_sync([], str(day - timedelta(days=1)), str(today), today=today)
    assert store.activities() == [run]
    assert store.sync_window() == window
    assert store.sync_window(complete=True) == complete


def test_sunday_fetch_requires_resync_after_week_closes(store):
    monday = store.plan().setup.start + timedelta(weeks=1)
    sunday = monday - timedelta(days=1)
    since = monday - timedelta(days=14)
    run = Activity(id="morning", day=sunday, distance_km=5, duration_min=30)
    coach = Coach(store)
    request = SyncRequest(since=since, until=sunday, activities=[run])
    coach.sync(request, today=sunday)
    assert store.activities() == [run]
    assert coach.status().sync.until == sunday
    assert store.sync_window(complete=True)["until"] == str(sunday - timedelta(days=1))
    with pytest.raises(ValueError, match="Sync"):
        coach.adapt(AdaptRequest(week=2), today=monday)
    late = run.model_copy(update={"id": "afternoon"})
    request.activities.append(late)
    coach.sync(request, today=monday)
    assert store.sync_window(complete=True)["until"] == str(sunday)
    assert coach.week(1).metrics.completed_minutes == 60
    assert not coach.adapt(AdaptRequest(week=2), today=monday).applied


def test_today_only_sync_has_no_complete_day_coverage(store):
    today = store.plan().setup.start
    Coach(store).sync(SyncRequest(since=today, activities=[]), today=today)
    assert store.sync_window() == {"since": str(today), "until": str(today)}
    assert store.sync_window(complete=True) == {}


def test_legacy_sync_requires_fresh_complete_coverage(store):
    monday = store.plan().setup.start + timedelta(weeks=1)
    with store.db:
        store.db.execute(
            "INSERT INTO metadata VALUES ('sync', ?)",
            (json.dumps({"since": str(monday - timedelta(days=14)), "until": str(monday)}),),
        )
    with pytest.raises(ValueError, match="Sync"):
        Coach(store).adapt(AdaptRequest(week=2), today=monday)
