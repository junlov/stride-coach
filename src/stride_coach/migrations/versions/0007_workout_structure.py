"""Typed repeat groups, step end conditions and current Garmin zones."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "steps", sa.Column("end_condition", sa.String(), nullable=False, server_default="time")
    )
    op.add_column("steps", sa.Column("distance_m", sa.Numeric()))
    for name in ("preferred_hr_zone", "hr_zone", "cadence_min", "cadence_max", "group_position"):
        op.add_column("steps", sa.Column(name, sa.Integer()))
    op.create_table(
        "step_repeats",
        sa.Column("workout_id", sa.String(), sa.ForeignKey("workouts.id"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("skip_last_rest", sa.Boolean(), nullable=False),
        sa.CheckConstraint("repetitions BETWEEN 2 AND 100"),
    )
    op.create_table(
        "garmin_hr_zones",
        sa.Column("zone", sa.Integer(), primary_key=True),
        sa.Column("lower_bpm", sa.Integer(), nullable=False),
        sa.Column("upper_bpm", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    connection = op.get_bind()
    structured = connection.scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM step_repeats) OR EXISTS (
            SELECT 1 FROM steps WHERE end_condition != 'time' OR distance_m IS NOT NULL
            OR preferred_hr_zone IS NOT NULL OR hr_zone IS NOT NULL
            OR cadence_min IS NOT NULL OR cadence_max IS NOT NULL
        )
    """)
    )
    if structured:
        raise RuntimeError("Restore a pre-upgrade backup to downgrade structured workouts")
    op.drop_table("garmin_hr_zones")
    op.drop_table("step_repeats")
    for name in (
        "group_position",
        "cadence_max",
        "cadence_min",
        "hr_zone",
        "preferred_hr_zone",
        "distance_m",
        "end_condition",
    ):
        op.drop_column("steps", name)
