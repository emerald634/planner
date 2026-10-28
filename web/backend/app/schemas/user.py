from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    role: UserRole = UserRole.MANAGER
    is_active: bool = True
    web_enabled: bool = True
    telegram_chat_id: str | None = None
    bitrix_user_id: str | None = None
    work_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    workday_start: time = time(9, 0)
    workday_end: time = time(18, 0)
    unavailable_until: date | None = None

    @field_validator("work_days")
    @classmethod
    def validate_work_days(cls, value: list[int]) -> list[int]:
        if not value or any(day < 0 or day > 6 for day in value):
            raise ValueError("Укажите хотя бы один рабочий день от 0 до 6")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_work_hours(self):
        if self.workday_start >= self.workday_end:
            raise ValueError("Начало смены должно быть раньше окончания")
        return self


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    web_enabled: bool | None = None
    telegram_chat_id: str | None = None
    bitrix_user_id: str | None = None
    work_days: list[int] | None = Field(default=None, min_length=1)
    workday_start: time | None = None
    workday_end: time | None = None
    unavailable_until: date | None = None

    @field_validator("is_active", "web_enabled", "role", mode="before")
    @classmethod
    def auth_fields_not_null(cls, value):
        if value is None:
            raise ValueError("Поля доступа не могут быть null")
        return value

    @field_validator("work_days")
    @classmethod
    def validate_work_days(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (not value or any(day < 0 or day > 6 for day in value)):
            raise ValueError("Укажите хотя бы один рабочий день от 0 до 6")
        return sorted(set(value)) if value is not None else None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
