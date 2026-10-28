"""Initial users and leads tables."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("hashed_password", sa.String(500), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "supervisor", "manager", name="userrole", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("telegram_chat_id", sa.String(100), nullable=True),
        sa.Column("bitrix_user_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column(
            "manager_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("transferred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_status", sa.String(100), nullable=False),
        sa.Column(
            "sync_status",
            sa.Enum("pending", "synced", "failed", name="leadsyncstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("bitrix_lead_id", sa.String(100), nullable=True),
        sa.Column("bitrix_deal_id", sa.String(100), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in (
        "phone",
        "source",
        "manager_id",
        "current_status",
        "sync_status",
        "bitrix_lead_id",
        "bitrix_deal_id",
    ):
        op.create_index(f"ix_leads_{name}", "leads", [name])


def downgrade() -> None:
    op.drop_table("leads")
    op.drop_table("users")
