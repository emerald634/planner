"""Explicit shared workspace links. No identity or business-data seeds."""

import sqlalchemy as sa

from alembic import op

revision = "0005_workspace_links"
down_revision = "0004_web_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_links",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("employee_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("can_confirm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("employee_id > 0", name="ck_workspace_employee"),
    )


def downgrade():
    # Rollback CODE without dropping links. Destructive downgrade is deliberate.
    raise RuntimeError(
        "Preserve workspace links; use compatible backend rollback, not DDL downgrade"
    )
