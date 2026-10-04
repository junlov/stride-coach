"""Retain uncertain unscheduling across retries and restarts."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE write_operation ADD VALUE 'unschedule'")


def downgrade():
    op.execute("DELETE FROM write_intents WHERE operation = 'unschedule'")
    op.execute("ALTER TABLE write_intents ALTER COLUMN operation TYPE text")
    op.execute("DROP TYPE write_operation")
    op.execute("CREATE TYPE write_operation AS ENUM ('create', 'schedule')")
    op.execute(
        "ALTER TABLE write_intents ALTER COLUMN operation TYPE write_operation "
        "USING operation::write_operation"
    )
