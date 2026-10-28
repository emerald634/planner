"""Server-side web credentials. All timestamps represent UTC instants."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebSession(Base):
    __tablename__ = "web_sessions"
    __table_args__ = (
        CheckConstraint("auth_version >= 1", name="ck_web_sessions_version"),
        CheckConstraint("length(token_digest) = 64", name="ck_web_sessions_digest"),
        CheckConstraint("last_visited_at >= issued_at", name="ck_web_sessions_visit"),
        CheckConstraint("last_checked_at >= last_visited_at", name="ck_web_sessions_checked"),
        CheckConstraint("absolute_expires_at > issued_at", name="ck_web_sessions_expiry"),
        Index("ix_web_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_web_sessions_expiry", "absolute_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
