"""Typed coaching records and durable Garmin ledger"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("distance_km", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("duration_min", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("average_hr", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "easy", "long", "tempo", "intervals", "recovery", "run-walk", name="session_kind"
            ),
            nullable=True,
        ),
        sa.Column("best_effort", sa.Boolean(), nullable=False),
        sa.CheckConstraint("distance_km >= 0 AND duration_min > 0", name="activity_measurements"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_activities_day"), "activities", ["day"], unique=False)
    op.create_table(
        "metadata",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("since", sa.Date(), nullable=True),
        sa.Column("until", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("key IN ('sync', 'sync_complete')", name="coverage_key"),
        sa.CheckConstraint(
            "(since IS NULL AND until IS NULL) OR "
            "(since IS NOT NULL AND until IS NOT NULL AND since <= until)",
            name="coverage_dates",
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column(
            "goal",
            sa.Enum("5k", "10k", "half", "marathon", "return-to-running", name="goal_kind"),
            nullable=False,
        ),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("race_date", sa.Date(), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column("long_run_day", sa.Integer(), nullable=False),
        sa.Column("resting_hr", sa.Integer(), nullable=False),
        sa.Column("max_hr", sa.Integer(), nullable=False),
        sa.Column("trimp_a", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("trimp_b", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("vdot", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("easy_pace", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("weekly_minutes", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("fitness_source", sa.String(), nullable=False),
        sa.Column("warnings", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("singleton", name="single_active_plan"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton"),
    )
    op.create_table(
        "weeks",
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.CheckConstraint("number > 0", name="positive_week"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
        ),
        sa.PrimaryKeyConstraint("plan_id", "number"),
    )
    op.create_table(
        "adjustments",
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("factor", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("reasons", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("before_minutes", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("after_minutes", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "week"],
            ["weeks.plan_id", "weeks.number"],
        ),
        sa.PrimaryKeyConstraint("plan_id", "week"),
    )
    op.create_table(
        "workouts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "easy",
                "long",
                "tempo",
                "intervals",
                "recovery",
                "run-walk",
                name="session_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("cutback", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "week"],
            ["weeks.plan_id", "weeks.number"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "position"),
    )
    op.create_index(op.f("ix_workouts_day"), "workouts", ["day"], unique=False)
    op.create_table(
        "matches",
        sa.Column("workout_id", sa.String(), nullable=False),
        sa.Column("activity_id", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
        ),
        sa.PrimaryKeyConstraint("workout_id"),
        sa.UniqueConstraint("activity_id"),
    )
    op.create_table(
        "scheduled",
        sa.Column("workout_id", sa.String(), nullable=False),
        sa.Column("remote_id", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("scheduled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
        ),
        sa.PrimaryKeyConstraint("workout_id"),
    )
    op.create_table(
        "steps",
        sa.Column("workout_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("warmup", "cooldown", "recovery", "interval", name="step_kind"),
            nullable=False,
        ),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("minutes", sa.Numeric(asdecimal=False), nullable=False),
        sa.Column("pace_min", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("pace_max", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("hr_min", sa.Integer(), nullable=True),
        sa.Column("hr_max", sa.Integer(), nullable=True),
        sa.CheckConstraint("minutes > 0", name="positive_step_minutes"),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
        ),
        sa.PrimaryKeyConstraint("workout_id", "position"),
    )
    op.create_table(
        "write_intents",
        sa.Column("workout_id", sa.String(), nullable=False),
        sa.Column(
            "operation", sa.Enum("create", "schedule", name="write_operation"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
        ),
        sa.PrimaryKeyConstraint("workout_id", "operation"),
    )


def downgrade():
    op.drop_table("write_intents")
    op.drop_table("steps")
    op.drop_table("scheduled")
    op.drop_table("matches")
    op.drop_index(op.f("ix_workouts_day"), table_name="workouts")
    op.drop_table("workouts")
    op.drop_table("adjustments")
    op.drop_table("weeks")
    op.drop_table("plans")
    op.drop_table("metadata")
    op.drop_index(op.f("ix_activities_day"), table_name="activities")
    op.drop_table("activities")

    for name in ("write_operation", "step_kind", "session_kind", "goal_kind"):
        sa.Enum(name=name).drop(op.get_bind())
