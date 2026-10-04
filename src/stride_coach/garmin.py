"""Server-owned Garmin adapter and recoverable, explicitly requested writes."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .garmin_auth import AUTH_ERROR, GarminError, StoredSession, TokenVault
from .models import Activity, Workout
from .storage import Store

SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}


class GarminClient:
    def __init__(self, token_dir: Path, database_url: str | None = None):
        from garminconnect import Garmin

        self.api = Garmin()
        try:
            self.api.garth = StoredSession(TokenVault(token_dir, database_url))
        except GarminError:
            raise
        except Exception:
            raise GarminError(AUTH_ERROR) from None

    def _valid_token(self):
        token = self.api.garth.oauth2_token
        if not self.api.garth.oauth1_token or not token:
            raise GarminError(AUTH_ERROR)
        if token.expired:
            self.api.garth.refresh_oauth2()

    def _call(self, fn, *args, **kwargs):
        self._valid_token()
        try:
            return fn(*args, **kwargs)
        except GarminError:
            raise
        except Exception:
            # Never emit upstream exception bodies, which can contain token material.
            raise GarminError(
                "Garmin request failed. No login or write retry was attempted. "
                "Check connectivity or reconnect Garmin before retrying."
            ) from None

    def activities(self, since: date, until: date) -> list[Activity]:
        rows = self._call(
            self.api.get_activities_by_date,
            since.isoformat(),
            until.isoformat(),
            activitytype="running",
        )
        return [normalize_activity(r) for r in rows]

    def activity_detail(self, activity_id: str, *, gps: bool = True):
        from .activity_capture import fetch_detail

        return fetch_detail(self, activity_id, gps=gps)

    def workouts(self) -> list[dict]:
        result = []
        for start in range(0, 10000, 100):
            rows = self._call(self.api.get_workouts, start=start, limit=100)
            if not isinstance(rows, list):
                raise GarminError("Unexpected Garmin workout list; refusing writes.")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise GarminError("Workout inventory exceeded 10,000 records; refusing partial discovery.")

    def workout(self, remote_id: str) -> dict:
        return self._call(self.api.get_workout_by_id, remote_id)

    def calendar(self, day: date) -> list[dict]:
        path = f"/calendar-service/year/{day.year}/month/{day.month - 1}"
        data = self._call(self.api.connectapi, path)
        if not isinstance(data, dict) or not isinstance(data.get("calendarItems"), list):
            raise GarminError("Unexpected Garmin calendar response; refusing writes.")
        return data["calendarItems"]

    def create(self, payload: dict) -> str:
        data = self._call(self.api.upload_workout, payload)
        return str(int(data["workoutId"]))

    def update(self, remote_id: str, payload: dict):
        self._call(
            self.api.garth.request,
            "PUT",
            "connectapi",
            f"/workout-service/workout/{int(remote_id)}",
            api=True,
            json={**payload, "workoutId": int(remote_id)},
        )

    def schedule(self, remote_id: str, day: date):
        self._call(
            self.api.garth.post,
            "connectapi",
            f"/workout-service/schedule/{int(remote_id)}",
            api=True,
            json={"date": day.isoformat()},
        )

    def unschedule(self, schedule_id: str):
        self._call(
            self.api.garth.delete,
            "connectapi",
            f"/workout-service/schedule/{int(schedule_id)}",
            api=True,
        )

    def delete(self, remote_id: str):
        self._call(
            self.api.garth.delete,
            "connectapi",
            f"/workout-service/workout/{int(remote_id)}",
            api=True,
        )


def normalize_activity(row: dict) -> Activity:
    from .activity_capture import normalize_metrics
    from .activity_storage import store_gps

    kind = row.get("activityType", row.get("activityTypeDTO", {})).get("typeKey", "")
    running = kind in {
        "running",
        "trail_running",
        "treadmill_running",
        "track_running",
        "indoor_running",
        "ultra_run",
        "virtual_run",
        "street_running",
    }
    return Activity(
        id=str(row["activityId"]),
        day=date.fromisoformat(row["startTimeLocal"][:10]),
        distance_km=float(row["distance"]) / 1000,
        duration_min=float(row["duration"]) / 60,
        average_hr=row.get("averageHR"),
        sport="running" if running else kind,
        metrics=normalize_metrics(row),
        raw_summary=row if store_gps() else None,
        source="garmin",
    )


def tag(workout: Workout) -> str:
    return f"stride-coach:v1:{workout.id}"


def workout_payload(workout: Workout) -> dict[str, Any]:
    steps = []
    for index, step in enumerate(workout.steps, 1):
        label = step.label.lower()
        type_id, type_key = (
            (1, "warmup")
            if label == "warm up"
            else (2, "cooldown")
            if label == "cool down"
            else (4, "recovery")
            if "walk" in label or "recovery" in label
            else (3, "interval")
        )
        record = {
            "type": "ExecutableStepDTO",
            "stepOrder": index,
            "description": step.label,
            "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key},
            "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
            "endConditionValue": round(step.minutes * 60, 3),
        }
        if step.pace_min is not None:
            record.update(
                targetType={"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
                targetValueOne=1000 / step.pace_max,
                targetValueTwo=1000 / step.pace_min,
            )
        else:
            record.update(
                targetType={"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
                targetValueOne=step.hr_min,
                targetValueTwo=step.hr_max,
            )
        steps.append(record)
    return {
        "workoutName": f"SC {workout.id} {workout.kind.value}",
        "description": tag(workout),
        "sportType": SPORT,
        "estimatedDurationInSecs": round(workout.minutes * 60),
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT, "workoutSteps": steps}],
    }


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def pending(store: Store, key: str, state: bool | None = None) -> bool:
    return store.pending(key, state)


def owned_remote(client, inventory: list[dict], workout: Workout) -> dict | None:
    # Names narrow inventory reads; description is the ownership authority.
    candidates = [
        r
        for r in inventory
        if r.get("workoutName", "").startswith(f"SC {workout.id} ")
        or r.get("description") == tag(workout)
    ]
    owned = [client.workout(str(r["workoutId"])) for r in candidates]
    owned = [r for r in owned if r.get("description") == tag(workout)]
    if len(owned) > 1:
        raise GarminError("Multiple workouts share an ownership tag; resolve duplicates in Garmin.")
    return owned[0] if owned else None


def push(store: Store, workouts: list[Workout], client=None, dry_run: bool = True) -> list[dict]:
    if dry_run:
        return [
            {"action": "preview", "date": w.day.isoformat(), "payload": workout_payload(w)}
            for w in workouts
        ]
    if client is None:
        raise ValueError("A Garmin client is required for a real push")
    output = []
    with store.lock():
        # Re-read after acquiring the lock, in case an adaptation changed the plan.
        ids = {w.id for w in workouts}
        workouts = [w for w in store.plan().workouts if w.id in ids]
        inventory = client.workouts()
        for workout in workouts:
            payload = workout_payload(workout)
            digest = fingerprint(payload)
            remote = owned_remote(client, inventory, workout)
            cached = store.scheduled(workout.id)
            create_key, schedule_key = f"create:{workout.id}", f"schedule:{workout.id}"
            action = "skipped"
            if remote:
                remote_id = str(remote["workoutId"])
                pending(store, create_key, False)
                if not cached or cached["fingerprint"] != digest:
                    client.update(remote_id, payload)
                    action = "updated"
            else:
                if pending(store, create_key) or cached:
                    raise GarminError(
                        "Previous upload is unresolved or no longer discoverable. "
                        "Inspect Garmin before retrying; creation was not repeated."
                    )
                pending(store, create_key, True)
                remote_id = client.create(payload)
                inventory.append({**payload, "workoutId": remote_id})
                store.save_remote(workout.id, remote_id, digest, False)
                pending(store, create_key, False)
                action = "created"
            calendar = client.calendar(workout.day)
            scheduled = any(
                str(item.get("workoutId")) == remote_id
                and item.get("date") == workout.day.isoformat()
                and item.get("itemType") == "workout"
                for item in calendar
            )
            if not scheduled:
                if pending(store, schedule_key) or (cached and cached["scheduled"]):
                    raise GarminError(
                        "Previous calendar write is unresolved or missing. "
                        "Inspect Garmin; scheduling was not repeated."
                    )
                pending(store, schedule_key, True)
                client.schedule(remote_id, workout.day)
                action += "+scheduled"
            store.save_remote(workout.id, remote_id, digest, True)
            pending(store, schedule_key, False)
            output.append({"workout_id": workout.id, "remote_id": remote_id, "action": action})
    return output


def remove(store: Store, client=None, dry_run: bool = True) -> list[dict]:
    workouts = store.plan().workouts
    if dry_run:
        return [{"action": "preview removal", "ownership_tag": tag(w)} for w in workouts]
    if client is None:
        raise ValueError("A Garmin client is required for removal")
    output = []
    with store.lock():
        inventory = client.workouts()
        for workout in workouts:
            remote = owned_remote(client, inventory, workout)
            if remote:
                remote_id = str(remote["workoutId"])
                for item in client.calendar(workout.day):
                    if (
                        item.get("itemType") == "workout"
                        and str(item.get("workoutId")) == remote_id
                    ):
                        client.unschedule(str(item["id"]))
                client.delete(remote_id)
                output.append({"remote_id": remote_id, "action": "removed"})
            elif pending(store, f"create:{workout.id}"):
                raise GarminError(
                    "An upload is unresolved. Removal cannot confirm absence; "
                    "inspect Garmin and retry after the workout becomes visible."
                )
            store.forget_remote(workout.id)
            pending(store, f"create:{workout.id}", False)
            pending(store, f"schedule:{workout.id}", False)
    return output
