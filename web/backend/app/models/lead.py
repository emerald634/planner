from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class LeadSyncStatus(StrEnum):
    LOCAL = "local"  # Durable hold: legacy workers select only pending/failed.
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    ABANDONED = "abandoned"


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="manual", index=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    transferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[str] = mapped_column(String(100), default="new", index=True)
    sync_status: Mapped[LeadSyncStatus] = mapped_column(
        Enum(
            LeadSyncStatus,
            native_enum=False,
            values_callable=lambda values: [v.value for v in values],
        ),
        default=LeadSyncStatus.PENDING,
        index=True,
    )
    bitrix_lead_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    bitrix_deal_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    bitrix_lead_status_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bitrix_lead_status_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    bitrix_deal_stage_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bitrix_deal_stage_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    bitrix_deal_category_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bitrix_deal_stage_semantic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_crm_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_crm_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    manager: Mapped["User | None"] = relationship(back_populates="leads")
    crm_events = relationship(
        "CrmStageEvent",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="CrmStageEvent.created_at",
    )
