from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CrmSource(TimestampMixin, Base):
    __tablename__ = "crm_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CrmStageEvent(Base):
    __tablename__ = "crm_stage_events"
    __table_args__ = (
        UniqueConstraint(
            "lead_id", "entity_type", "external_event_id", name="uq_crm_stage_history_event"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(100))
    external_event_id: Mapped[str] = mapped_column(String(100))
    stage_id: Mapped[str] = mapped_column(String(200))
    stage_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    semantic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    lead = relationship("Lead", back_populates="crm_events")
