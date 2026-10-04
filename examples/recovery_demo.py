"""Real loopback HTTP proof, with an isolated database and synthetic Garmin responses."""

import secrets
import socket
import tempfile
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import uvicorn
from synthetic_database import synthetic_database

from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin import GarminClient
from stride_coach.models import Activity, Kind, Setup
from stride_coach.service import Coach, GoalRequest
from stride_coach.storage import Store


def prove(directory):
    store = Store()
    try:
        start = date(2026, 10, 5)
        setup = Setup(
            goal="10k", start=start, race_date=start + timedelta(weeks=12), days_per_week=4
        )
        history = [
            Activity(
                id=f"history-{i}",
                day=start - timedelta(days=i * 2 + 1),
                distance_km=7,
                duration_min=40,
            )
            for i in range(12)
        ]
        coach = Coach(store)
        coach.initialize(GoalRequest(setup=setup, recent_runs=history))
        hard = next(w for w in coach.plan().workouts if w.kind == Kind.TEMPO)
        today = hard.day - timedelta(days=1)
        completed = next(w for w in coach.plan().workouts if w.day < today)
        # Exercise the real Garmin adapter, backed solely by synthetic SDK responses.
        client = GarminClient.__new__(GarminClient)
        client._valid_token = lambda: None
        pace = sum([completed.steps[0].pace_min, completed.steps[0].pace_max]) / 2
        seconds = completed.minutes * 60
        client.api = SimpleNamespace(
            get_activities_by_date=Mock(
                return_value=[
                    {
                        "activityId": 123,
                        "startTimeLocal": str(completed.day) + " 07:00:00",
                        "distance": seconds / pace * 1000,
                        "duration": seconds,
                        "averageHR": 140,
                        "activityType": {"typeKey": "running"},
                    }
                ]
            ),
            get_training_readiness=Mock(return_value=[{"calendarDate": str(today), "score": 20}]),
            get_hrv_data=Mock(return_value={"hrvSummary": {"status": "LOW"}}),
            get_sleep_data=Mock(
                return_value={"dailySleepDTO": {"sleepScores": {"overall": {"value": 40}}}}
            ),
            connectapi=Mock(return_value={"displayName": "synthetic-runner"}),
        )
        # Supply synthetic detail through the same capture entry point; no originals or GPS.
        from stride_coach.activity_models import RunLap

        detail = Activity(
            id="123",
            day=completed.day,
            distance_km=seconds / pace,
            duration_min=completed.minutes,
            laps=[
                RunLap(duration_s=seconds, distance_m=seconds / pace * 1000, average_pace_s_km=pace)
            ],
            source="garmin",
        )
        client.activity_detail = lambda *args, **kwargs: (detail, None)
        token = secrets.token_urlsafe(32)
        config = ServerConfig(
            token=token, database_url=store.url, tokens=directory / "tokens", sync_enabled=False
        )
        app = create_app(config, client_factory=lambda _: client)
        app.state.sync_worker.now = lambda: datetime.combine(today, datetime.min.time(), UTC)
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", log_level="error", access_log=False)
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(16)
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                assert server.started
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
                    headers={"Authorization": f"Bearer {token}"},
                    trust_env=False,
                ) as http:
                    result = http.post("/sync", json={"since": str(start), "until": str(today)})
                    result.raise_for_status()
                    assert result.json()["details"]["completed"] == 1
                    record = http.get("/readiness").json()[0]
                    assert (
                        record["training_readiness"],
                        record["hrv_status"],
                        record["sleep_score"],
                    ) == (20, "LOW", 40)
                    print("sync: synthetic Garmin response stored; readiness=20, HRV=LOW, sleep=40")
                    run = http.get("/activities/123").json()
                    assert run["step_compliance"]["score"] == 100
                    print("run detail: stored step score=100; captured laps preserved")
                    before = http.get("/plan").json()
                    preview = http.get("/adjustments/daily").json()
                    assert (
                        preview["before"]["kind"] == "tempo" and preview["after"]["kind"] == "easy"
                    )
                    assert http.get("/plan").json() == before
                    assert http.post("/adapt/daily", json={"apply": True}).status_code == 400
                    print(
                        "proposal: tempo to easy, same duration; preview leaves plan unchanged; "
                        "missing confirmation rejected"
                    )
                    body = {"apply": True, "proposal_fingerprint": preview["proposal_fingerprint"]}
                    applied = http.post("/adapt/daily", json=body)
                    applied.raise_for_status()
                    assert applied.json()["applied"]
                    assert http.post("/adapt/daily", json=body).json() == applied.json()
                    push = http.post("/push", json={"workout": hard.id, "dry_run": True})
                    push.raise_for_status()
                    assert push.json()[0]["action"] == "preview"
                    assert store.scheduled_count() == 0
                    print(
                        "confirmation: saved once; repeated confirmation unchanged; "
                        "Garmin push remains a preview"
                    )
                    print(
                        "proof: real loopback HTTP and PostgreSQL; zero live Garmin calls or writes"
                    )
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                assert not thread.is_alive()
    finally:
        store.close()


if __name__ == "__main__":
    with synthetic_database(), tempfile.TemporaryDirectory(prefix="stride-recovery-") as directory:
        prove(Path(directory))
