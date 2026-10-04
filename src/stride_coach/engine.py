"""Pure, deterministic planning rules. See docs/training-rules.md."""

import hashlib
import math
from datetime import timedelta
from statistics import median

from .models import Activity, Fitness, Goal, Kind, Plan, RepeatGroup, Setup, Step, Workout, executable_steps


def vdot(distance_km: float, minutes: float) -> float:
    if distance_km <= 0 or minutes <= 0:
        raise ValueError("Distance and duration must be positive")
    speed = distance_km * 1000 / minutes
    oxygen = -4.60 + 0.182258 * speed + 0.000104 * speed**2
    fraction = 0.8 + 0.1894393 * math.exp(-0.012778 * minutes)
    fraction += 0.2989558 * math.exp(-0.1932605 * minutes)
    return oxygen / fraction


def estimate_fitness(runs: list[Activity], setup: Setup) -> Fitness:
    recent = [a for a in runs if a.sport == "running" and 0 < (setup.start - a.day).days <= 28]
    # Include empty weeks, so one recent long run does not imply a busy baseline.
    volume = sum(a.duration_min for a in recent) / 4
    efforts = [
        vdot(a.distance_km, a.duration_min)
        for a in recent
        if a.best_effort and a.distance_km >= 3 and a.duration_min >= 12
    ]
    efforts = [v for v in efforts if 15 <= v <= 85]
    if efforts:
        score = max(efforts) * 0.97
        # Solve the oxygen-cost polynomial at 65% VDOT for easy running speed.
        speed = (-0.182258 + math.sqrt(0.182258**2 + 4 * 0.000104 * (4.60 + 0.65 * score))) / (
            2 * 0.000104
        )
        return Fitness(
            vdot=round(score, 1),
            easy_pace=round(60000 / speed),
            weekly_minutes=volume,
            source="recent marked best effort, 3% margin",
        )
    paces = [a.duration_min * 60 / a.distance_km for a in recent if a.distance_km >= 2]
    pace = max(420, median(paces) * 1.1) if len(paces) >= 3 else None
    return Fitness(
        vdot=None,
        easy_pace=pace,
        weekly_minutes=volume,
        source="conservative recent easy pace" if pace else "thin history: HR targets",
    )


def training_days(count: int, long_day: int) -> list[int]:
    # Spread relative to long run and put quality away from the long run.
    offsets = {2: [0, 3], 3: [0, 2, 4], 4: [0, 2, 4, 5], 5: [0, 1, 2, 4, 5], 6: [0, 1, 2, 3, 4, 5]}
    return sorted((long_day + offset) % 7 for offset in offsets[count])


def make_steps(kind: Kind, minutes: float, fitness: Fitness, setup: Setup, week: int) -> list[Step | RepeatGroup]:
    def step(label: str, duration: float, effort: str = "easy") -> Step:
        bands = {
            "easy": (0.60, 0.72),
            "recovery": (0.50, 0.65),
            "tempo": (0.78, 0.87),
            "intervals": (0.85, 0.93),
            "walk": (0.35, 0.55),
        }
        lo, hi = bands[effort]
        athlete = setup.athlete
        reserve = athlete.max_hr - athlete.resting_hr
        kwargs = {
            "hr_min": round(athlete.resting_hr + lo * reserve),
            "hr_max": round(athlete.resting_hr + hi * reserve),
        }
        if fitness.easy_pace and effort in ("tempo", "intervals"):
            ratio = {"easy": 1, "recovery": 1.08, "tempo": 0.83, "intervals": 0.75}[effort]
            center = fitness.easy_pace * ratio * 1.01
            half_spread = max(10, fitness.easy_pace * ratio * 0.05)
            kwargs = {
                "pace_min": max(1, math.floor(center - half_spread)),
                "pace_max": math.ceil(center + half_spread),
            }
        elif effort in ("easy", "recovery"):
            kwargs["preferred_hr_zone"] = 1 if effort == "recovery" else 2
        return Step(label=label, minutes=duration, **kwargs)

    if kind == Kind.RUN_WALK:
        # Increase run fraction slowly: 8% time growth times 1% stays below 10%.
        fraction = min(0.7, 0.33 * 1.01 ** (week - 1))
        return [RepeatGroup(label="Run / walk", repetitions=6, steps=[
            step("Run gently", minutes / 6 * fraction),
            step("Walk", minutes / 6 * (1 - fraction), "walk"),
        ])]
    if kind in (Kind.TEMPO, Kind.INTERVALS):
        if kind == Kind.TEMPO:
            main = step("Steady tempo", minutes * 0.5, "tempo")
        else:
            work = step("Controlled interval", minutes * 0.08, "intervals")
            recovery = step("Easy recovery", minutes * 0.045, "recovery")
            if fitness.easy_pace:
                for part, pace in [(work, fitness.easy_pace * 0.75),
                                   (recovery, fitness.easy_pace * 1.08)]:
                    distance = math.floor(part.minutes * 60000 / pace / 100) * 100
                    if distance >= 100:
                        part.end_condition = "distance"
                        part.distance_m = distance
                        part.minutes = distance * pace / 60000
            main = RepeatGroup(label="Intervals", repetitions=4, skip_last_rest=True, steps=[work, recovery])
        remainder = (minutes - main.minutes) / 2
        warmup, cooldown = step("Warm up", remainder), step("Cool down", remainder)
        warmup.end_condition = cooldown.end_condition = "lap"
        return [warmup, main, cooldown]
    if kind == Kind.EASY and minutes >= 20 and fitness.easy_pace:
        # Reallocate four minutes, preserving the existing weekly time budget.
        return [step("Easy", minutes - 4), RepeatGroup(label="Strides", repetitions=4,
            steps=[step("Relaxed stride", 1 / 3, "intervals"),
                   step("Easy recovery", 2 / 3, "recovery")])]
    return [step(kind.value.title(), minutes, "recovery" if kind == Kind.RECOVERY else "easy")]


def generate_plan(setup: Setup, runs: list[Activity]) -> Plan:
    fitness = estimate_fitness(runs, setup)
    cadences = [a.metrics.average_cadence_spm for a in runs
                if a.sport == "running" and 0 < (setup.start - a.day).days <= 28
                and a.metrics and a.metrics.average_cadence_spm
                and 100 <= a.metrics.average_cadence_spm <= 230]
    cadence = round(median(cadences)) if len(cadences) >= 3 else None
    plan_id = hashlib.sha256(setup.model_dump_json().encode()).hexdigest()[:16]
    weeks = math.ceil((setup.race_date - setup.start).days / 7)
    taper = 3 if setup.goal == Goal.MARATHON else 2
    base = max(2, int(weeks * 0.3))
    baseline = fitness.weekly_minutes
    volume = min(60, baseline) if setup.goal == Goal.RETURN and baseline else baseline
    if not volume:
        volume = 20 * setup.days_per_week
    volume = min(volume, 360)
    caps = {Goal.FIVE_K: 240, Goal.TEN_K: 300, Goal.HALF: 360, Goal.MARATHON: 480, Goal.RETURN: 120}
    workouts = []
    days = training_days(setup.days_per_week, setup.long_run_day)
    quality_day = (setup.long_run_day + 4) % 7
    warnings = []
    if fitness.vdot is None:
        warnings.append("No recent marked best effort: targets use a conservative fallback.")
    if setup.goal in (Goal.HALF, Goal.MARATHON) and baseline < 120:
        warnings.append("Limited recent volume: this plan does not establish race readiness.")
    for index in range(weeks):
        week = index + 1
        phase = (
            "taper"
            if index >= weeks - taper
            else "base"
            if index < base
            else "peak"
            if index >= weeks - taper - 2
            else "build"
        )
        cutback = week % 4 == 0 and phase != "taper"
        if index:
            volume *= 0.75 if phase == "taper" else 0.85 if cutback else 1.08
        volume = min(volume, caps[setup.goal])
        # With two days, avoid concentrating most of the week into one run.
        long_share = 0.5 if setup.days_per_week == 2 else 1 / setup.days_per_week + 0.10
        for day in days:
            when = setup.start + timedelta(days=index * 7 + day)
            if when >= setup.race_date:
                continue
            kind = Kind.EASY
            share = (1 - long_share) / (setup.days_per_week - 1)
            if day == setup.long_run_day:
                kind, share = Kind.LONG, long_share
            elif day == quality_day and phase in ("build", "peak") and not cutback:
                if setup.days_per_week >= 3 and baseline >= 90:
                    kind = Kind.TEMPO if week % 2 else Kind.INTERVALS
            elif (day - setup.long_run_day) % 7 == 1:
                kind = Kind.RECOVERY
            if setup.goal == Goal.RETURN:
                kind, share = Kind.RUN_WALK, 1 / setup.days_per_week
            minutes = volume * share
            steps = make_steps(kind, minutes, fitness, setup, week)
            if cadence is not None:
                for step in executable_steps(steps):
                    if step.label == "Relaxed stride":
                        step.cadence_min, step.cadence_max = cadence - 10, cadence + 10
            workouts.append(
                Workout(
                    id=f"{plan_id}-{when.isoformat()}",
                    day=when,
                    week=week,
                    phase=phase,
                    kind=kind,
                    cutback=cutback,
                    steps=steps,
                )
            )
    return Plan(id=plan_id, setup=setup, fitness=fitness, workouts=workouts, warnings=warnings)
