"""One-time, read-only legacy import. SQLite is never used as a runtime store."""

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from sqlalchemy import select

from .db_models import (
    ActivityRow,
    AdjustmentRow,
    Base,
    MetadataRow,
    ScheduledRow,
    WriteIntentRow,
    WriteOperation,
)
from .models import Activity, Adjustment, Plan
from .storage import Store


def import_sqlite(path: Path, store: Store) -> dict[str, int]:
    path = path.expanduser().resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        plans = [
            Plan.model_validate_json(row[0]) for row in source.execute("SELECT data FROM plan")
        ]
        if len(plans) > 1:
            raise ValueError("Legacy database must contain at most one plan")
        activities = [
            Activity.model_validate_json(row[0])
            for row in source.execute("SELECT data FROM activities")
        ]
        adjustments = [
            Adjustment.model_validate_json(row[0])
            for row in source.execute("SELECT data FROM adjustments")
        ]
        scheduled = [dict(row) for row in source.execute("SELECT * FROM scheduled")]
        metadata = [dict(row) for row in source.execute("SELECT * FROM metadata")]
    # One transaction imports all data or none. Refuse merges, including repeated imports.
    with store.lock(), store.transaction() as session:
        if any(
            session.execute(select(table).limit(1)).first() for table in Base.metadata.sorted_tables
        ):
            raise ValueError("Import requires an empty PostgreSQL database; nothing was imported.")
        if plans:
            store._initialize(session, plans[0])
        if (adjustments or scheduled) and not plans:
            raise ValueError("Legacy adjustment/remote ledger has no owning plan")
        session.add_all(ActivityRow(**a.model_dump()) for a in activities)
        session.add_all(AdjustmentRow(plan_id=plans[0].id, **a.model_dump()) for a in adjustments)
        session.add_all(
            ScheduledRow(**{**row, "scheduled": bool(row["scheduled"])}) for row in scheduled
        )
        for row in metadata:
            key, value = row["key"], row["value"]
            if key in {"sync", "sync_complete"}:
                window = json.loads(value)
                if window and set(window) != {"since", "until"}:
                    raise ValueError("Invalid legacy sync coverage")
                session.add(
                    MetadataRow(
                        key=key,
                        since=date.fromisoformat(window["since"]) if window else None,
                        until=date.fromisoformat(window["until"]) if window else None,
                    )
                )
            elif key.startswith(("create:", "schedule:")) and value == "pending":
                operation, workout_id = key.split(":", 1)
                session.add(
                    WriteIntentRow(workout_id=workout_id, operation=WriteOperation(operation))
                )
            else:
                raise ValueError("Unknown legacy metadata; import stopped without changing data")
        store._refresh_matches(session)
    return {
        "plans": len(plans),
        "activities": len(activities),
        "adjustments": len(adjustments),
        "scheduled": len(scheduled),
        "metadata": len(metadata),
    }
