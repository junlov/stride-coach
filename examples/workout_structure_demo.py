"""Synthetic workout proof. Builds the actual plan and Garmin payloads without a client."""

import json
from datetime import date, timedelta
from pathlib import Path
import argparse

from stride_coach.engine import estimate_fitness, make_steps
from stride_coach.garmin import workout_payload
from stride_coach.models import Activity, Kind, Setup, Workout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    setup = Setup(goal="10k", start=date(2026, 10, 5), race_date=date(2027, 1, 3), days_per_week=4)
    runs = [Activity(id=str(i), day=setup.start - timedelta(days=i * 2 + 1), distance_km=7,
                     duration_min=40, average_hr=140, best_effort=i == 0) for i in range(12)]
    for kind in Kind:
        workout = Workout(id=f"synthetic-{kind.value}", day=setup.start, week=5, phase="build", kind=kind,
            steps=make_steps(kind, 40, estimate_fitness(runs, setup), setup, 5))
        payload = workout_payload(workout)
        if args.directory:
            args.directory.mkdir(parents=True, exist_ok=True)
            (args.directory / f"{kind.value}.json").write_text(json.dumps(payload, indent=2) + "\n")
        blocks = payload["workoutSegments"][0]["workoutSteps"]
        repeats = [s["numberOfIterations"] for s in blocks if s["type"] == "RepeatGroupDTO"]
        print(f"{kind.value}: {payload['estimatedDurationInSecs']} estimated seconds; "
              f"{len(blocks)} blocks; repeats={repeats}")
    print("Garmin clients created: 0; Garmin requests: 0")


if __name__ == "__main__":
    main()
