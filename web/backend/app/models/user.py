from datetime import date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, Enum, Integer, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.lead import Lead


class UserRole(StrEnum):
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    MANAGER = "manager"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("auth_version >= 1", name="ck_users_auth_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(500))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, values_callable=lambda values: [v.value for v in values]),
        default=UserRole.MANAGER,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    web_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    auth_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bitrix_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    workday_start: Mapped[time] = mapped_column(Time, default=time(9, 0))
    workday_end: Mapped[time] = mapped_column(Time, default=time(18, 0))
    unavailable_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    leads: Mapped[list["Lead"]] = relationship(back_populates="manager")

    def is_available_at(self, moment: datetime, timezone: str = "Europe/Moscow") -> bool:
        local = moment.astimezone(ZoneInfo(timezone))
        return bool(
            self.is_active
            and self.role == UserRole.MANAGER
            and local.weekday() in self.work_days
            and self.workday_start <= local.time().replace(tzinfo=None) <= self.workday_end
            and (self.unavailable_until is None or self.unavailable_until < local.date())
        )
