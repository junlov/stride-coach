"""Explainable weekly adaptation; proposals have no side effects."""

import math
from datetime import date, timedelta

from .models import Activity, Adjustment, Athlete, Kind, Plan
from .storage import Store


def trimp(activity: Activity, athlete: Athlete) -> float | None:
    if activity.average_hr is None:
        return None
    reserve = max(
        0,
        min(1, (activity.average_hr - athlete.resting_hr) / (athlete.max_hr - athlete.resting_hr)),
    )
    return activity.duration_min * reserve * athlete.trimp_a * math.exp(athlete.trimp_b * reserve)


def match_activities(plan: Plan, activities: list[Activity]) -> list[dict]:
    matches, used = [], set()
    for workout in plan.workouts:
        candidates = [
            a
            for a in activities
            if a.id not in used
            and a.day == workout.day
            and a.sport == "running"
            and (a.kind is None or a.kind == workout.kind)
        ]
        if candidates:
            activity = min(
                candidates,
                key=lambda a: (a.kind is None, abs(a.duration_min - workout.minutes), a.id),
            )
            used.add(activity.id)
            matches.append(
                {
                    "workout_id": workout.id,
                    "activity_id": activity.id,
                    "method": "date+type" if activity.kind else "date+running (inferred)",
                }
            )
    return matches


def week_metrics(plan: Plan, activities: list[Activity], week: int) -> dict:
    workouts = [w for w in plan.workouts if w.week == week]
    ids = {w.id for w in workouts}
    matches = [m for m in match_activities(plan, activities) if m["workout_id"] in ids]
    start = plan.setup.start + timedelta(weeks=week - 1)
    runs = [
        a for a in activities if start <= a.day < start + timedelta(days=7) and a.sport == "running"
    ]
    loads = [trimp(a, plan.setup.athlete) for a in runs]
    return {
        "week": week,
        "planned_sessions": len(workouts),
        "matched_sessions": len(matches),
        "compliance": len(matches) / len(workouts) if workouts else 0,
        "planned_minutes": sum(w.minutes for w in workouts),
        "completed_minutes": sum(a.duration_min for a in runs),
        "trimp": round(sum(v for v in loads if v is not None), 2),
        "missing_hr": sum(v is None for v in loads),
        "matches": matches,
    }


def propose(plan: Plan, activities: list[Activity], week: int) -> Adjustment:
    current = week_metrics(plan, activities, week - 1)
    previous = week_metrics(plan, activities, week - 2)
    upcoming = [w for w in plan.workouts if w.week == week]
    if week < 2 or not upcoming:
        raise ValueError("Choose an existing week after week 1")
    before = sum(w.minutes for w in upcoming)
    factor, reasons = 1.0, []
    if current["compliance"] < 0.5:
        factor = 0.75
        reasons.append("Less than half of last week's sessions completed: reduce 25%.")
    elif current["compliance"] < 0.8:
        factor = 0.9
        reasons.append("Less than 80% compliance: reduce 10%.")
    elif current["compliance"] < 1:
        reasons.append("A session was missed: hold volume.")
        factor = min(factor, current["planned_minutes"] / before)
    if current["missing_hr"] or previous["missing_hr"]:
        reasons.append("Missing heart rate: load comparison is incomplete; hold volume.")
        factor = min(factor, current["planned_minutes"] / before)
    elif previous["trimp"] > 0 and current["trimp"] > 1.2 * previous["trimp"]:
        factor = min(factor, 0.85)
        reasons.append("Running TRIMP rose more than 20%: reduce 15%.")
    activities_by_id = {a.id: a for a in activities}
    workouts_by_id = {w.id: w for w in plan.workouts}
    hard, easy = 0, 0
    for match in current["matches"]:
        a, w = activities_by_id[match["activity_id"]], workouts_by_id[match["workout_id"]]
        # Whole-run averages cannot assess short interval or run-walk steps reliably.
        if w.kind not in (Kind.EASY, Kind.LONG, Kind.RECOVERY):
            continue
        target = w.steps[0]
        if target.hr_max and a.average_hr:
            hard += a.average_hr > target.hr_max + 8
            easy += a.average_hr < target.hr_min - 8
        elif target.pace_min and a.distance_km:
            pace = a.duration_min * 60 / a.distance_km
            hard += pace < target.pace_min * 0.9
            easy += pace > target.pace_max * 1.15
    if hard:
        factor = min(factor, 0.9)
        reasons.append("Easy running was substantially harder than target: reduce 10%.")
    if easy:
        factor = min(factor, current["planned_minutes"] / before)
        reasons.append("Running was substantially easier than target: hold and review targets.")
    if current["completed_minutes"] < current["planned_minutes"] * 0.7:
        factor = min(factor, 0.85)
        reasons.append("Completed duration below 70% of plan: reduce 15%.")
    factor = min(1, factor)
    if not reasons:
        reasons.append("Completion and load are within limits: retain the planned week.")
    return Adjustment(
        week=week,
        factor=factor,
        reasons=reasons,
        before_minutes=before,
        after_minutes=before * factor,
    )


def adapt(store: Store, week: int, today: date, apply: bool = False) -> Adjustment:
    with store.lock():
        existing = store.adjustment(week)
        if existing:
            return existing
        plan = store.plan()
        start = plan.setup.start + timedelta(weeks=week - 1)
        if start != today:
            raise ValueError("Adapt on the target week's Monday, after the previous week closes.")
        window = store.sync_window(complete=True)
        required_since = start - timedelta(days=14)
        if (
            not window
            or date.fromisoformat(window["since"]) > required_since
            or date.fromisoformat(window["until"]) < start - timedelta(days=1)
        ):
            raise ValueError("Sync the previous two complete weeks before adaptation.")
        adjustment = propose(plan, store.activities(), week)
        if apply:
            # Propagate the reduction so later weeks cannot jump back above the 10% cap.
            for workout in plan.workouts:
                if workout.week >= week:
                    for step in workout.steps:
                        step.minutes *= adjustment.factor
            store.apply(plan, adjustment)
        return adjustment
