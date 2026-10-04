"""Migrations share the connection and lock supplied by stride-coach db upgrade."""

from alembic import context

from stride_coach.db_models import Base

context.configure(connection=context.config.attributes["connection"], target_metadata=Base.metadata)
with context.begin_transaction():
    context.run_migrations()
