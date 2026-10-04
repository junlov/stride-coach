"""Seed the dedicated contributor database once, without Garmin traffic."""

import os
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from stride_coach.db_models import PlanRow
from stride_coach.models import Activity, Setup
from stride_coach.service import Coach, GoalRequest
from stride_coach.storage import Store

store = Store(os.environ["DATABASE_URL"])
try:
    with store.transaction() as session:
        exists = session.scalar(select(PlanRow.id).limit(1)) is not None
    if exists:
        print("Existing dev plan retained.")
    else:
        today = date.today()
        start = today + timedelta(days=(-today.weekday()) % 7)
        runs = [
            Activity(
                id="synthetic-dev-run",
                day=today - timedelta(days=1),
                distance_km=3,
                duration_min=24,
                average_hr=135,
                sport="running",
            )
        ]
        coach = Coach(store, token_dir=Path(os.environ["STRIDE_COACH_TOKENS"]))
        result = coach.initialize(
            GoalRequest(
                setup=Setup(
                    goal="return-to-running",
                    start=start,
                    race_date=start + timedelta(weeks=12),
                    days_per_week=3,
                    long_run_day=6,
                ),
                recent_runs=runs,
            )
        )
        store.save_sync(runs, since=str(runs[0].day), until=str(runs[0].day))
        print(f"Seeded {result.sessions} synthetic sessions and one synthetic run.")
finally:
    store.close()
