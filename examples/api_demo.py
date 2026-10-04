"""Exercise the actual HTTP server on loopback, with generated auth and synthetic setup."""

import argparse
import asyncio
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def prove_mcp(base_url: str, token: str):
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        trust_env=False,
        timeout=10,
    ) as client:
        async with streamable_http_client(f"{base_url}/mcp/", http_client=client) as (
            reader,
            writer,
            _,
        ):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                expected = {
                    "plan": {},
                    "week": {"number": 1},
                    "compliance": {},
                    "load": {},
                    "propose_adjustment": {"number": 2},
                    "today_workout": {},
                    "current_week": {},
                    "status": {},
                    "readiness": {},
                    "propose_daily_adjustment": {},
                    "activity": {"activity_id": "synthetic-demo"},
                }
                assert {tool.name for tool in tools} == set(expected)
                assert all(tool.annotations.readOnlyHint for tool in tools)
                for name, arguments in expected.items():
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, name
                for name in ("sync", "push", "remove", "adapt", "apply"):
                    result = await session.call_tool(name, {"apply": True})
                    assert result.isError, name
                print(
                    "mcp: Streamable HTTP handshake, 11 read-only tools called, "
                    "5 write names rejected"
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    directory = parser.parse_args().directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "STRIDE_COACH_API_TOKEN": token}
    command = [
        sys.executable,
        "-m",
        "stride_coach.cli",
        "--tokens",
        str(directory / "garmin"),
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
                imported = client.post(
                    "/sync",
                    json={
                        "since": str(today),
                        "until": str(today),
                        "activities": [
                            {
                                "id": "synthetic-demo",
                                "day": str(today),
                                "distance_km": 3,
                                "duration_min": 20,
                            }
                        ],
                    },
                )
                imported.raise_for_status()
                before = client.get("/status").json()
                unauthorized = client.post("/mcp/", headers={"Authorization": "Bearer invalid"})
                assert unauthorized.status_code == 401
                print("mcp auth: invalid bearer rejected with HTTP 401")
                asyncio.run(prove_mcp(str(client.base_url).rstrip("/"), token))
                assert client.get("/status").json() == before
                print("mcp: stored status unchanged after all tool calls")
                print("server: loopback HTTP workflow complete")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    from synthetic_database import synthetic_database

    with synthetic_database():
        main()
