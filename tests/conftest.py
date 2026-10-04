import os
import socket
import uuid
from datetime import date, timedelta

import pytest
import requests
from sqlalchemy import text
from sqlalchemy.engine import make_url

from stride_coach.database import make_engine, upgrade
from stride_coach.engine import generate_plan
from stride_coach.models import Activity, Goal, Setup
from stride_coach.storage import Store


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden in the offline test suite")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Set TEST_DATABASE_URL to a disposable PostgreSQL database. See docs/self-hosting.md."
        )
    engine = make_engine(url)
    schema = "test_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    url = scoped.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    upgrade(url)
    try:
        yield url
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture
def setup():
    return Setup(
        goal=Goal.TEN_K,
        start=date(2026, 10, 5),
        race_date=date(2027, 1, 3),
        days_per_week=4,
        long_run_day=6,
    )


@pytest.fixture
def runs(setup):
    return [
        Activity(
            id=str(i),
            day=setup.start - timedelta(days=i * 2 + 1),
            distance_km=7,
            duration_min=40,
            average_hr=140,
            best_effort=i == 0,
        )
        for i in range(12)
    ]


@pytest.fixture
def plan(setup, runs):
    return generate_plan(setup, runs)


@pytest.fixture
def store(database, plan):
    db = Store(database)
    db.initialize(plan)
    yield db
    db.close()


@pytest.fixture
def legacy_store(database, plan):
    """Pre-structure plan for upgrade tests, using only the old timed-step contract."""
    from stride_coach.models import RepeatGroup, Step

    for workout in plan.workouts:
        leaves = []
        for block in workout.steps:
            children = (
                block.steps * block.repetitions if isinstance(block, RepeatGroup) else [block]
            )
            if isinstance(block, RepeatGroup) and block.skip_last_rest:
                children = children[:-1]
            leaves.extend(
                Step(
                    **step.model_dump(
                        include={"label", "minutes", "pace_min", "pace_max", "hr_min", "hr_max"}
                    )
                )
                for step in children
            )
        workout.steps = leaves
    db = Store(database)
    db.initialize(plan)
    yield db
    db.close()
