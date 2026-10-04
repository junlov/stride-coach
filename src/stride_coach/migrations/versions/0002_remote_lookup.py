"""Index remote ledger identifiers for operator reconciliation."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_scheduled_remote_id", "scheduled", ["remote_id"])


def downgrade():
    op.drop_index("ix_scheduled_remote_id", table_name="scheduled")
