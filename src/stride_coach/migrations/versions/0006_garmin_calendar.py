"""Persist Garmin calendar preferences and last confirmed plan fingerprint."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "garmin_calendar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("synced_fingerprint", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="single_calendar"),
        sa.CheckConstraint("window_days BETWEEN 7 AND 28", name="calendar_window"),
    )


def downgrade():
    op.drop_table("garmin_calendar")
