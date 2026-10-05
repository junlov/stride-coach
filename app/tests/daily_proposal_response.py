"""Emit a synthetic response from the daily proposal HTTP endpoint for mobile tests."""

from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from stride_coach.api import ServerConfig, create_app
from stride_coach.engine import generate_plan, make_steps
from stride_coach.models import Activity, Goal, Kind, Setup
from stride_coach.recovery_models import DailyReadiness

setup = Setup(
    goal=Goal.TEN_K,
    start=date(2026, 10, 5),
    race_date=date(2027, 1, 3),
    days_per_week=4,
    long_run_day=6,
)
runs = [
    Activity(id=str(i), day=setup.start - timedelta(days=i + 1), distance_km=7, duration_min=40)
    for i in range(12)
]
plan = generate_plan(setup, runs)
workout = plan.workouts[0]
workout.kind = Kind.INTERVALS
workout.steps = make_steps(Kind.INTERVALS, 40, plan.fitness, setup, 5)
today = workout.day - timedelta(days=1)
now = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
store = SimpleNamespace(
    plan=lambda: plan,
    resolve_workout_targets=lambda workout: workout,
    readiness=lambda day: DailyReadiness(day=day, fetched_at=now, training_readiness=10),
    daily_adjustment=lambda _: None,
    scheduled=lambda _: None,
    lock=nullcontext,
    close=lambda: None,
)
token = "synthetic-mobile-response-token-only"
app = create_app(
    ServerConfig(
        token=token,
        database_url="postgresql://schema:synthetic-schema-password@localhost/schema",
        sync_enabled=False,
    )
)
with patch("stride_coach.api.Store", return_value=store):
    app.state.sync_worker.now = lambda: now
    response = TestClient(app).get(
        "/adjustments/daily", headers={"Authorization": f"Bearer {token}"}
    )
    response.raise_for_status()
    print(response.text)
