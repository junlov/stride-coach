"""Exercise the actual HTTP server on loopback, with generated auth and synthetic setup."""

import argparse
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    directory = parser.parse_args().directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / "api-demo.db"
    if db.exists():
        raise SystemExit("Choose a fresh demo directory; this database already exists.")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "STRIDE_COACH_API_TOKEN": token}
    command = [
        sys.executable,
        "-m",
        "stride_coach.cli",
        "--db",
        str(db),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                timeout=5,
                headers={"Authorization": f"Bearer {token}"},
                trust_env=False,
            ) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Demo server exited; inspect its local log")
                    try:
                        if client.get("/openapi.json").status_code == 200:
                            break
                    except httpx.ConnectError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Demo server did not start in ten seconds")
                unauthorized = client.get("/plan", headers={"Authorization": "Bearer invalid"})
                assert unauthorized.status_code == 401
                print("auth: invalid bearer rejected with HTTP 401")
                today = date.today()
                start = today + timedelta(days=(-today.weekday()) % 7)
                response = client.post(
                    "/goal",
                    json={
                        "setup": {
                            "goal": "return-to-running",
                            "start": str(start),
                            "race_date": str(start + timedelta(weeks=12)),
                            "days_per_week": 3,
                            "long_run_day": 6,
                        }
                    },
                )
                response.raise_for_status()
                print(f"goal: HTTP 200, {response.json()['sessions']} synthetic sessions")
                week = client.get("/weeks/1")
                week.raise_for_status()
                workout = week.json()["workouts"][0]["workout"]["id"]
                preview = client.post("/push", json={"workout": workout})
                preview.raise_for_status()
                assert len(preview.json()) == 1 and preview.json()[0]["action"] == "preview"
                print("push: HTTP 200, one default dry-run payload, zero Garmin calls")
                response = client.get("/status")
                response.raise_for_status()
                assert response.json()["scheduled_workouts"] == 0
                print("status: HTTP 200, zero scheduled Garmin workouts")
                print("server: loopback HTTP workflow complete")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
