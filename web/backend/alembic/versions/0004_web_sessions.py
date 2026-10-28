"""Add shared server-side web sessions; PostgreSQL, no business-data rewrite."""

import sqlalchemy as sa

from alembic import op

revision = "0004_web_sessions"
down_revision = "0003_bitrix_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "users", sa.Column("web_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.create_check_constraint("ck_users_auth_version", "users", "auth_version >= 1")
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_visited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("auth_version >= 1", name="ck_web_sessions_version"),
        sa.CheckConstraint("length(token_digest) = 64", name="ck_web_sessions_digest"),
        sa.CheckConstraint("last_visited_at >= issued_at", name="ck_web_sessions_visit"),
        sa.CheckConstraint("last_checked_at >= last_visited_at", name="ck_web_sessions_checked"),
        sa.CheckConstraint("absolute_expires_at > issued_at", name="ck_web_sessions_expiry"),
    )
    op.create_index("ix_web_sessions_user_revoked", "web_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_web_sessions_expiry", "web_sessions", ["absolute_expires_at"])


def downgrade() -> None:
    # Destructive to auth state; NEVER a safe application rollback after cutover.
    op.drop_table("web_sessions")
    op.drop_constraint("ck_users_auth_version", "users", type_="check")
    op.drop_column("users", "web_enabled")
    op.drop_column("users", "auth_version")
