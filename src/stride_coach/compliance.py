"""Conservative lap-to-step scoring. Ambiguous alignment is unavailable, not failure."""

from .activity_models import RunCompliance, RunLap, StepCompliance
from .models import Workout


def score_steps(workout: Workout, laps: list[RunLap]) -> RunCompliance:
    groups = [laps] if len(workout.steps) == 1 and laps else [[lap] for lap in laps]
    aligned = bool(laps) and len(groups) == len(workout.steps)
    if aligned and len(workout.steps) > 1:
        aligned = all(
            0.9 * step.minutes * 60 <= lap.duration_s <= 1.1 * step.minutes * 60
            for step, lap in zip(workout.steps, laps, strict=True)
        )
    results = []
    for position, step in enumerate(workout.steps):
        result = StepCompliance(
            position=position, label=step.label, planned_seconds=step.minutes * 60
        )
        if not aligned:
            result.missing = "Step alignment unverified: laps do not establish planned boundaries."
        else:
            group = groups[position]
            duration = sum(lap.duration_s for lap in group)
            result.actual_seconds = duration
            result.duration_in_range = (
                0.9 * result.planned_seconds <= duration <= 1.1 * result.planned_seconds
            )
            if step.pace_min is not None and step.pace_max is not None:
                result.target = "pace"
                paces = [
                    lap.average_pace_s_km
                    if lap.average_pace_s_km is not None
                    else lap.duration_s * 1000 / lap.distance_m
                    if lap.distance_m > 0 and lap.duration_s > 0
                    else None
                    for lap in group
                ]
                if all(pace is not None for pace in paces) and duration > 0:
                    # Fraction of recorded time whose lap-average target was met.
                    result.target_score = (
                        100
                        * sum(
                            lap.duration_s
                            for lap, pace in zip(group, paces, strict=True)
                            if step.pace_min <= pace <= step.pace_max
                        )
                        / duration
                    )
            elif step.hr_min is not None and step.hr_max is not None:
                result.target = "heart_rate"
                if (
                    all(lap.average_hr is not None and lap.average_hr > 0 for lap in group)
                    and duration > 0
                ):
                    result.target_score = (
                        100
                        * sum(
                            lap.duration_s
                            for lap in group
                            if step.hr_min <= lap.average_hr <= step.hr_max
                        )
                        / duration
                    )
            if result.target_score is None:
                result.missing = "Target or recorded pace/heart rate unavailable."
            else:
                result.target_score = round(min(100, result.target_score), 6)
                result.score = (100 * result.duration_in_range + result.target_score) / 2
        results.append(result)
    known = [r.score for r in results if r.score is not None]
    return RunCompliance(
        workout_id=workout.id,
        score=sum(known) / len(known) if known else None,
        scored_steps=len(known),
        missing_steps=len(results) - len(known),
        steps=results,
    )
