"""Pure, deterministic planning rules. See docs/training-rules.md."""

import hashlib
import math
from datetime import timedelta
from statistics import median

from .models import Activity, Fitness, Goal, Kind, Plan, Setup, Step, Workout


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


def make_steps(kind: Kind, minutes: float, fitness: Fitness, setup: Setup, week: int) -> list[Step]:
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
        if fitness.easy_pace and effort != "walk":
            ratio = {"easy": 1, "recovery": 1.08, "tempo": 0.83, "intervals": 0.75}[effort]
            kwargs = {
                "pace_min": round(fitness.easy_pace * ratio * 0.96),
                "pace_max": round(fitness.easy_pace * ratio * 1.06),
            }
        return Step(label=label, minutes=duration, **kwargs)

    if kind == Kind.RUN_WALK:
        # Increase run fraction slowly: 8% time growth times 1% stays below 10%.
        fraction = min(0.7, 0.33 * 1.01 ** (week - 1))
        return [
            s
            for _ in range(6)
            for s in [
                step("Run gently", minutes / 6 * fraction),
                step("Walk", minutes / 6 * (1 - fraction), "walk"),
            ]
        ]
    if kind in (Kind.TEMPO, Kind.INTERVALS):
        steps = [step("Warm up", minutes * 0.25)]
        if kind == Kind.TEMPO:
            steps.append(step("Steady tempo", minutes * 0.5, "tempo"))
        else:
            for _ in range(4):
                steps.extend(
                    [
                        step("Controlled interval", minutes * 0.08, "intervals"),
                        step("Easy recovery", minutes * 0.045, "recovery"),
                    ]
                )
        return steps + [step("Cool down", minutes * 0.25)]
    return [step(kind.value.title(), minutes, "recovery" if kind == Kind.RECOVERY else "easy")]


def generate_plan(setup: Setup, runs: list[Activity]) -> Plan:
    fitness = estimate_fitness(runs, setup)
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
            workouts.append(
                Workout(
                    id=f"{plan_id}-{when.isoformat()}",
                    day=when,
                    week=week,
                    phase=phase,
                    kind=kind,
                    cutback=cutback,
                    steps=make_steps(kind, minutes, fitness, setup, week),
                )
            )
    return Plan(id=plan_id, setup=setup, fitness=fitness, workouts=workouts, warnings=warnings)
