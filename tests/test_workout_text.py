from datetime import date

import pytest

from stride_coach.garmin import workout_payload
from stride_coach.models import Kind, Step, Workout
from stride_coach.workout_text import duration, step_description, workout_description, workout_name


@pytest.fixture(autouse=True)
def database():
    # These formatters need no database, matching the pure preview contract tests.
    return None


def session(kind, steps):
    return Workout(
        id="synthetic", day=date(2026, 10, 5), week=3, phase="build", kind=kind, steps=steps
    )


@pytest.mark.parametrize(
    "kind,minutes,name",
    [
        (Kind.EASY, 40, "Easy Run 40 min"),
        (Kind.LONG, 75, "Long Run 75 min"),
        (Kind.RECOVERY, 25, "Recovery 25 min"),
        (Kind.RUN_WALK, 30, "Run-Walk 30 min"),
    ],
)
def test_names(kind, minutes, name):
    assert workout_name(session(kind, [Step(label=kind.value.title(), minutes=minutes)])) == name


@pytest.mark.parametrize(
    "kind,label,name",
    [
        (Kind.TEMPO, "Steady tempo", "Tempo 3 x 8 min"),
        (Kind.INTERVALS, "Controlled interval", "Intervals 3x8m"),
    ],
)
def test_main_set_excludes_warmup_recovery_and_cooldown(kind, label, name):
    steps = [Step(label="Warm up", minutes=10)]
    for _ in range(3):
        steps += [Step(label=label, minutes=8), Step(label="Easy recovery", minutes=2)]
    steps += [Step(label="Cool down", minutes=5)]
    assert workout_name(session(kind, steps)) == name


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("minutes", [0.5, 2.75, 25, 75, 123.5, 100000000000000])
def test_name_limit(kind, minutes):
    workout = session(kind, [Step(label="Controlled interval", minutes=minutes)])
    name = workout_name(workout)
    assert 0 < len(name.encode("utf-8")) <= 15
    assert name == name.rstrip()
    assert "synthetic" not in name


def test_variable_main_set_and_missing_main():
    assert (
        workout_name(
            session(
                Kind.TEMPO,
                [
                    Step(label="Steady tempo", minutes=8),
                    Step(label="Steady tempo", minutes=5),
                ],
            )
        )
        == "Tempo 13 min"
    )
    assert workout_name(session(Kind.TEMPO, [Step(label="Run", minutes=10)])) == "Tempo 10 min"
    assert (
        workout_name(
            session(
                Kind.INTERVALS,
                [
                    Step(label="Controlled interval", minutes=123.5),
                ],
            )
        )
        == "Reps 123:30m"
    )


@pytest.mark.parametrize("minutes,expected", [(0.5, "30 sec"), (2, "2 min"), (2.75, "2:45 min")])
def test_duration(minutes, expected):
    assert duration(minutes) == expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Warm up", "Warm up easy for 8 min"),
        ("Cool down", "Cool down for 8 min"),
        ("Easy recovery", "8 min easy jog"),
        ("Walk", "8 min walk"),
        ("Run gently", "8 min gentle run"),
        ("Steady tempo", "8 min"),
    ],
)
def test_step_instructions_use_existing_target(label, expected):
    step = Step(label=label, minutes=8, pace_min=305, pace_max=315)
    assert step_description(step) == expected + " at 5:05 to 5:15 /km"
    step.pace_min = step.pace_max = None
    step.hr_min, step.hr_max = 130, 145
    assert step_description(step) == expected + " at 130 to 145 bpm"
    step.hr_min = step.hr_max = None
    assert step_description(step) == expected


def test_payload_snapshot():
    workout = session(Kind.EASY, [Step(label="Easy", minutes=40, hr_min=130, hr_max=145)])
    sport = {"sportTypeId": 1, "sportTypeKey": "running"}
    assert workout_payload(workout) == {
        "workoutName": "Easy Run 40 min",
        "description": "Build endurance at an easy effort where you can chat comfortably. "
        "Aim for 130 to 145 bpm during the running efforts.\nstride-coach:v1:synthetic",
        "sportType": sport,
        "estimatedDurationInSecs": 2400,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport,
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "description": "40 min easy run at 130 to 145 bpm",
                        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                        "endConditionValue": 2400,
                        "targetType": {
                            "workoutTargetTypeId": 4,
                            "workoutTargetTypeKey": "heart.rate.zone",
                        },
                        "targetValueOne": 130,
                        "targetValueTwo": 145,
                    }
                ],
            }
        ],
    }


def test_description_targets_for_run_walk_and_variable_efforts():
    workout = session(
        Kind.RUN_WALK,
        [
            Step(label="Run gently", minutes=2, pace_min=360, pace_max=400),
            Step(label="Walk", minutes=1, hr_min=100, hr_max=115),
        ],
    )
    assert "6:00 to 6:40 /km" in workout_description(workout)
    assert "100 to 115" not in workout_description(workout)
    workout.steps.append(Step(label="Run gently", minutes=2, pace_min=350, pace_max=390))
    assert "targets shown in each step" in workout_description(workout)
