"""Run the public CLI and local adaptation with synthetic data, without a Garmin account."""

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from stride_coach.adaptation import adapt
from stride_coach.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    directory = parser.parse_args().directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=2)
    end = start + timedelta(weeks=12)

    def cli(*args):
        process = subprocess.run(
            [sys.executable, "-m", "stride_coach.cli", *args],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(process.stdout)

    created = cli("init", "return-to-running", str(end), "--start", str(start), "--days", "3")
    print(f"init: {created['sessions']} run-walk sessions, synthetic baseline")
    week = cli("plan", "--week", "3")
    # A future week is always available for the real CLI's date guard.
    previews = cli("push", "--week", "4", "--dry-run")
    print(f"push: {len(previews)} local payload previews, zero Garmin calls")
    preview = previews[0]["payload"]
    view = cli("plan", "--week", "4")["workouts"][0]["workout"]
    assert view["name"] == preview["workoutName"]
    assert len(preview["workoutName"]) <= 15
    assert preview["description"].splitlines()[-1] == f"stride-coach:v1:{view['id']}"
    print(f"workout: {view['name']} (same name in API view and Garmin preview)")
    print("guidance: " + preview["description"].splitlines()[0])
    print("first step: " + preview["workoutSegments"][0]["workoutSteps"][0]["description"])
    workouts = cli("plan", "--week", "2")["workouts"]
    activities = [
        {
            "id": f"demo-{i}",
            "day": w["workout"]["day"],
            "distance_km": 2,
            "duration_min": w["minutes"],
            "average_hr": 135,
            "sport": "running",
            "kind": "run-walk",
        }
        for i, w in enumerate(workouts[:1])
    ]
    source = directory / "synthetic-activities.json"
    source.write_text(json.dumps(activities))
    result = cli(
        "sync",
        "--since",
        str(start),
        "--until",
        str(monday - timedelta(days=1)),
        "--activities",
        str(source),
    )
    print(f"sync: {result['synced']} synthetic completed run")
    store = Store()
    try:
        proposal = adapt(store, 3, monday)
        applied = adapt(
            store,
            3,
            monday,
            apply=True,
            proposal_fingerprint=proposal.inputs["proposal_fingerprint"],
        )
        repeated = adapt(
            store,
            3,
            monday,
            apply=True,
            proposal_fingerprint=proposal.inputs["proposal_fingerprint"],
        )
        assert applied == repeated
        assert proposal.factor == 0.75
        assert len(week["workouts"]) == 3
        print(f"adapt: simulated Monday {monday}, factor {applied.factor}, applied once")
        print("reason: " + applied.reasons[0])
    finally:
        store.close()
    status = cli("status")
    assert len(status["adjustments"]) == 1
    print("status: one persisted adjustment; offline loop complete")


if __name__ == "__main__":
    from synthetic_database import synthetic_database

    with synthetic_database():
        main()
