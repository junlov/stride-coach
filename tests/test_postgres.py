"""Execute migration, import, constraints, and recovery against a real PostgreSQL."""

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner

from stride_coach.api import ServerConfig, create_app
from stride_coach.cli import app
from stride_coach.database import check_schema, database_url, make_engine, migration_config, upgrade
from stride_coach.db_models import MatchRow, PlanRow, StepRow
from stride_coach.models import Activity, Adjustment
from stride_coach.sqlite_import import import_sqlite
from stride_coach.storage import Store

TOKEN = "synthetic-postgres-test-bearer-secret"


def legacy(path, plan, *, unknown_metadata=False):
    activity = Activity(
        id="synthetic-run",
        day=plan.workouts[0].day,
        distance_km=5,
        duration_min=30,
        kind=plan.workouts[0].kind,
    )
    adjustment = Adjustment(
        week=2,
        factor=0.75,
        reasons=["Synthetic imported reduction"],
        before_minutes=129.6,
        after_minutes=97.19999999999999,
        applied=True,
    )
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE plan(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE activities(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE adjustments(week INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE scheduled(workout_id TEXT PRIMARY KEY, remote_id TEXT,
                fingerprint TEXT, scheduled INTEGER);
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
        """)
        db.execute("INSERT INTO plan VALUES (1, ?)", (plan.model_dump_json(),))
        db.execute(
            "INSERT INTO activities VALUES (?, ?)", (activity.id, activity.model_dump_json())
        )
        db.execute("INSERT INTO adjustments VALUES (?, ?)", (2, adjustment.model_dump_json()))
        db.execute("INSERT INTO scheduled VALUES (?, '123', 'digest', 1)", (plan.workouts[0].id,))
        db.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("sync", json.dumps({"since": str(activity.day), "until": str(activity.day)})),
                ("sync_complete", "{}"),
                ("create:" + plan.workouts[1].id, "pending"),
                ("schedule:" + plan.workouts[0].id, "pending"),
            ],
        )
        if unknown_metadata:
            db.execute("INSERT INTO metadata VALUES ('unknown', 'unrecognized')")
    return activity, adjustment


def test_legacy_import_roundtrip_and_no_duplicates(database, tmp_path, plan):
    path = tmp_path / "legacy.db"
    activity, adjustment = legacy(path, plan)
    before = path.read_bytes()
    result = CliRunner().invoke(app, ["db", "import-sqlite", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "plans": 1,
        "activities": 1,
        "adjustments": 1,
        "scheduled": 1,
        "metadata": 4,
    }
    assert path.read_bytes() == before
    store = Store(database)
    try:
        assert store.plan() == plan
        assert store.activities() == [activity]
        assert store.adjustment(2) == adjustment
        assert store.scheduled(plan.workouts[0].id)["remote_id"] == "123"
        assert store.scheduled(plan.workouts[0].id)["scheduled"] is True
        assert store.pending("create:" + plan.workouts[1].id)
        assert store.pending("schedule:" + plan.workouts[0].id)
        assert store.sync_window() == {"since": str(activity.day), "until": str(activity.day)}
        assert store.sync_window(complete=True) == {}
        with store.transaction() as session:
            match = session.scalar(select(MatchRow))
            assert match.activity_id == activity.id
            assert match.workout_id == plan.workouts[0].id
        with pytest.raises(ValueError, match="empty"):
            import_sqlite(path, store)
        assert store.plan() == plan
    finally:
        store.close()


def test_import_unknown_metadata_rolls_back_everything(database, tmp_path, plan):
    path = tmp_path / "legacy.db"
    legacy(path, plan, unknown_metadata=True)
    store = Store(database)
    try:
        with pytest.raises(ValueError, match="Unknown legacy metadata"):
            import_sqlite(path, store)
        with pytest.raises(ValueError, match="No plan"):
            store.plan()
        assert store.activities() == []
        assert store.scheduled_count() == 0
    finally:
        store.close()


def test_import_orphan_ledger_rolls_back(database, tmp_path, plan):
    path = tmp_path / "legacy.db"
    legacy(path, plan)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE scheduled SET workout_id='missing'")
    store = Store(database)
    try:
        with pytest.raises(IntegrityError):
            import_sqlite(path, store)
        assert store.activities() == []
        with pytest.raises(ValueError, match="No plan"):
            store.plan()
    finally:
        store.close()


def test_restart_retains_unresolved_write_and_adaptation(store):
    from test_garmin import FakeGarmin

    from stride_coach.adaptation import adapt
    from stride_coach.garmin import GarminError, push

    plan = store.plan()
    client = FakeGarmin()
    client.fail_create = True
    with pytest.raises(GarminError, match="Response lost"):
        push(store, plan.workouts[:1], client, False)
    reopened = Store(store.url)
    try:
        assert reopened.pending("create:" + plan.workouts[0].id)
        client.fail_create = False
        client.hide_workouts = True
        with pytest.raises(GarminError, match="unresolved"):
            push(reopened, plan.workouts[:1], client, False)
        assert client.writes == ["create"]
        client.hide_workouts = False
        push(reopened, plan.workouts[:1], client, False)
        assert client.writes.count("create") == 1
        assert client.writes.count("schedule") == 1
        monday = plan.setup.start + timedelta(weeks=1)
        reopened.save_sync([], str(monday - timedelta(days=14)), str(monday), today=monday)
        applied = adapt(reopened, 2, monday, apply=True)
        assert store.adjustment(2) == applied
        assert store.scheduled(plan.workouts[0].id)["scheduled"]
    finally:
        reopened.close()


def test_upgrade_preserves_data_and_unknown_revision_is_refused(store, tmp_path):
    plan = store.plan()
    with store.connection.begin():
        command.downgrade(migration_config(store.connection), "0001")
    with pytest.raises(ValueError, match="not supported"):
        Store(store.url, read_only=True)
    # API startup applies the pending migration from the prior revision.
    with TestClient(create_app(ServerConfig(token=TOKEN, tokens=tmp_path / "tokens"))) as client:
        assert client.get("/health").json() == {"status": "ready"}
    assert store.plan() == plan
    with store.connection.begin():
        check_schema(store.connection)
        assert "ix_scheduled_remote_id" in {
            index["name"] for index in inspect(store.connection).get_indexes("scheduled")
        }
        store.connection.execute(text("UPDATE alembic_version SET version_num='future-schema'"))
    with pytest.raises(ValueError, match="newer or unknown"):
        upgrade(store.url)
    with pytest.raises(ValueError, match="newer or unknown"):
        Store(store.url)
    result = CliRunner().invoke(app, ["db", "upgrade"])
    assert result.exit_code == 1
    assert "schema compatibility" in result.output


def test_health_is_public_but_does_not_expose_schema_failure(database, tmp_path):
    config = ServerConfig(token=TOKEN, tokens=tmp_path / "tokens")
    with TestClient(create_app(config)) as client:
        assert client.get("/health").json() == {"status": "ready"}
        assert client.get("/plan").status_code == 401
        with make_engine(database).begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='future-schema'"))
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}


def test_typed_constraints_and_roundtrip(store):
    plan = store.plan()
    with store.transaction() as session:
        session.get(StepRow, (plan.workouts[0].id, 0)).minutes = 97.19999999999999
    assert store.plan().workouts[0].steps[0].minutes == 97.19999999999999
    with pytest.raises(IntegrityError):
        with store.transaction() as session:
            session.get(StepRow, (plan.workouts[0].id, 0)).minutes = -1
    with pytest.raises(IntegrityError):
        with store.transaction() as session:
            original = session.get(PlanRow, plan.id)
            session.add(
                PlanRow(
                    **{
                        c.name: getattr(original, c.name)
                        for c in PlanRow.__table__.columns
                        if c.name != "id"
                    },
                    id="second-plan",
                )
            )
    assert store.plan().id == plan.id


@pytest.mark.parametrize("url", ["", "sqlite:///bad.db", "not-a-url", "postgresql://localhost"])
def test_postgres_only(url):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        database_url(url)


def test_configuration_failure_does_not_print_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://stride:short-password@localhost/stride")
    monkeypatch.setenv("STRIDE_COACH_API_TOKEN", TOKEN)
    result = CliRunner().invoke(app, ["--tokens", str(tmp_path / "tokens"), "serve"])
    assert result.exit_code == 1
    assert "at least 16" in result.output
    assert "short-password" not in result.output
    for token in ("x" * 40, "replace-me-with-a-generated-secret"):
        with pytest.raises(ValueError):
            ServerConfig(token=token)
    monkeypatch.setenv("TZ", "Unknown/Timezone")
    with pytest.raises(ValueError, match="TZ"):
        ServerConfig.from_env()


def test_schema_generation_still_matches_public_contract():
    # Health is an operator probe, so the mobile API contract is unchanged.
    config = ServerConfig(token=TOKEN)
    assert create_app(config).openapi() == json.loads(Path("docs/openapi.json").read_text())


def test_migrations_match_typed_models(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from stride_coach.db_models import Base

    with make_engine(database).connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_adaptation_failure_rolls_back_minutes_and_adjustment(store):
    plan = store.plan()
    plan.workouts[0].steps[0].minutes = -1
    adjustment = Adjustment(
        week=2, factor=0.75, reasons=["synthetic"], before_minutes=100, after_minutes=75
    )
    with pytest.raises(IntegrityError):
        store.apply(plan, adjustment)
    assert store.plan().workouts[0].steps[0].minutes > 0
    assert store.adjustment(2) is None
    assert not adjustment.applied


def test_readiness_and_data_errors_are_sanitized(database, tmp_path):
    from sqlalchemy.engine import make_url

    # Port 1 is intentionally unavailable; probes disclose no connection configuration.
    url = make_url(database).set(host="127.0.0.1", port=1)
    config = ServerConfig(
        token=TOKEN,
        database_url=url.render_as_string(hide_password=False),
        tokens=tmp_path / "tokens",
    )
    client = TestClient(create_app(config))
    assert client.get("/health").json() == {"status": "unavailable"}
    response = client.get("/plan", headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    with pytest.raises(RuntimeError, match="Database startup failed"):
        with TestClient(create_app(config)):
            pass
