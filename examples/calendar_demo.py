"""Prove calendar reconciliation over real loopback HTTP using synthetic Garmin only."""

import secrets
import socket
import tempfile
import time
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from threading import Thread

import httpx
import uvicorn
from synthetic_database import synthetic_database

from stride_coach.api import ServerConfig, create_app
from stride_coach.db_models import StepRow
from stride_coach.storage import Store


class SyntheticGarmin:
    def __init__(self):
        self.data, self.events, self.writes = {}, [], []
        self.next_id = 1

    def workouts(self):
        return list(self.data.values())

    def workout(self, remote_id):
        return deepcopy(self.data[remote_id])

    def calendar(self, day):
        return deepcopy(self.events)

    def create(self, payload):
        remote_id = str(self.next_id)
        self.next_id += 1
        self.data[remote_id] = {**deepcopy(payload), "workoutId": remote_id}
        self.writes.append("create")
        return remote_id

    def update(self, remote_id, payload):
        self.data[remote_id] = {**deepcopy(payload), "workoutId": remote_id}
        self.writes.append("update")

    def schedule(self, remote_id, day):
        self.events.append(
            {"id": remote_id, "workoutId": remote_id, "date": str(day), "itemType": "workout"}
        )
        self.writes.append("schedule")

    def unschedule(self, schedule_id):
        self.events = [e for e in self.events if str(e["id"]) != schedule_id]
        self.writes.append("unschedule")

    def delete(self, remote_id):
        del self.data[remote_id]
        self.writes.append("delete")


def main():
    fake = SyntheticGarmin()
    with tempfile.TemporaryDirectory(prefix="stride-calendar-") as directory:
        token = secrets.token_urlsafe(32)
        app = create_app(
            ServerConfig(token=token, tokens=Path(directory), sync_enabled=False),
            client_factory=lambda _: fake,
        )
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
                timeout=30,
            ) as api:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                today = date.today()
                start = today + timedelta(days=(-today.weekday()) % 7)
                result = api.post(
                    "/goal",
                    json={
                        "setup": {
                            "goal": "5k",
                            "start": str(start),
                            "race_date": str(start + timedelta(weeks=12)),
                            "days_per_week": 4,
                        }
                    },
                )
                result.raise_for_status()
                preview = api.post("/calendar", json={})
                preview.raise_for_status()
                assert not fake.writes
                print(f"preview: {len(preview.json()['changes'])} creates, zero Garmin writes")
                result = api.post(
                    "/calendar", json={"apply": True, "preview_id": preview.json()["preview_id"]}
                )
                result.raise_for_status()
                assert not api.get("/status").json()["garmin_out_of_date"]
                fake.data["personal"] = {"workoutId": "personal", "workoutName": "My workout"}
                store = Store()
                try:
                    workout = store.plan().workouts[0]
                    with store.transaction() as session:
                        session.get(StepRow, (workout.id, 0)).minutes *= 0.8
                finally:
                    store.close()
                assert api.get("/status").json()["garmin_out_of_date"]
                print("plan change: persistent Garmin out-of-date status")
                result = api.post("/calendar/settings", json={"window_days": 7})
                result.raise_for_status()
                writes_before = len(fake.writes)
                preview = api.post("/calendar", json={}).json()
                actions = [c["action"] for c in preview["changes"]]
                assert "update" in actions and "remove" in actions
                assert len(fake.writes) == writes_before
                print(
                    f"review: {actions.count('update')} update, "
                    f"{actions.count('remove')} removals, no writes"
                )
                result = api.post(
                    "/calendar", json={"apply": True, "preview_id": preview["preview_id"]}
                )
                result.raise_for_status()
                assert "personal" in fake.data
                assert all(
                    today <= date.fromisoformat(e["date"]) < today + timedelta(days=7)
                    for e in fake.events
                )
                assert api.post("/calendar", json={}).json()["changes"] == []
                print(
                    "confirmed: seven-day window, personal workout preserved, "
                    "repeated preview empty"
                )
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    with synthetic_database():
        main()
