from datetime import date

import pytest

from stride_coach.activity_models import RunLap
from stride_coach.compliance import score_steps
from stride_coach.models import Kind, Step, Workout


@pytest.fixture(autouse=True)
def database():
    yield


@pytest.mark.parametrize(
    "seconds,aligned",
    [
        ([780, 840, 780], False),
        ([600, 600, 600], False),
        ([600, 1200, 661], False),
        ([600, 1200, 600], True),
        ([540, 1320, 660], True),
    ],
)
def test_multistep_alignment_requires_consistent_durations(seconds, aligned):
    workout = Workout(
        id="tempo",
        day=date(2026, 10, 5),
        week=1,
        phase="build",
        kind=Kind.TEMPO,
        steps=[
            Step(label=label, minutes=minutes, hr_min=120, hr_max=140)
            for label, minutes in [("Warm up", 10), ("Tempo", 20), ("Cool down", 10)]
        ],
    )
    result = score_steps(
        workout,
        [RunLap(duration_s=value, distance_m=1000, average_hr=150) for value in seconds],
    )
    if aligned:
        assert result.scored_steps == 3
        assert result.score == 50
        assert all(step.duration_in_range is True for step in result.steps)
        assert all(step.target_score == 0 for step in result.steps)
    else:
        assert result.scored_steps == 0
        assert result.missing_steps == 3
        assert result.score is None
        for step in result.steps:
            assert step.actual_seconds is None
            assert step.duration_in_range is None
            assert step.target_score is None
            assert step.score is None
            assert "alignment unverified" in step.missing
