"""Server-owned Garmin adapter and recoverable, explicitly requested writes."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .garmin_auth import AUTH_ERROR, GarminError, StoredSession, TokenVault
from .models import Activity, Workout
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
            "description": step_description(step),
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


def reconcile_cached_remote(store: Store, workout_id: str, inventory: list[dict], events: list[dict]):
    cached = store.scheduled(workout_id)
    if not cached or pending(store, f"create:{workout_id}"):
        return cached
    remote_id = cached["remote_id"]
    if any(str(item["workoutId"]) == remote_id for item in inventory) or any(
        item.get("itemType") == "workout" and str(item.get("workoutId")) == remote_id
        for item in events
    ):
        return cached
    store.forget_remote(workout_id)
    pending(store, f"schedule:{workout_id}", False)
    return None


def push(
    store: Store,
    workouts: list[Workout],
    client=None,
    dry_run: bool = True,
    *,
    inventory: list[dict] | None = None,
) -> list[dict]:
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
        inventory = workout_inventory(client) if inventory is None else list(inventory)
        for workout in workouts:
            payload = workout_payload(workout)
            digest = fingerprint(payload)
            remote = owned_remote(client, inventory, workout)
            calendar = client.calendar(workout.day)
            cached = reconcile_cached_remote(store, workout.id, inventory, calendar)
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
        store.calendar_synced(None)
        inventory = workout_inventory(client)
        for workout in workouts:
            remote = owned_remote(client, inventory, workout)
            if remote:
                remote_id = str(remote["workoutId"])
                delete_owned(store, client, remote, workout.id, client.calendar(workout.day))
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


def calendar_fingerprint(store: Store, today: date) -> str:
    return fingerprint(
        {
            "plan": store.plan().model_dump(mode="json"),
            "today": today.isoformat(),
            "days": store.calendar_settings()["window_days"],
        }
    )


def delete_owned(store: Store, client, remote: dict, workout_id: str, events: list[dict]):
    """Share deletion mechanics while treating a fresh detail tag as authority."""
    remote_id = str(remote["workoutId"])
    detail = client.workout(remote_id)
    if detail.get("description") != f"stride-coach:v1:{workout_id}":
        raise GarminError("Workout ownership changed. Preview Garmin changes again.")
    for item in events:
        if item.get("itemType") == "workout" and str(item.get("workoutId")) == remote_id:
            client.unschedule(str(item["id"]))
    client.delete(remote_id)
    store.forget_remote(workout_id)
    pending(store, f"create:{workout_id}", False)
    pending(store, f"schedule:{workout_id}", False)


def reconcile_calendar(store: Store, client, today: date, *, apply=False, preview_id=None):
    """Read remote inventory for a bounded plan, then apply only a confirmed snapshot."""
    import re
    from datetime import timedelta

    from .adaptation import match_activities

    with store.lock():
        plan = store.plan()
        days = store.calendar_settings()["window_days"]
        end = today + timedelta(days=days)
        desired = [w for w in plan.workouts if today <= w.day < end]
        by_id = {w.id: w for w in plan.workouts}
        activities = store.activities()
        completed = {m["workout_id"] for m in match_activities(plan, activities)}
        inventory = client.workouts()
        owned = {}
        dates = {w.day for w in plan.workouts} | {today, end}
        # Inventory summaries may omit descriptions. Detail is the only authority,
        # including old or renamed workouts that are no longer in the local plan.
        for item in inventory:
            remote = client.workout(str(item["workoutId"]))
            match = re.fullmatch(r"stride-coach:v1:(.+)", remote.get("description") or "")
            if not match:
                continue
            workout_id = match[1]
            if workout_id in owned:
                raise GarminError(
                    "Multiple workouts share an ownership tag; resolve duplicates in Garmin."
                )
            owned[workout_id] = remote
            try:
                dates.add(date.fromisoformat(workout_id[-10:]))
            except ValueError:
                pass
        events = {}
        for year, month in sorted({(d.year, d.month) for d in dates}):
            for item in client.calendar(date(year, month, 1)):
                if item.get("itemType") == "workout":
                    events[str(item["id"])] = item
        for workout in plan.workouts:
            reconcile_cached_remote(store, workout.id, inventory, list(events.values()))
        changes = []
        for workout in desired:
            remote = owned.get(workout.id)
            payload = workout_payload(workout)
            cached = store.scheduled(workout.id)
            remote_id = str(remote["workoutId"]) if remote else None
            scheduled = any(
                str(e.get("workoutId")) == remote_id and e.get("date") == workout.day.isoformat()
                for e in events.values()
            )
            if not remote:
                if cached or pending(store, f"create:{workout.id}"):
                    raise GarminError(
                        "Previous upload is unresolved. Inspect Garmin before retrying."
                    )
                action = "create"
            elif not cached or cached["fingerprint"] != fingerprint(payload):
                action = "update"
            elif not scheduled:
                action = "schedule"
            else:
                continue
            if (
                remote
                and not scheduled
                and (pending(store, f"schedule:{workout.id}") or (cached and cached["scheduled"]))
            ):
                raise GarminError(
                    "Previous calendar write is unresolved. Inspect Garmin before retrying."
                )
            changes.append(
                {
                    "action": action,
                    "workout_id": workout.id,
                    "remote_id": remote_id,
                    "date": workout.day.isoformat(),
                    "payload": payload,
                }
            )
        for workout_id, remote in owned.items():
            workout = by_id.get(workout_id)
            scheduled_events = [
                e for e in events.values() if str(e.get("workoutId")) == str(remote["workoutId"])
            ]
            past = [e for e in scheduled_events if str(e.get("date", "")) < today.isoformat()]
            reason = None
            if workout is None:
                reason = "No longer in the plan"
            elif workout.day >= end:
                reason = "Outside the Garmin window"
            elif workout.day < today and workout_id not in completed:
                # A missing local activity alone is not proof of non-completion.
                coverage = store.sync_window(complete=True)
                missed_dates = {workout.day.isoformat()} | {e["date"] for e in past}
                if coverage and all(
                    coverage["since"] <= day <= coverage["until"] for day in missed_dates
                ):
                    reason = "Past workout without a completed run in synced history"
            if reason:
                changes.append(
                    {
                        "action": "remove",
                        "workout_id": workout_id,
                        "remote_id": str(remote["workoutId"]),
                        "ownership_tag": f"stride-coach:v1:{workout_id}",
                        "date": workout.day.isoformat() if workout else None,
                        "reason": reason,
                    }
                )
        changes.sort(key=lambda c: (c["workout_id"], c["action"]))
        digest = calendar_fingerprint(store, today)
        snapshot = fingerprint(
            {
                "plan": digest,
                "changes": changes,
                "owned": owned,
                "events": sorted(events.values(), key=lambda e: str(e["id"])),
            }
        )
        if apply:
            if not preview_id or preview_id != snapshot:
                raise ValueError("Garmin preview changed or is missing. Preview and confirm again.")
            store.calendar_synced(None)
            for change in changes:
                if change["action"] == "remove":
                    delete_owned(
                        store,
                        client,
                        owned[change["workout_id"]],
                        change["workout_id"],
                        list(events.values()),
                    )
                    del owned[change["workout_id"]]
            # The existing push path retains durable create/schedule recovery guards.
            changed_ids = {c["workout_id"] for c in changes if c["action"] != "remove"}
            push(
                store,
                [w for w in desired if w.id in changed_ids],
                client,
                dry_run=False,
                inventory=list(owned.values()),
            )
            store.calendar_synced(digest)
        return {
            "window_days": days,
            "since": today,
            "until": end - timedelta(days=1),
            "preview_id": snapshot,
            "applied": apply,
            "changes": changes,
        }
