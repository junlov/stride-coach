"""Prove the Docker package using disposable, synthetic Compose resources only."""

import os
import secrets
import socket
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = "stride-proof-" + uuid.uuid4().hex[:10]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = secrets.token_hex(32)
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project,
        "STRIDE_COACH_API_TOKEN": token,
        "POSTGRES_USER": "stride",
        "POSTGRES_DB": "stride",
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "PORT": str(port),
        "BIND_ADDRESS": "127.0.0.1",
        "STRIDE_COACH_TOKENS": "/data/garmin",
        "STRIDE_COACH_CORS_ORIGINS": "",
        "TZ": "UTC",
    }
    env.pop("DATABASE_URL", None)
    # Ignore an operator's .env. All resources belong to this random disposable project.
    base = ["docker", "compose", "--env-file", "/dev/null", "-p", project]

    def compose(*args):
        result = subprocess.run(
            [*base, *args], cwd=ROOT, env=env, text=True, capture_output=True, check=False
        )
        if result.returncode:
            # Redact generated credentials from diagnostic output.
            detail = result.stderr[-4000:]
            for secret in (token, env["POSTGRES_PASSWORD"]):
                detail = detail.replace(secret, "[redacted]")
            raise RuntimeError(f"Compose {args[0]} failed (exit {result.returncode}): {detail}")
        return result.stdout.strip()

    def python(code):
        return compose("exec", "-T", "api", "python", "-c", code)

    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False
        ) as client:
            assert client.get("/health").json() == {"status": "ready"}
            assert client.get("/plan").status_code == 401
            client.headers["Authorization"] = f"Bearer {token}"
            today = date.today()
            monday = today + timedelta(days=(-today.weekday()) % 7)
            response = client.post(
                "/goal",
                json={
                    "setup": {
                        "goal": "return-to-running",
                        "start": str(monday),
                        "race_date": str(monday + timedelta(weeks=12)),
                        "days_per_week": 3,
                    }
                },
            )
            response.raise_for_status()
            assert response.json()["sessions"] == 36
            plan = client.get("/plan").json()
            response = client.post("/push", json={"week": 1})
            response.raise_for_status()
            assert all(item["action"] == "preview" for item in response.json())
            response = client.post(
                "/sync",
                json={
                    "since": str(today),
                    "until": str(today),
                    "activities": [
                        {
                            "id": "synthetic-proof-run",
                            "day": str(today),
                            "distance_km": 5,
                            "duration_min": 30,
                        }
                    ],
                },
            )
            response.raise_for_status()
            assert response.json()["synced"] == 1
            python("""
from stride_coach.storage import Store
from stride_coach.garmin_auth import GarminConnection
from pathlib import Path
store = Store()
store.pending('create:' + store.plan().workouts[0].id, True)
store.close()
vault = GarminConnection(Path('/data/garmin')).vault
with vault.locked():
    vault.write({'generation': 'synthetic-volume-proof'})
""")
            print(
                "clean install: healthy, unauthenticated data rejected, 36 sessions, preview only"
            )
            print(
                "synthetic state: one activity, durable pending upload, private session generation"
            )
            status = client.get("/status").json()
            compose("restart", "api", "postgres")
            compose("up", "-d", "--wait", "--wait-timeout", "120")
            assert client.get("/plan").json() == plan
            assert client.get("/status").json() == status
            assert (
                python("""
from stride_coach.storage import Store
from stride_coach.garmin_auth import GarminConnection
from pathlib import Path
store = Store()
assert len(store.activities()) == 1
assert store.pending('create:' + store.plan().workouts[0].id)
store.close()
vault = GarminConnection(Path('/data/garmin')).vault
with vault.locked():
    assert vault.read()['generation'] == 'synthetic-volume-proof'
print('persisted')
""")
                == "persisted"
            )
            print("restart: plan, activity, pending upload, and Garmin volume persisted")
            compose("stop", "api")
            # Exercise the previous packaged revision with data, never an operator database.
            compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "api",
                "-c",
                """
from alembic import command
from stride_coach.database import make_engine, migration_config
with make_engine().begin() as db:
    command.downgrade(migration_config(db), '0001')
""",
            )
            compose("up", "-d", "--wait", "--wait-timeout", "120")
            assert client.get("/health").json() == {"status": "ready"}
            assert client.get("/plan").json() == plan
            assert client.get("/status").json() == status
            assert (
                python("""
from sqlalchemy import text
from stride_coach.storage import Store
store = Store()
assert store.pending('create:' + store.plan().workouts[0].id)
assert len(store.activities()) == 1
with store.connection.begin():
    print(store.connection.scalar(text('SELECT version_num FROM alembic_version')))
store.close()
""")
                == "0002"
            )
            print(
                "upgrade: startup migrated 0001 to 0002; "
                "plan, activity, and pending intent preserved"
            )
            print("CLI: " + compose("exec", "-T", "api", "stride-coach", "db", "upgrade"))
            # A dump is generated and restored within the disposable project for runbook proof.
            dump = compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/proof.dump '
                "&& pg_restore --list /tmp/proof.dump | wc -l",
            )
            assert int(dump) > 20
            compose("stop", "api")
            compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                "--clean --if-exists --no-owner --exit-on-error /tmp/proof.dump",
            )
            compose("up", "-d", "--wait", "--wait-timeout", "120")
            assert client.get("/plan").json() == plan
            print("backup: pg_dump and pg_restore preserved the synthetic plan")
            print("proof complete: zero Garmin calls, no published image, no live account")
    finally:
        compose("down", "--volumes", "--remove-orphans")
        print("cleanup: disposable Compose containers, network, and volumes removed")


if __name__ == "__main__":
    main()
