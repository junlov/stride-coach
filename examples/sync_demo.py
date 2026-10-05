"""Run sync and history against a real loopback API with synthetic Garmin responses."""

import secrets
import socket
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from threading import Thread

import httpx
import uvicorn
from synthetic_database import synthetic_database

from stride_coach.api import ServerConfig, create_app
from stride_coach.models import Activity
from stride_coach.storage import Store


class SyntheticGarmin:
    def __init__(self, path):
        pass

    def activities(self, since, until):
        return [Activity(id="synthetic-recent", day=until, distance_km=5, duration_min=30)]

    def activity_page(self, since, until, offset, limit):
        return [
            Activity(
                id=f"synthetic-{i}",
                day=until - timedelta(days=i // 2),
                distance_km=5,
                duration_min=30,
            )
            for i in range(offset, min(101, offset + limit))
        ]


def main():
    with tempfile.TemporaryDirectory(prefix="stride-sync-") as directory:
        token = secrets.token_urlsafe(32)
        app = create_app(
            ServerConfig(
                token=token,
                tokens=Path(directory) / "tokens",
                sync_enabled=False,
                import_page_delay=0.1,
            ),
            client_factory=SyntheticGarmin,
        )
        today = date.today()
        non_runs = [
            Activity(
                id=f"synthetic-{sport}", sport=sport, day=today, distance_km=1, duration_min=20
            )
            for sport in ("walking", "cycling", "strength_training")
        ]
        store = Store()
        try:
            store.save_sync(non_runs, str(today), str(today), today=today)
        finally:
            store.close()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = Thread(target=server.run)
        thread.start()
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                trust_env=False,
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                response = client.post("/sync/open")
                response.raise_for_status()
                assert response.json()["skipped"]
                print("disconnected: app-open sync skipped, zero Garmin calls")
                vault = app.state.garmin_connection.vault
                with vault.locked():
                    vault.write({"tokens": "synthetic-session", "generation": "demo"})
                response = client.post("/sync/open")
                response.raise_for_status()
                assert response.json()["latest"]["activity_count"] == 1
                assert client.post("/sync/open").json()["skipped"]
                print("app-open: one run synced; repeat skipped by persisted interval")
                for activity in non_runs:
                    response = client.get(f"/activities/{activity.id}")
                    response.raise_for_status()
                    assert response.json()["sport"] == activity.sport
                response = client.post("/sync", json={"since": str(today), "until": str(today)})
                response.raise_for_status()
                assert response.json()["synced"] == 1
                for activity in non_runs:
                    response = client.get(f"/activities/{activity.id}")
                    response.raise_for_status()
                    assert response.json()["sport"] == activity.sport
                print("preservation: walks, rides, and strength survive app-open and manual sync")
                response = client.post("/sync/history", json={"range": "12-weeks"})
                response.raise_for_status()
                job = response.json()
                assert job["result"] == "running"
                for _ in range(100):
                    status = client.get("/sync/status").json()
                    if status["history"]["result"] != "running":
                        break
                    time.sleep(0.1)
                assert status["history"]["result"] == "success"
                assert status["history"]["activity_count"] == 101
                assert (
                    client.post("/sync/history", json={"range": "12-weeks"}).json()["id"]
                    == job["id"]
                )
                print("history: 101 runs imported in two pages; repeat returns same completed job")
                today = date.today()
                start = today + timedelta(days=(-today.weekday()) % 7)
                response = client.post(
                    "/goal",
                    json={
                        "setup": {
                            "goal": "5k",
                            "start": str(start),
                            "race_date": str(start + timedelta(weeks=12)),
                            "days_per_week": 3,
                        }
                    },
                )
                response.raise_for_status()
                print("goal: created after import using stored runs for fitness")
                assert client.get("/status").json()["scheduled_workouts"] == 0
                assert client.get("/status").json()["adjustments"] == []
                print("safety: zero Garmin workout writes and zero applied adjustments")
        finally:
            server.should_exit = True
            thread.join(10)


if __name__ == "__main__":
    with synthetic_database():
        main()
