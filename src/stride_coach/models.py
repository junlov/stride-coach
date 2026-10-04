"""Validated local records. Durations are minutes, distance km, pace seconds/km."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activity_models import CaptureStatus, HeartRateZone, RunLap, RunMetrics, RunStreams


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Goal(StrEnum):
    FIVE_K = "5k"
    TEN_K = "10k"
    HALF = "half"
    MARATHON = "marathon"
    RETURN = "return-to-running"


class Kind(StrEnum):
    EASY = "easy"
    LONG = "long"
    TEMPO = "tempo"
    INTERVALS = "intervals"
    RECOVERY = "recovery"
    RUN_WALK = "run-walk"


class Athlete(Record):
    resting_hr: int = Field(default=60, ge=30, le=120)
    max_hr: int = Field(default=190, ge=100, le=240)
    trimp_a: float = Field(default=0.64, gt=0, le=2)
    trimp_b: float = Field(default=1.92, gt=0, le=3)

    @model_validator(mode="after")
    def valid_hr(self):
        if self.max_hr <= self.resting_hr:
            raise ValueError("Maximum HR must exceed resting HR")
        return self


class ActivityCore(Record):
    id: str
    day: date
    distance_km: float = Field(ge=0, le=500)
    duration_min: float = Field(gt=0, le=3000)
    average_hr: float | None = Field(default=None, ge=30, le=240)
    sport: str = "running"
    kind: Kind | None = None
    best_effort: bool = False


class RunDetail(ActivityCore):
    metrics: RunMetrics | None = None
    raw_summary: dict | None = None
    laps: list[RunLap] | None = None
    splits: list[RunLap] | None = None
    hr_zones: list[HeartRateZone] | None = None
    capture: CaptureStatus | None = None


class Activity(RunDetail):
    streams: RunStreams | None = None
    source: str = "local"


class Setup(Record):
    goal: Goal
    start: date
    race_date: date
    days_per_week: int = Field(ge=2, le=6)
    long_run_day: int = Field(default=6, ge=0, le=6)
    athlete: Athlete = Field(default_factory=Athlete)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.start.weekday() != 0:
            raise ValueError("Plan start must be a Monday")
        if not 55 <= (self.race_date - self.start).days <= 365:
            raise ValueError("Choose a race/completion date 8 to 52 weeks after start")
        if self.goal == Goal.RETURN and self.days_per_week > 3:
            raise ValueError("Return to running supports 2 or 3 days for recovery spacing")
        return self


class Fitness(Record):
    vdot: float | None
    easy_pace: float | None
    weekly_minutes: float
    source: str


class Step(Record):
    label: str
    minutes: float = Field(gt=0)
    pace_min: float | None = Field(default=None, gt=0)
    pace_max: float | None = Field(default=None, gt=0)
    hr_min: int | None = Field(default=None, gt=0)
    hr_max: int | None = Field(default=None, gt=0)


class Workout(Record):
    id: str
    day: date
    week: int
    phase: str
    kind: Kind
    steps: list[Step]
    cutback: bool = False

    @property
    def minutes(self) -> float:
        return sum(s.minutes for s in self.steps)


class Plan(Record):
    id: str
    setup: Setup
    fitness: Fitness
    workouts: list[Workout]
    warnings: list[str] = Field(default_factory=list)


class Adjustment(Record):
    week: int
    factor: float
    reasons: list[str]
    before_minutes: float
    after_minutes: float
    applied: bool = False
