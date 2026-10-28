"""Explicit web-to-Planner identity; no seed, guessing, or role escalation."""

from sqlalchemy import Boolean, ForeignKey, Integer, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceLink(Base):
    __tablename__ = "workspace_links"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    employee_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    can_confirm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
