"""Daily recovery observations, confirmed proposals, and step scores."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_readiness",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_readiness", sa.Integer()),
        sa.Column("hrv_status", sa.String()),
        sa.Column("sleep_score", sa.Integer()),
    )
    op.create_table(
        "daily_adjustments",
        sa.Column("workout_id", sa.String(), sa.ForeignKey("workouts.id"), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(), unique=True, nullable=False),
        sa.Column("reasons", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("readiness", JSONB(), nullable=False),
        sa.Column("before", JSONB(), nullable=False),
        sa.Column("after", JSONB(), nullable=False),
        sa.Column("garmin_update_required", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "step_compliance",
        sa.Column(
            "workout_id",
            sa.String(),
            sa.ForeignKey("matches.workout_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("planned_seconds", sa.Numeric(), nullable=False),
        sa.Column("actual_seconds", sa.Numeric()),
        sa.Column("duration_in_range", sa.Boolean()),
        sa.Column("target", sa.String()),
        sa.Column("target_score", sa.Numeric()),
        sa.Column("score", sa.Numeric()),
        sa.Column("missing", sa.String()),
    )


def downgrade():
    op.drop_table("step_compliance")
    op.drop_table("daily_adjustments")
    op.drop_table("daily_readiness")
