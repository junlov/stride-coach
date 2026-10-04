"""Durable sync jobs and adjustment evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("adjustments", sa.Column("inputs", JSONB(), nullable=False, server_default="{}"))
    op.create_table(
        "sync_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("until", sa.Date(), nullable=False),
        sa.Column("activity_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("history_range", sa.String()),
        sa.Column("next_page", sa.Integer(), nullable=False),
        sa.Column("next_page_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sync_attempts_started_at", "sync_attempts", ["started_at"])


def downgrade():
    op.drop_table("sync_attempts")
    op.drop_column("adjustments", "inputs")
