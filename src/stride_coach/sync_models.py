"""Durable read-only sync API records."""

from datetime import date, datetime
from typing import Literal

from .models import Record

HistoryRange = Literal["12-weeks", "6-months", "everything"]


class HistoryRequest(Record):
    range: HistoryRange


class SyncAttempt(Record):
    id: str
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    result: str = "running"
    since: date
    until: date
    activity_count: int = 0
    error: str | None = None
    history_range: HistoryRange | None = None
    next_page: int = 0
    next_page_at: datetime | None = None


class SyncStatus(Record):
    latest: SyncAttempt | None = None
    last_success: SyncAttempt | None = None
    history: SyncAttempt | None = None
    skipped: bool = False
