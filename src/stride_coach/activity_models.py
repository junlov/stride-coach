"""Optional run detail contract, shared by imports and the authenticated API."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class DetailRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StepCompliance(DetailRecord):
    position: int
    label: str
    planned_seconds: float
    actual_seconds: float | None = None
    duration_in_range: bool | None = None
    target: Literal["pace", "heart_rate"] | None = None
    target_score: float | None = Field(default=None, ge=0, le=100)
    score: float | None = Field(default=None, ge=0, le=100)
    missing: str | None = None


class RunCompliance(DetailRecord):
    workout_id: str
    rule_version: Literal["laps-v1"] = "laps-v1"
    score: float | None = None
    scored_steps: int
    missing_steps: int
    steps: list[StepCompliance]


class RunMetrics(DetailRecord):
    moving_time_s: float | None = Field(default=None, ge=0)
    elapsed_time_s: float | None = Field(default=None, ge=0)
    average_pace_s_km: float | None = Field(default=None, gt=0)
    max_pace_s_km: float | None = Field(default=None, gt=0)
    average_speed_m_s: float | None = Field(default=None, ge=0)
    max_speed_m_s: float | None = Field(default=None, ge=0)
    max_hr: float | None = Field(default=None, ge=0)
    average_cadence_spm: float | None = Field(default=None, ge=0)
    max_cadence_spm: float | None = Field(default=None, ge=0)
    stride_length_cm: float | None = Field(default=None, ge=0)
    vertical_oscillation_cm: float | None = Field(default=None, ge=0)
    vertical_ratio_percent: float | None = Field(default=None, ge=0)
    ground_contact_time_ms: float | None = Field(default=None, ge=0)
    average_power_w: float | None = Field(default=None, ge=0)
    max_power_w: float | None = Field(default=None, ge=0)
    normalized_power_w: float | None = Field(default=None, ge=0)
    elevation_gain_m: float | None = Field(default=None, ge=0)
    elevation_loss_m: float | None = Field(default=None, ge=0)
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    average_temperature_c: float | None = None
    min_temperature_c: float | None = None
    max_temperature_c: float | None = None
    calories: float | None = Field(default=None, ge=0)
    aerobic_training_effect: float | None = Field(default=None, ge=0)
    anaerobic_training_effect: float | None = Field(default=None, ge=0)
    training_load: float | None = Field(default=None, ge=0)
    vo2_max: float | None = Field(default=None, ge=0)
    started_at: AwareDatetime | None = None
    timezone: str | None = None
    device: str | None = None


class RunLap(DetailRecord):
    distance_m: float = Field(ge=0)
    duration_s: float = Field(ge=0)
    average_pace_s_km: float | None = Field(default=None, gt=0)
    average_hr: float | None = Field(default=None, ge=0)
    max_hr: float | None = Field(default=None, ge=0)
    average_cadence_spm: float | None = Field(default=None, ge=0)
    elevation_gain_m: float | None = Field(default=None, ge=0)
    elevation_loss_m: float | None = Field(default=None, ge=0)
    average_power_w: float | None = Field(default=None, ge=0)
    max_power_w: float | None = Field(default=None, ge=0)


class HeartRateZone(DetailRecord):
    zone: int = Field(ge=0)
    seconds: float = Field(ge=0)
    lower_bpm: float | None = Field(default=None, ge=0)
    upper_bpm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.lower_bpm is not None and self.upper_bpm is not None:
            if self.lower_bpm > self.upper_bpm:
                raise ValueError("Zone bounds must be ordered")
        return self


class RunStreams(DetailRecord):
    version: Literal[1] = 1
    time_s: list[float] = Field(default_factory=list)
    distance_m: list[float | None] | None = None
    heart_rate_bpm: list[float | None] | None = None
    speed_m_s: list[float | None] | None = None
    cadence_spm: list[float | None] | None = None
    elevation_m: list[float | None] | None = None
    power_w: list[float | None] | None = None
    latitude_deg: list[float | None] | None = None
    longitude_deg: list[float | None] | None = None

    @model_validator(mode="after")
    def aligned(self):
        if any(t < 0 for t in self.time_s) or self.time_s != sorted(self.time_s):
            raise ValueError("Stream time_s must be nonnegative and ordered")
        for key in type(self).model_fields:
            values = getattr(self, key)
            if isinstance(values, list) and len(values) != len(self.time_s):
                raise ValueError("Stream columns must have equal lengths")
        for key, limit in (("latitude_deg", 90), ("longitude_deg", 180)):
            if any(abs(v) > limit for v in getattr(self, key) or [] if v is not None):
                raise ValueError("Invalid GPS coordinates")
        return self


class CaptureStatus(DetailRecord):
    state: str
    attempts: int
    error: str | None = None
    fetched_at: datetime | None = None
    fit_archived: bool = False


class BackfillResult(DetailRecord):
    completed: int = 0
    failed: int = 0
    remaining: int = 0
