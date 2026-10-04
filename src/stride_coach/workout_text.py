"""Runner-facing text shared by Garmin payloads and API views."""

from .models import Kind, Step, Workout

# Garmin support documents a 15-character limit on many devices. The Python
# client's workoutName string has no length validation. See docs/garmin-workouts.md.
WORKOUT_NAME_LIMIT = 15

_NAMES = {
    Kind.EASY: "Easy Run",
    Kind.LONG: "Long Run",
    Kind.TEMPO: "Tempo",
    Kind.INTERVALS: "Intervals",
    Kind.RECOVERY: "Recovery Jog",
    Kind.RUN_WALK: "Run-Walk",
}
_PURPOSE = {
    Kind.EASY: "Build endurance at an easy effort where you can chat comfortably.",
    Kind.LONG: "Build staying power with a relaxed, conversational effort throughout.",
    Kind.TEMPO: "Practice a steady, comfortably hard effort that stays controlled.",
    Kind.INTERVALS: "Practice faster running with controlled efforts and easy recoveries.",
    Kind.RECOVERY: "Keep your legs moving with a gentle jog that feels very easy.",
    Kind.RUN_WALK: "Build running time gently, alternating relaxed running with walking breaks.",
}


def duration(minutes: float) -> str:
    seconds = max(1, round(minutes * 60))
    whole, remainder = divmod(seconds, 60)
    if not whole:
        return f"{remainder} sec"
    if not remainder:
        return f"{whole} min"
    return f"{whole}:{remainder:02d} min"


def main_steps(workout: Workout) -> list[Step]:
    labels = {Kind.TEMPO: "steady tempo", Kind.INTERVALS: "controlled interval"}
    if workout.kind in labels:
        return [s for s in workout.steps if s.label.lower() == labels[workout.kind]]
    if workout.kind == Kind.RUN_WALK:
        return [s for s in workout.steps if s.label.lower() == "run gently"]
    return workout.steps


def workout_name(workout: Workout) -> str:
    main = main_steps(workout)
    summary = duration(workout.minutes)
    if workout.kind in (Kind.TEMPO, Kind.INTERVALS) and main:
        if len({round(s.minutes * 60) for s in main}) == 1:
            summary = duration(main[0].minutes)
            if len(main) > 1:
                summary = f"{len(main)} x {summary}"
        else:
            summary = duration(sum(s.minutes for s in main))
    name = f"{_NAMES[workout.kind]} {summary}"
    if len(name) > WORKOUT_NAME_LIMIT:
        name = name.replace("Recovery Jog", "Recovery")
    if len(name) > WORKOUT_NAME_LIMIT:
        name = name.replace(" x ", "x").replace(" min", "m").replace(" sec", "s")
    if len(name) > WORKOUT_NAME_LIMIT:
        name = name.replace("Intervals", "Reps")
    # Only ASCII text is generated, so this also respects byte-based limits.
    return name[:WORKOUT_NAME_LIMIT].rstrip()


def target_text(step: Step) -> str:
    if step.pace_min is not None and step.pace_max is not None:

        def pace(seconds: float) -> str:
            minutes, remainder = divmod(round(seconds), 60)
            return f"{minutes}:{remainder:02d}"

        return f"{pace(step.pace_min)} to {pace(step.pace_max)} /km"
    if step.hr_min is not None and step.hr_max is not None:
        return f"{step.hr_min} to {step.hr_max} bpm"
    return ""


def step_description(step: Step) -> str:
    label = step.label.lower()
    instruction = {
        "warm up": "Warm up easy",
        "cool down": "Cool down",
        "easy recovery": "easy jog",
        "recovery": "easy jog",
        "walk": "walk",
        "run gently": "gentle run",
        "easy": "easy run",
        "long": "easy run",
    }.get(label, "")
    if label in ("warm up", "cool down"):
        text = f"{instruction} for {duration(step.minutes)}"
    else:
        text = f"{duration(step.minutes)} {instruction}".rstrip()
    target = target_text(step)
    return f"{text} at {target}" if target else text


def workout_description(workout: Workout) -> str:
    main = main_steps(workout)
    targets = list(dict.fromkeys(target_text(s) for s in main if target_text(s)))
    text = _PURPOSE[workout.kind]
    if targets:
        # Avoid a long list for variable sets; each step still carries its own target.
        target = targets[0] if len(targets) == 1 else "the targets shown in each step"
        text += f" Aim for {target} during the running efforts."
    return text
