"""Server-owned Garmin adapter and recoverable, explicitly requested writes."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .garmin_auth import AUTH_ERROR, GarminError, StoredSession, TokenVault
from .models import Activity, GarminHeartRateZone, RepeatGroup, Step, Workout
from .storage import Store
from .workout_text import step_description, workout_description, workout_name

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

    def activity_page(self, since: date, until: date, offset: int, limit: int = 100):
        rows = self._call(
            self.api.connectapi,
            self.api.garmin_connect_activities,
            params={
                "startDate": since.isoformat(),
                "endDate": until.isoformat(),
                "start": str(offset),
                "limit": str(limit),
                "activityType": "running",
                "sortOrder": "asc",
            },
        )
        if not isinstance(rows, list):
            raise GarminError("Unexpected Garmin activity page. Retry the import.")
        return [normalize_activity(row) for row in rows]

    def activity_detail(self, activity_id: str, *, gps: bool = True):
        from .activity_capture import fetch_detail

        return fetch_detail(self, activity_id, gps=gps)

    def readiness(self, day: date):
        from .recovery import parse_readiness

        def optional(method):
            try:
                return self._call(method, day.isoformat())
            except Exception:
                # Unsupported devices, absent fields, and provider failures are normal here.
                # Never persist upstream exception text or prevent activity sync.
                return None

        training = optional(self.api.get_training_readiness)
        hrv = optional(self.api.get_hrv_data)
        sleep = None
        try:
            # The stored connection label may be a full name. Sleep needs Garmin's
            # actual displayName identifier, obtained through the same read-only transport.
            profile = self._call(self.api.connectapi, "/userprofile-service/userprofile/profile")
            name = profile.get("displayName")
            if isinstance(name, str) and name:
                self.api.display_name = name
                sleep = optional(self.api.get_sleep_data)
        except Exception:
            pass
        return parse_readiness(day, training, hrv, sleep)

    def heart_rate_zones(self) -> list[GarminHeartRateZone]:
        # The pinned library lacks the convenience method, but exposes connectapi.
        payload = self._call(self.api.connectapi, "/biometric-service/heartRateZones/")
        return normalize_heart_rate_zones(payload)

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


def normalize_heart_rate_zones(payload) -> list[GarminHeartRateZone]:
    """Use current running settings, or account defaults when running is absent."""
    if not isinstance(payload, list):
        return []
    profiles = {row.get("sport"): row for row in payload if isinstance(row, dict)}
    profile = profiles.get("RUNNING", profiles.get("DEFAULT"))
    if profile is None:
        return []
    bounds = [profile.get(f"zone{i}Floor") for i in range(1, 6)]
    bounds.append(profile.get("maxHeartRateUsed"))
    if any(type(value) is not int or not 30 <= value <= 240 for value in bounds):
        return []
    if any(a >= b for a, b in zip(bounds, bounds[1:], strict=False)):
        return []
    return [
        GarminHeartRateZone(zone=i + 1, lower_bpm=bounds[i], upper_bpm=bounds[i + 1])
        for i in range(5)
    ]


def tag(workout: Workout) -> str:
    return f"stride-coach:v1:{workout.id}"


def workout_payload(workout: Workout) -> dict[str, Any]:
    order = 0

    def encode(step: Step | RepeatGroup) -> dict:
        nonlocal order
        order += 1
        index = order
        if isinstance(step, RepeatGroup):
            return {
                "type": "RepeatGroupDTO",
                "stepOrder": index,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                "numberOfIterations": step.repetitions,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": step.repetitions,
                "skipLastRestStep": step.skip_last_rest,
                "smartRepeat": False,
                "workoutSteps": [encode(child) for child in step.steps],
            }
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
            "description": step_description(step),
            "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key},
            "endCondition": {
                "conditionTypeId": {"time": 2, "distance": 3, "lap": 1}[step.end_condition],
                "conditionTypeKey": "lap.button"
                if step.end_condition == "lap"
                else step.end_condition,
            },
        }
        if step.end_condition != "lap":
            record["endConditionValue"] = round(
                step.distance_m if step.end_condition == "distance" else step.minutes * 60, 3
            )
        if step.cadence_min is not None:
            record.update(
                secondaryTargetType={"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence"},
                secondaryTargetValueOne=step.cadence_min,
                secondaryTargetValueTwo=step.cadence_max,
            )
        if step.hr_zone is not None:
            record.update(
                targetType={"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
                zoneNumber=step.hr_zone,
            )
        elif step.pace_min is not None:
            record.update(
                targetType={"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
                targetValueOne=1000 / step.pace_max,
                targetValueTwo=1000 / step.pace_min,
            )
        elif step.hr_min is not None:
            record.update(
                targetType={"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
                targetValueOne=step.hr_min,
                targetValueTwo=step.hr_max,
            )
        else:
            record["targetType"] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
        return record

    steps = [encode(step) for step in workout.steps]
    return {
        "workoutName": workout_name(workout),
        "description": f"{workout_description(workout)}\n{tag(workout)}",
        "sportType": SPORT,
        "estimatedDurationInSecs": round(workout.minutes * 60),
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT, "workoutSteps": steps}],
    }


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def pending(store: Store, key: str, state: bool | None = None) -> bool:
    return store.pending(key, state)


def has_tag(record: dict, workout: Workout) -> bool:
    description = record.get("description")
    return isinstance(description, str) and tag(workout) in description.splitlines()


def workout_inventory(client) -> list[dict]:
    return [
        record if record.get("description") else client.workout(str(record["workoutId"]))
        for record in client.workouts()
    ]


def owned_remote(client, inventory: list[dict], workout: Workout) -> dict | None:
    # A name is only a discovery hint; an exact tag line authorizes ownership.
    candidates = [
        r
        for r in inventory
        if (r.get("workoutName") or "").startswith(f"SC {workout.id} ") or has_tag(r, workout)
    ]
    owned = [client.workout(str(r["workoutId"])) for r in candidates]
    owned = [r for r in owned if has_tag(r, workout)]
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
        inventory = workout_inventory(client)
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
        inventory = workout_inventory(client)
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
                inventory = [r for r in inventory if str(r["workoutId"]) != remote_id]
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
