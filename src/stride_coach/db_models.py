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
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    UNSCHEDULE = "unschedule"


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
    end_condition: Mapped[str] = mapped_column(default="time", server_default="time")
    distance_m: Mapped[float | None]
    preferred_hr_zone: Mapped[int | None]
    hr_zone: Mapped[int | None]
    cadence_min: Mapped[int | None]
    cadence_max: Mapped[int | None]
    group_position: Mapped[int | None]


class RepeatRow(Base):
    __tablename__ = "step_repeats"
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]
    repetitions: Mapped[int]
    skip_last_rest: Mapped[bool]
    __table_args__ = (CheckConstraint("repetitions BETWEEN 2 AND 100"),)


class GarminZoneRow(Base):
    __tablename__ = "garmin_hr_zones"
    zone: Mapped[int] = mapped_column(primary_key=True)
    lower_bpm: Mapped[int]
    upper_bpm: Mapped[int]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class StepComplianceRow(Base):
    __tablename__ = "step_compliance"
    workout_id: Mapped[str] = mapped_column(
        ForeignKey("matches.workout_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]
    planned_seconds: Mapped[float]
    actual_seconds: Mapped[float | None]
    duration_in_range: Mapped[bool | None]
    target: Mapped[str | None]
    target_score: Mapped[float | None]
    score: Mapped[float | None]
    missing: Mapped[str | None]


class ReadinessRow(Base):
    __tablename__ = "daily_readiness"
    day: Mapped[date] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    training_readiness: Mapped[int | None]
    hrv_status: Mapped[str | None]
    sleep_score: Mapped[int | None]


class DailyAdjustmentRow(Base):
    __tablename__ = "daily_adjustments"
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"), primary_key=True)
    day: Mapped[date]
    proposal_fingerprint: Mapped[str] = mapped_column(unique=True)
    reasons: Mapped[list[str]]
    # Immutable evidence and before/after snapshots, not the current plan state.
    readiness: Mapped[dict] = mapped_column(JSONB)
    before: Mapped[dict] = mapped_column(JSONB)
    after: Mapped[dict] = mapped_column(JSONB)
    garmin_update_required: Mapped[bool]


class AdjustmentRow(Base):
    __tablename__ = "adjustments"
    __table_args__ = (ForeignKeyConstraint(["plan_id", "week"], ["weeks.plan_id", "weeks.number"]),)
    plan_id: Mapped[str] = mapped_column(primary_key=True)
    week: Mapped[int] = mapped_column(primary_key=True)
    factor: Mapped[float]
    reasons: Mapped[list[str]]
    inputs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
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


class SyncAttemptRow(Base):
    __tablename__ = "sync_attempts"
    id: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str]
    since: Mapped[date]
    until: Mapped[date]
    activity_count: Mapped[int]
    error: Mapped[str | None]
    history_range: Mapped[str | None]
    next_page: Mapped[int]
    next_page_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityDetailRow(Base):
    __tablename__ = "activity_details"
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(default="local")
    raw_summary: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fit_name: Mapped[str | None]
    moving_time_s: Mapped[float | None]
    elapsed_time_s: Mapped[float | None]
    average_pace_s_km: Mapped[float | None]
    max_pace_s_km: Mapped[float | None]
    average_speed_m_s: Mapped[float | None]
    max_speed_m_s: Mapped[float | None]
    max_hr: Mapped[float | None]
    average_cadence_spm: Mapped[float | None]
    max_cadence_spm: Mapped[float | None]
    stride_length_cm: Mapped[float | None]
    vertical_oscillation_cm: Mapped[float | None]
    vertical_ratio_percent: Mapped[float | None]
    ground_contact_time_ms: Mapped[float | None]
    average_power_w: Mapped[float | None]
    max_power_w: Mapped[float | None]
    normalized_power_w: Mapped[float | None]
    elevation_gain_m: Mapped[float | None]
    elevation_loss_m: Mapped[float | None]
    min_elevation_m: Mapped[float | None]
    max_elevation_m: Mapped[float | None]
    average_temperature_c: Mapped[float | None]
    min_temperature_c: Mapped[float | None]
    max_temperature_c: Mapped[float | None]
    calories: Mapped[float | None]
    aerobic_training_effect: Mapped[float | None]
    anaerobic_training_effect: Mapped[float | None]
    training_load: Mapped[float | None]
    vo2_max: Mapped[float | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None]
    device: Mapped[str | None]


class ActivityLapRow(Base):
    __tablename__ = "activity_laps"
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    distance_m: Mapped[float]
    duration_s: Mapped[float]
    average_pace_s_km: Mapped[float | None]
    average_hr: Mapped[float | None]
    max_hr: Mapped[float | None]
    average_cadence_spm: Mapped[float | None]
    elevation_gain_m: Mapped[float | None]
    elevation_loss_m: Mapped[float | None]
    average_power_w: Mapped[float | None]
    max_power_w: Mapped[float | None]


class ActivitySplitRow(Base):
    __tablename__ = "activity_splits"
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    distance_m: Mapped[float]
    duration_s: Mapped[float]
    average_pace_s_km: Mapped[float | None]
    average_hr: Mapped[float | None]
    max_hr: Mapped[float | None]
    average_cadence_spm: Mapped[float | None]
    elevation_gain_m: Mapped[float | None]
    elevation_loss_m: Mapped[float | None]
    average_power_w: Mapped[float | None]
    max_power_w: Mapped[float | None]


class ActivityZoneRow(Base):
    __tablename__ = "activity_hr_zones"
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    zone: Mapped[int]
    seconds: Mapped[float]
    lower_bpm: Mapped[float | None]
    upper_bpm: Mapped[float | None]


class ActivityStreamRow(Base):
    __tablename__ = "activity_streams"
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    format: Mapped[str]
    data: Mapped[bytes] = mapped_column(LargeBinary)


class PairingCodeRow(Base):
    __tablename__ = "pairing_codes"

    code_hash: Mapped[str] = mapped_column(primary_key=True)
    token_hash: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PairingLimitRow(Base):
    __tablename__ = "pairing_limit"

    id: Mapped[int] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int]


class GarminCalendarRow(Base):
    __tablename__ = "garmin_calendar"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_calendar"),
        CheckConstraint("window_days BETWEEN 7 AND 28", name="calendar_window"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(default=14, server_default="14")
    synced_fingerprint: Mapped[str | None] = mapped_column(Text)
