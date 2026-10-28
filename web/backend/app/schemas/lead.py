from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.lead import LeadSyncStatus
from app.schemas.user import UserRead


class LeadBase(BaseModel):
    phone: str = Field(min_length=5, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=5000)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        value = value.strip()
        allowed = set("+0123456789() -")
        if any(char not in allowed for char in value):
            raise ValueError("Недопустимые символы в номере телефона")
        return value


class LeadCreate(LeadBase):
    manager_id: int | None = None
    auto_assign: bool = True


class LeadUpdate(BaseModel):
    phone: str | None = Field(default=None, min_length=5, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=5000)
    manager_id: int | None = None
    current_status: str | None = Field(default=None, max_length=100)
    sync_status: LeadSyncStatus | None = None
    bitrix_lead_id: str | None = None
    bitrix_deal_id: str | None = None


class CrmStageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type: str
    external_id: str
    external_event_id: str
    stage_id: str
    stage_name: str | None
    semantic: str | None
    moved_at: datetime | None
    created_at: datetime


class LeadRead(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    manager_id: int | None
    manager: UserRead | None
    transferred_at: datetime | None
    current_status: str
    sync_status: LeadSyncStatus
    bitrix_lead_id: str | None
    bitrix_deal_id: str | None
    bitrix_lead_status_id: str | None
    bitrix_lead_status_name: str | None
    bitrix_deal_stage_id: str | None
    bitrix_deal_stage_name: str | None
    bitrix_deal_category_id: str | None
    bitrix_deal_stage_semantic: str | None
    last_crm_sync_at: datetime | None
    sync_attempts: int
    next_crm_retry_at: datetime | None
    crm_events: list[CrmStageEventRead] = Field(default_factory=list)
    sync_error: str | None
    created_at: datetime
    updated_at: datetime


class LeadList(BaseModel):
    items: list[LeadRead]
    total: int
    page: int
    page_size: int
