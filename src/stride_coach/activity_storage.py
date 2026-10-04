"""Transactional run details. Streams never load during coaching calculations."""

import json
import os
import zlib
from datetime import UTC, datetime

from sqlalchemy import delete, select

from .activity_models import CaptureStatus, HeartRateZone, RunLap, RunMetrics, RunStreams
from .db_models import (
    ActivityDetailRow,
    ActivityLapRow,
    ActivityRow,
    ActivitySplitRow,
    ActivityStreamRow,
    ActivityZoneRow,
)
from .models import ActivityCore, RunDetail

STREAM_FORMAT = "stride-streams-v1+json+zlib"


def store_gps() -> bool:
    value = os.getenv("STRIDE_COACH_STORE_GPS", "true").lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("STRIDE_COACH_STORE_GPS must be true or false")
    return value in {"true", "1"}


def without_gps(streams: RunStreams) -> RunStreams:
    return streams.model_copy(update={"latitude_deg": None, "longitude_deg": None})


def save_details(session, activity, *, gps: bool | None = None):
    gps = store_gps() if gps is None else gps
    row = session.get(ActivityDetailRow, activity.id)
    if row is None:
        row = ActivityDetailRow(activity_id=activity.id, source=activity.source)
        session.add(row)
    if activity.metrics is not None:
        # Omitted fields preserve earlier detail on summary-only re-sync.
        for name, value in activity.metrics.model_dump(exclude_unset=True).items():
            setattr(row, name, value)
    if activity.raw_summary is not None and (row.state != "complete" or activity.laps is not None):
        row.raw_summary = activity.raw_summary if gps else None
    if not gps:
        row.raw_summary = None
    for name, table in (
        ("laps", ActivityLapRow),
        ("splits", ActivitySplitRow),
        ("hr_zones", ActivityZoneRow),
    ):
        values = getattr(activity, name)
        if values is not None:
            session.execute(delete(table).where(table.activity_id == activity.id))
            session.add_all(
                table(activity_id=activity.id, position=i, **value.model_dump())
                for i, value in enumerate(values)
            )
    if activity.streams is not None:
        streams = activity.streams if gps else without_gps(activity.streams)
        session.merge(
            ActivityStreamRow(
                activity_id=activity.id,
                format=STREAM_FORMAT,
                data=zlib.compress(streams.model_dump_json(exclude_none=True).encode(), level=9),
            )
        )
    if activity.source == "local":
        row.state = "imported"
    return row


def read_detail(store, activity_id: str) -> RunDetail:
    with store.transaction() as session:
        activity = session.get(ActivityRow, activity_id)
        if activity is None:
            raise ValueError("Activity not found")
        result = RunDetail(**{k: getattr(activity, k) for k in ActivityCore.model_fields})
        row = session.get(ActivityDetailRow, activity_id)
        if row:
            result.metrics = RunMetrics(**{k: getattr(row, k) for k in RunMetrics.model_fields})
            result.raw_summary = row.raw_summary
            result.capture = CaptureStatus(
                state=row.state,
                attempts=row.attempts,
                error=row.error,
                fetched_at=row.fetched_at,
                fit_archived=row.fit_name is not None,
            )
        for name, table, model in (
            ("laps", ActivityLapRow, RunLap),
            ("splits", ActivitySplitRow, RunLap),
            ("hr_zones", ActivityZoneRow, HeartRateZone),
        ):
            rows = session.scalars(
                select(table).where(table.activity_id == activity_id).order_by(table.position)
            )
            setattr(
                result,
                name,
                [model(**{k: getattr(r, k) for k in model.model_fields}) for r in rows],
            )
        return result


def read_streams(store, activity_id: str) -> RunStreams | None:
    with store.transaction() as session:
        if session.get(ActivityRow, activity_id) is None:
            raise ValueError("Activity not found")
        row = session.get(ActivityStreamRow, activity_id)
        if row is None:
            return None
        if row.format != STREAM_FORMAT:
            raise ValueError("Unsupported stream storage format")
        return RunStreams.model_validate(json.loads(zlib.decompress(row.data)))


def pending_ids(store, limit: int, *, include_legacy: bool = False) -> list[str]:
    with store.transaction() as session:
        query = (
            select(ActivityRow.id)
            .outerjoin(ActivityDetailRow, ActivityDetailRow.activity_id == ActivityRow.id)
            .where(ActivityRow.sport == "running")
        )
        pending = (ActivityDetailRow.source == "garmin") & (
            ActivityDetailRow.state.in_(["pending", "failed"])
        )
        if include_legacy:
            pending |= ActivityDetailRow.activity_id.is_(None)
        return list(
            session.scalars(
                query.where(pending).order_by(ActivityRow.day, ActivityRow.id).limit(limit)
            )
        )


def mark_attempt(store, activity_id, *, error=None, complete=False, fit_name=None):
    with store.transaction() as session:
        row = session.get(ActivityDetailRow, activity_id)
        if row is None:
            row = ActivityDetailRow(activity_id=activity_id, source="garmin", attempts=0)
            session.add(row)
        if not error and not complete:
            row.attempts += 1
        row.state = "complete" if complete else "failed" if error else "pending"
        row.error = error
        if complete:
            row.fetched_at = datetime.now(UTC)
            row.fit_name = fit_name
