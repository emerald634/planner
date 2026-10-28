"""Add Bitrix sources and CRM entity monitoring."""

import sqlalchemy as sa

from alembic import op

revision = "0003_bitrix_sync"
down_revision = "0002_manager_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_crm_sources_external_id", "crm_sources", ["external_id"])
    for name, type_ in (
        ("bitrix_lead_status_id", sa.String(200)),
        ("bitrix_lead_status_name", sa.String(300)),
        ("bitrix_deal_stage_id", sa.String(200)),
        ("bitrix_deal_stage_name", sa.String(300)),
        ("bitrix_deal_category_id", sa.String(100)),
        ("bitrix_deal_stage_semantic", sa.String(50)),
        ("last_crm_sync_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("leads", sa.Column(name, type_, nullable=True))
    op.add_column(
        "leads", sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "leads", sa.Column("next_crm_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "crm_stage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("external_event_id", sa.String(100), nullable=False),
        sa.Column("stage_id", sa.String(200), nullable=False),
        sa.Column("stage_name", sa.String(300), nullable=True),
        sa.Column("semantic", sa.String(50), nullable=True),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "lead_id", "entity_type", "external_event_id", name="uq_crm_stage_history_event"
        ),
    )
    op.create_index("ix_crm_stage_events_lead_id", "crm_stage_events", ["lead_id"])


def downgrade() -> None:
    op.drop_table("crm_stage_events")
    for name in (
        "next_crm_retry_at",
        "sync_attempts",
        "last_crm_sync_at",
        "bitrix_deal_stage_semantic",
        "bitrix_deal_category_id",
        "bitrix_deal_stage_name",
        "bitrix_deal_stage_id",
        "bitrix_lead_status_name",
        "bitrix_lead_status_id",
    ):
        op.drop_column("leads", name)
    op.drop_table("crm_sources")
