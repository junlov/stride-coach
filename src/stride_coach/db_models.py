"""PostgreSQL records. Core coaching fields never use serialized JSON."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .models import Goal, Kind


class StepKind(StrEnum):
    WARMUP = "warmup"
    COOLDOWN = "cooldown"
    RECOVERY = "recovery"
    INTERVAL = "interval"


class WriteOperation(StrEnum):
    CREATE = "create"
    SCHEDULE = "schedule"


def enum_type(kind, name):
    return Enum(kind, name=name, values_callable=lambda values: [v.value for v in values])


class FloatNumeric(TypeDecorator):
    """Send decimal text rather than a server-side float cast, preserving Python round trips."""

    impl = Numeric
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return Decimal(str(value)) if value is not None else None

    def process_result_value(self, value, dialect):
        return float(value) if value is not None else None


class Base(DeclarativeBase):
    type_annotation_map = {float: FloatNumeric(), list[str]: ARRAY(Text)}


class PlanRow(Base):
    __tablename__ = "plans"
    __table_args__ = (CheckConstraint("singleton", name="single_active_plan"),)
    id: Mapped[str] = mapped_column(primary_key=True)
    singleton: Mapped[bool] = mapped_column(Boolean, unique=True, default=True)
    goal: Mapped[Goal] = mapped_column(enum_type(Goal, "goal_kind"))
    start: Mapped[date]
    race_date: Mapped[date]
    days_per_week: Mapped[int]
    long_run_day: Mapped[int]
    resting_hr: Mapped[int]
    max_hr: Mapped[int]
    trimp_a: Mapped[float]
    trimp_b: Mapped[float]
    vdot: Mapped[float | None]
    easy_pace: Mapped[float | None]
    weekly_minutes: Mapped[float]
    fitness_source: Mapped[str]
    warnings: Mapped[list[str]]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeekRow(Base):
    __tablename__ = "weeks"
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    __table_args__ = (CheckConstraint("number > 0", name="positive_week"),)


class WorkoutRow(Base):
    __tablename__ = "workouts"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "week"], ["weeks.plan_id", "weeks.number"]),
        UniqueConstraint("plan_id", "position"),
    )
    id: Mapped[str] = mapped_column(primary_key=True)
    plan_id: Mapped[str]
    week: Mapped[int]
    position: Mapped[int]
    day: Mapped[date] = mapped_column(index=True)
    phase: Mapped[str]
    kind: Mapped[Kind] = mapped_column(enum_type(Kind, "session_kind"))
    cutback: Mapped[bool]


class StepRow(Base):
    __tablename__ = "steps"
    __table_args__ = (CheckConstraint("minutes > 0", name="positive_step_minutes"),)
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[StepKind] = mapped_column(enum_type(StepKind, "step_kind"))
    label: Mapped[str]
    minutes: Mapped[float]
    pace_min: Mapped[float | None]
    pace_max: Mapped[float | None]
    hr_min: Mapped[int | None]
    hr_max: Mapped[int | None]


class ActivityRow(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("distance_km >= 0 AND duration_min > 0", name="activity_measurements"),
    )
    id: Mapped[str] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    distance_km: Mapped[float]
    duration_min: Mapped[float]
    average_hr: Mapped[float | None]
    sport: Mapped[str]
    kind: Mapped[Kind | None] = mapped_column(enum_type(Kind, "session_kind"))
    best_effort: Mapped[bool]


class MatchRow(Base):
    __tablename__ = "matches"
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), unique=True
    )
    method: Mapped[str]


class AdjustmentRow(Base):
    __tablename__ = "adjustments"
    __table_args__ = (ForeignKeyConstraint(["plan_id", "week"], ["weeks.plan_id", "weeks.number"]),)
    plan_id: Mapped[str] = mapped_column(primary_key=True)
    week: Mapped[int] = mapped_column(primary_key=True)
    factor: Mapped[float]
    reasons: Mapped[list[str]]
    before_minutes: Mapped[float]
    after_minutes: Mapped[float]
    applied: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduledRow(Base):
    __tablename__ = "scheduled"
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    remote_id: Mapped[str] = mapped_column(index=True)
    fingerprint: Mapped[str]
    scheduled: Mapped[bool]


class WriteIntentRow(Base):
    __tablename__ = "write_intents"
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    operation: Mapped[WriteOperation] = mapped_column(
        enum_type(WriteOperation, "write_operation"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataRow(Base):
    __tablename__ = "metadata"
    __table_args__ = (
        CheckConstraint("key IN ('sync', 'sync_complete')", name="coverage_key"),
        CheckConstraint(
            "(since IS NULL AND until IS NULL) OR "
            "(since IS NOT NULL AND until IS NOT NULL AND since <= until)",
            name="coverage_dates",
        ),
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    since: Mapped[date | None]
    until: Mapped[date | None]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
