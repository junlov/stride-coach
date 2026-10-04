"""Database configuration, schema compatibility, and cross-process locks."""

import os
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool

WRITE_LOCK = 73190501
MIGRATION_LOCK = 73190502
TOKEN_LOCK = 73190503


def database_url(value: str | None = None) -> str:
    value = value if value is not None else os.getenv("DATABASE_URL", "")
    try:
        url = make_url(value)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError
        if not url.database:
            raise ValueError
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    except (ValueError, TypeError, ArgumentError):
        raise ValueError("DATABASE_URL must specify a PostgreSQL database") from None


def make_engine(url: str | None = None):
    return create_engine(
        database_url(url), poolclass=NullPool, connect_args={"connect_timeout": 10}
    )


def migration_config(connection):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.attributes["connection"] = connection
    return config


def check_schema(connection):
    config = migration_config(connection)
    head = ScriptDirectory.from_config(config).get_current_head()
    current = MigrationContext.configure(connection).get_current_heads()
    if current != (head,):
        raise ValueError(
            "Database schema is not supported by this version. "
            "Use the matching server release or run stride-coach db upgrade."
        )


@contextmanager
def connection_lock(connection, key):
    # Session locks survive the commits that make remote intent durable before network I/O.
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
    connection.commit()
    try:
        yield
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        connection.commit()


@contextmanager
def advisory_lock(key, url=None):
    engine = make_engine(url)
    try:
        with engine.connect() as connection, connection_lock(connection, key):
            yield
    finally:
        engine.dispose()


def upgrade(url: str | None = None):
    engine = make_engine(url)
    try:
        with engine.connect() as connection, connection_lock(connection, MIGRATION_LOCK):
            config = migration_config(connection)
            scripts = ScriptDirectory.from_config(config)
            current = MigrationContext.configure(connection).get_current_heads()
            known = {revision.revision for revision in scripts.walk_revisions()}
            if len(current) > 1 or any(revision not in known for revision in current):
                raise ValueError(
                    "Database has a newer or unknown schema; upgrade the server first."
                )
            connection.commit()
            with connection.begin():
                command.upgrade(config, "head")
            check_schema(connection)
    finally:
        engine.dispose()
