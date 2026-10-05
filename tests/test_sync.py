from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stride_coach.db_models import MetadataRow
from stride_coach.models import Activity
from stride_coach.service import AdaptRequest, Coach, SyncRequest
from stride_coach.storage import Store


@pytest.mark.parametrize("local_import", [False, True])
def test_sync_upserts_runs_and_preserves_other_activities(store, local_import):
    plan = store.plan()
    day = plan.workouts[0].day
    run = Activity(id="kept", day=day, distance_km=5, duration_min=30, average_hr=140)
    non_runs = [
        run.model_copy(update={"id": sport, "sport": sport})
        for sport in ("walking", "cycling", "strength_training")
    ]
    before = run.model_copy(update={"id": "before", "day": day - timedelta(days=1)})
    after = run.model_copy(update={"id": "after", "day": day + timedelta(days=1)})
    coach = Coach(store)
    coach.sync(
        SyncRequest(
            since=before.day,
            until=after.day,
            activities=[before, run, *non_runs, after],
        ),
        today=after.day + timedelta(days=1),
    )

    fetched = [run.model_copy(update={"duration_min": 35})]

    class Garmin:
        def activities(self, since, until):
            assert (since, until) == (day, day)
            return fetched

    coach = Coach(store, client_factory=lambda _: Garmin())
    request = SyncRequest(since=day, until=day)
    if local_import:
        request.activities = [run.model_copy(update={"duration_min": 35})]
    coach.sync(request, today=after.day)
    expected_ids = {"before", "kept", "after", *(a.id for a in non_runs)}
    assert {a.id for a in store.activities()} == expected_ids
    assert all(a in store.activities() for a in non_runs)
    assert next(a for a in store.activities() if a.id == "kept").duration_min == 35
    metrics = coach.week(1).metrics
    assert metrics.completed_minutes == sum(
        a.duration_min
        for a in store.activities()
        if a.day >= plan.setup.start and a.sport == "running"
    )
    assert any(m.activity_id == "kept" for m in metrics.matches)
    # Repeated partial imports update the same ID without duplicating or deleting records.
    coach.sync(request, today=after.day)
    assert {a.id for a in store.activities()} == expected_ids
    if local_import:
        request.activities = []
    else:
        fetched.clear()
    coach.sync(request, today=after.day)
    assert {a.id for a in store.activities()} == expected_ids
    assert coach.week(1).metrics == metrics
    assert store.plan() == plan


def test_sync_rolls_back_upserts_and_coverage(store):
    today = store.plan().setup.start
    day = today - timedelta(days=1)
    run = Activity(id="old", day=day, distance_km=5, duration_min=30)
    store.save_sync([run], str(day), str(day), today=today)
    window = store.sync_window()
    complete = store.sync_window(complete=True)
    with store.connection.begin():
        store.connection.execute(
            text("""
            CREATE FUNCTION reject_coverage() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'coverage failure' USING ERRCODE = '23514'; END;
            $$
        """)
        )
        store.connection.execute(
            text("""
            CREATE TRIGGER reject_coverage BEFORE INSERT OR UPDATE ON metadata
            FOR EACH ROW WHEN (NEW.key = 'sync_complete') EXECUTE FUNCTION reject_coverage()
        """)
        )
    with pytest.raises(IntegrityError, match="coverage failure"):
        store.save_sync(
            [run.model_copy(update={"duration_min": 35}), run.model_copy(update={"id": "new"})],
            str(day - timedelta(days=1)),
            str(today),
            today=today,
        )
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
    with store.transaction() as session:
        session.add(MetadataRow(key="sync", since=monday - timedelta(days=14), until=monday))
    with pytest.raises(ValueError, match="Sync"):
        Coach(store).adapt(AdaptRequest(week=2), today=monday)


def test_concurrent_sync_preserves_newer_snapshot(store, monkeypatch):
    monday = store.plan().setup.start + timedelta(weeks=1)
    sunday = monday - timedelta(days=1)
    since = monday - timedelta(days=14)
    run = Activity(id="new-run", day=sunday, distance_km=5, duration_min=30)
    first_fetched, release_first = Event(), Event()
    second_lock_attempted, second_fetched = Event(), Event()
    second_store = Store(store.url)
    shared_lock = second_store.lock

    @contextmanager
    def observed_lock():
        second_lock_attempted.set()
        with shared_lock():
            yield

    monkeypatch.setattr(second_store, "lock", observed_lock)

    class OlderGarmin:
        def activities(self, begin, end):
            first_fetched.set()
            assert release_first.wait(5)
            return []

    class NewerGarmin:
        def activities(self, begin, end):
            second_fetched.set()
            return [run]

    older = Coach(store, client_factory=lambda _: OlderGarmin())
    newer = Coach(second_store, client_factory=lambda _: NewerGarmin())
    request = SyncRequest(since=since, until=sunday)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(older.sync, request, today=monday)
            try:
                assert first_fetched.wait(5)
                second = pool.submit(newer.sync, request, today=monday)
                assert second_lock_attempted.wait(5)
                if second_fetched.is_set():
                    second.result(timeout=5)
            finally:
                release_first.set()
            first.result(timeout=5)
            second.result(timeout=5)
        assert store.activities() == [run]
        assert store.sync_window(complete=True) == {"since": str(since), "until": str(sunday)}
        assert older.week(1).metrics.completed_minutes == 30
        assert not older.adapt(AdaptRequest(week=2), today=monday).applied
    finally:
        second_store.close()
