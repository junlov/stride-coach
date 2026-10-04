"""Typed recovery observations and explicit daily plan proposals."""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field

from .models import Record, Workout


class DailyReadiness(Record):
    day: date
    fetched_at: AwareDatetime
    training_readiness: int | None = Field(default=None, ge=0, le=100)
    hrv_status: Literal["BALANCED", "UNBALANCED", "LOW", "POOR", "UNKNOWN"] | None = None
    sleep_score: int | None = Field(default=None, ge=0, le=100)


class DailyProposal(Record):
    day: date
    readiness: DailyReadiness | None
    reasons: list[str]
    before: Workout | None = None
    after: Workout | None = None
    proposal_fingerprint: str | None = None
    applied: bool = False
    garmin_update_required: bool = False


class DailyAdaptRequest(Record):
    apply: bool = False
    proposal_fingerprint: str | None = None
