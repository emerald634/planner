import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.services.bitrix_sync as bitrix_sync
from app.integrations.bitrix24 import BitrixObject
from app.models.crm import CrmSource, CrmStageEvent
from app.models.lead import Lead, LeadSyncStatus
from app.models.user import User, UserRole
from app.services.bitrix_sync import (
    BITRIX_SYNC_BATCH_SIZE,
    MAX_BITRIX_SYNC_ATTEMPTS,
    BitrixSyncService,
)


@pytest.fixture(autouse=True)
def standalone_legacy_worker(monkeypatch):
    # These tests explicitly cover the old, separate export runtime.
    monkeypatch.delenv("WORKSPACE_RUNTIME", raising=False)


class FakeBitrixGateway:
    def list_sources(self):
        return [
            {"STATUS_ID": "WEB", "NAME": "Сайт Bitrix", "SORT": "10"},
            {"STATUS_ID": "CALL", "NAME": "Телефон", "SORT": "20"},
        ]

    def create_lead(self, **_kwargs):
        return BitrixObject(lead_id="501")

    def list_statuses(self, entity_id: str):
        if entity_id == "STATUS":
            return [{"STATUS_ID": "CONVERTED", "NAME": "Качественный лид"}]
        return [{"STATUS_ID": "NEW", "NAME": "Новая сделка"}]

    def get_lead(self, _lead_id: str):
        return {
            "ID": "501",
            "STATUS_ID": "CONVERTED",
            "STATUS_SEMANTIC_ID": "S",
            "DATE_MODIFY": "2026-08-10T10:00:00+03:00",
        }

    def find_deal_by_lead(self, _lead_id: str):
        return {"ID": "701"}

    def get_deal(self, _deal_id: str):
        return {
            "ID": "701",
            "LEAD_ID": "501",
            "CATEGORY_ID": "0",
            "STAGE_ID": "NEW",
            "STAGE_SEMANTIC_ID": "P",
            "MOVED_TIME": "2026-08-10T10:01:00+03:00",
        }

    def list_stage_history(self, entity_type_id: int, _owner_id: str):
        if entity_type_id == 1:
            return [
                {
                    "ID": "1001",
                    "STATUS_ID": "CONVERTED",
                    "STATUS_SEMANTIC_ID": "S",
                    "CREATED_TIME": "2026-08-10T10:00:00+03:00",
                }
            ]
        return [
            {
                "ID": "2001",
                "STAGE_ID": "NEW",
                "STAGE_SEMANTIC_ID": "P",
                "CREATED_TIME": "2026-08-10T10:01:00+03:00",
            }
        ]


class FailingGateway:
    def create_lead(self, **_kwargs):
        raise RuntimeError("Bitrix недоступен")


def test_bitrix_sync_abandons_lead_after_max_attempts(db: Session):
    manager = db.scalar(select(User).where(User.role == UserRole.MANAGER))
    assert manager
    manager.bitrix_user_id = "24"
    lead = Lead(
        phone="+79990009999",
        source="WEB",
        manager_id=manager.id,
        sync_attempts=MAX_BITRIX_SYNC_ATTEMPTS - 1,
    )
    db.add(lead)
    db.commit()

    service = BitrixSyncService(db, FailingGateway())
    assert service.create_pending_leads() == 0
    db.refresh(lead)
    assert lead.sync_status == LeadSyncStatus.ABANDONED
    assert lead.sync_attempts == MAX_BITRIX_SYNC_ATTEMPTS
    assert lead.next_crm_retry_at is None

    assert service.create_pending_leads() == 0
    db.refresh(lead)
    assert lead.sync_attempts == MAX_BITRIX_SYNC_ATTEMPTS


def test_bitrix_sync_throttles_and_batches_create_pending_leads(db: Session, monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(bitrix_sync.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    manager = db.scalar(select(User).where(User.role == UserRole.MANAGER))
    assert manager
    manager.bitrix_user_id = "24"
    for i in range(BITRIX_SYNC_BATCH_SIZE + 2):
        db.add(Lead(phone=f"+7999000{i:04d}", source="WEB", manager_id=manager.id))
    db.commit()

    service = BitrixSyncService(db, FakeBitrixGateway())
    assert service.create_pending_leads() == BITRIX_SYNC_BATCH_SIZE
    assert len(sleep_calls) == BITRIX_SYNC_BATCH_SIZE - 1


def test_bitrix_sync_throttles_and_batches_monitor_entities(db: Session, monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(bitrix_sync.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    manager = db.scalar(select(User).where(User.role == UserRole.MANAGER))
    assert manager
    for i in range(BITRIX_SYNC_BATCH_SIZE + 2):
        db.add(
            Lead(
                phone=f"+7999001{i:04d}",
                source="WEB",
                manager_id=manager.id,
                bitrix_lead_id="501",
            )
        )
    db.commit()

    service = BitrixSyncService(db, FakeBitrixGateway())
    assert service.monitor_entities() == BITRIX_SYNC_BATCH_SIZE
    assert len(sleep_calls) == BITRIX_SYNC_BATCH_SIZE - 1


def test_bitrix_sources_creation_and_lead_to_deal_monitoring(db: Session):
    manager = db.scalar(select(User).where(User.role == UserRole.MANAGER))
    assert manager
    manager.bitrix_user_id = "24"
    lead = Lead(phone="+79990001122", source="WEB", manager_id=manager.id)
    db.add(lead)
    db.commit()

    service = BitrixSyncService(db, FakeBitrixGateway())
    assert service.sync_sources() == 2
    active_sources = db.scalars(select(CrmSource).where(CrmSource.is_active)).all()
    assert [source.external_id for source in active_sources] == [
        "WEB",
        "CALL",
    ]
    assert service.create_pending_leads() == 1
    assert lead.bitrix_lead_id == "501"
    assert lead.sync_status == LeadSyncStatus.SYNCED

    assert service.monitor_entities() == 1
    db.refresh(lead)
    assert lead.bitrix_lead_status_id == "CONVERTED"
    assert lead.bitrix_deal_id == "701"
    assert lead.bitrix_deal_stage_id == "NEW"
    assert lead.current_status == "deal:NEW"
    events = list(db.scalars(select(CrmStageEvent).where(CrmStageEvent.lead_id == lead.id)))
    assert [(event.entity_type, event.stage_id) for event in events] == [
        ("lead", "CONVERTED"),
        ("deal", "NEW"),
    ]
    assert service.monitor_entities() == 1
    assert db.scalar(select(func.count(CrmStageEvent.id))) == 2
