"""Typed repeat groups, step end conditions and current Garmin zones."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("steps", sa.Column("end_condition", sa.String(), nullable=False, server_default="time"))
    op.add_column("steps", sa.Column("distance_m", sa.Numeric()))
    for name in ("preferred_hr_zone", "hr_zone", "cadence_min", "cadence_max", "group_position"):
        op.add_column("steps", sa.Column(name, sa.Integer()))
    op.create_table("step_repeats",
        sa.Column("workout_id", sa.String(), sa.ForeignKey("workouts.id"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("skip_last_rest", sa.Boolean(), nullable=False),
        sa.CheckConstraint("repetitions BETWEEN 2 AND 100"),
    )
    op.create_table("garmin_hr_zones",
        sa.Column("zone", sa.Integer(), primary_key=True),
        sa.Column("lower_bpm", sa.Integer(), nullable=False),
        sa.Column("upper_bpm", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # Flatten repetitions before dropping structure so durations are not lost.
    raise RuntimeError("Restore a pre-upgrade backup to downgrade structured workouts")
