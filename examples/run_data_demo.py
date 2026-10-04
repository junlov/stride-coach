"""Prove capture/import/API persistence with synthetic data and disposable PostgreSQL."""

import json
import math
import os
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import text
from synthetic_database import synthetic_database

from stride_coach.activity_models import RunStreams
from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin import GarminClient, normalize_activity
from stride_coach.models import Activity
from stride_coach.service import Coach, SyncRequest
from stride_coach.storage import Store

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
DAY = date(2026, 9, 1)


def fixture(name):
    return json.loads((FIXTURES / f"run-{name}.json").read_text())


def sizes(store, activity_id):
    total = 0
    with store.transaction() as session:
        for table in (
            "activities",
            "activity_details",
            "activity_laps",
            "activity_splits",
            "activity_hr_zones",
            "activity_streams",
        ):
            key = "id" if table == "activities" else "activity_id"
            total += session.scalar(
                text(f"SELECT coalesce(sum(pg_column_size(t)), 0) FROM {table} t WHERE {key}=:id"),
                {"id": activity_id},
            )
        stream_bytes = session.scalar(
            text("SELECT octet_length(data) FROM activity_streams WHERE activity_id=:id"),
            {"id": activity_id},
        )
    return {"postgres_row_bytes": int(total), "compressed_stream_bytes": stream_bytes}


def run(directory):
    os.environ["STRIDE_COACH_FIT_DIR"] = str(directory / "fit")
    os.environ["STRIDE_COACH_STORE_GPS"] = "true"
    os.environ["STRIDE_COACH_DETAIL_DELAY_SECONDS"] = "0.1"
    summary = fixture("summary")
    activity = normalize_activity({**summary, **summary["summaryDTO"]})
    client = object.__new__(GarminClient)
    client._valid_token = lambda: None
    client.activities = lambda *_: [activity]
    client.api = SimpleNamespace(
        get_activity=lambda _: fixture("summary"),
        get_activity_splits=lambda _: fixture("laps"),
        get_activity_hr_in_timezones=lambda _: fixture("zones"),
        get_activity_details=lambda *_, **__: fixture("streams"),
        download_activity=lambda *_, **__: (FIXTURES / "synthetic-run.fit").read_bytes(),
        ActivityDownloadFormat=SimpleNamespace(ORIGINAL="original"),
    )
    store = Store()
    try:
        coach = Coach(store, client_factory=lambda _: client)
        first = coach.sync(SyncRequest(since=DAY, until=DAY))
        assert first.details.completed == 1
        repeated = coach.sync(SyncRequest(since=DAY, until=DAY))
        assert repeated.details.completed == 0
        assert len(list((directory / "fit").glob("*.fit"))) == 1
        fixture_sizes = sizes(store, activity.id)
        fixture_sizes["fit_bytes"] = (FIXTURES / "synthetic-run.fit").stat().st_size
        seconds = list(range(3601))
        streams = RunStreams(
            time_s=seconds,
            distance_m=[round(t * 10000 / 3600, 3) for t in seconds],
            heart_rate_bpm=[round(145 + 12 * math.sin(t / 120), 1) for t in seconds],
            speed_m_s=[round(2.8 + 0.2 * math.sin(t / 30), 3) for t in seconds],
            cadence_spm=[round(172 + 4 * math.sin(t / 60), 1) for t in seconds],
            elevation_m=[round(40 + 10 * math.sin(t / 300), 2) for t in seconds],
            power_w=[round(230 + 30 * math.sin(t / 90), 1) for t in seconds],
            latitude_deg=[round(-23 + t / 1000000, 6) for t in seconds],
            longitude_deg=[round(-46 + t / 1000000, 6) for t in seconds],
        )
        one_hour = Activity(
            id="synthetic-hour",
            day=DAY,
            distance_km=10,
            duration_min=60,
            average_hr=145,
            streams=streams,
        )
        coach.sync(SyncRequest(since=DAY, until=DAY, activities=[activity, one_hour]))
        hour_sizes = sizes(store, one_hour.id)
        hour_sizes["stream_json_bytes"] = len(streams.model_dump_json(exclude_none=True).encode())
        config = ServerConfig.from_env(
            token="synthetic-run-data-proof-bearer-secret", tokens=directory / "tokens"
        )

        def forbidden(_):
            raise AssertionError("API reads must not contact Garmin")

        with TestClient(create_app(config, client_factory=forbidden)) as api:
            headers = {"Authorization": "Bearer synthetic-run-data-proof-bearer-secret"}
            detail = api.get("/activities/12345", headers=headers)
            data = api.get("/activities/12345/streams", headers=headers)
            assert detail.status_code == data.status_code == 200
            assert len(detail.json()["laps"]) == 2
            assert len(detail.json()["hr_zones"]) == 3
            assert "streams" not in detail.json()
            assert len(data.json()["time_s"]) == 6
        print(
            json.dumps(
                {
                    "capture": first.details.model_dump(),
                    "repeat_capture": repeated.details.model_dump(),
                    "api": "detail and streams: 200; 2 laps, 3 zones, 6 samples",
                    "fixture_run": fixture_sizes,
                    "one_hour_run": hour_sizes,
                },
                indent=2,
            )
        )
    finally:
        store.close()


if __name__ == "__main__":
    with synthetic_database(), tempfile.TemporaryDirectory(prefix="stride-run-proof-") as folder:
        run(Path(folder))
