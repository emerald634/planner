"""Add manager work schedules and temporary days off."""

import sqlalchemy as sa

from alembic import op

revision = "0002_manager_schedules"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("work_days", sa.JSON(), nullable=False, server_default="[0,1,2,3,4]"),
    )
    op.add_column(
        "users", sa.Column("workday_start", sa.Time(), nullable=False, server_default="09:00:00")
    )
    op.add_column(
        "users", sa.Column("workday_end", sa.Time(), nullable=False, server_default="18:00:00")
    )
    op.add_column("users", sa.Column("unavailable_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "unavailable_until")
    op.drop_column("users", "workday_end")
    op.drop_column("users", "workday_start")
    op.drop_column("users", "work_days")
