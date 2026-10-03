import socket
from datetime import date, timedelta

import pytest
import requests

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
def store(tmp_path, plan):
    db = Store(tmp_path / "coach.db")
    db.initialize(plan)
    yield db
    db.close()
