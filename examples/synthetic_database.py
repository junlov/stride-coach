"""Allocate and remove an isolated schema in an explicitly supplied test database."""

import os
import uuid
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url

from stride_coach.database import make_engine


@contextmanager
def synthetic_database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        raise SystemExit("Set TEST_DATABASE_URL to disposable PostgreSQL; see docs/self-hosting.md")
    engine = make_engine(url)
    schema = "demo_" + uuid.uuid4().hex
    previous = os.environ.get("DATABASE_URL")
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    os.environ["DATABASE_URL"] = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
