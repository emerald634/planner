import json
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.crm_policy import require_legacy_export
from app.integrations.bitrix24 import Bitrix24Gateway
from app.models.crm import CrmSource, CrmStageEvent
from app.models.lead import Lead, LeadSyncStatus

logger = logging.getLogger(__name__)

MAX_BITRIX_SYNC_ATTEMPTS = 10
# Bitrix24 webhooks are limited to ~2 requests/second; pacing calls and batching
# each cycle keeps a large backlog from bursting past that limit.
BITRIX_REQUEST_DELAY_SECONDS = 0.5
BITRIX_SYNC_BATCH_SIZE = 20


def _throttle(index: int, total: int) -> None:
    if index < total - 1:
        time.sleep(BITRIX_REQUEST_DELAY_SECONDS)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class BitrixSyncService:
    def __init__(self, db: Session, gateway: Bitrix24Gateway):
        self.db = db
        self.gateway = gateway
        self._status_cache: dict[str, dict[str, str]] = {}

    def sync_sources(self) -> int:
        remote = self.gateway.list_sources()
        existing = {
            source.external_id: source for source in self.db.scalars(select(CrmSource)).all()
        }
        for source in existing.values():
            source.is_active = False
        for item in remote:
            external_id = str(item["STATUS_ID"])
            source = existing.get(external_id)
            if source is None:
                source = CrmSource(external_id=external_id, name=str(item["NAME"]))
                self.db.add(source)
            source.name = str(item["NAME"])
            source.sort = int(item.get("SORT") or 0)
            source.is_active = True
        self.db.commit()
        logger.info("Bitrix sources synchronized: %s", len(remote))
        return len(remote)

    def create_pending_leads(self) -> int:
        require_legacy_export()
        now = datetime.now(UTC)
        leads = self.db.scalars(
            select(Lead)
            .options(joinedload(Lead.manager))
            .where(
                Lead.bitrix_lead_id.is_(None),
                Lead.sync_status.in_([LeadSyncStatus.PENDING, LeadSyncStatus.FAILED]),
                or_(Lead.next_crm_retry_at.is_(None), Lead.next_crm_retry_at <= now),
            )
            .order_by(Lead.created_at)
            .limit(BITRIX_SYNC_BATCH_SIZE)
        ).all()
        created = 0
        for index, lead in enumerate(leads):
            try:
                if not lead.manager or not lead.manager.bitrix_user_id:
                    raise ValueError("У назначенного менеджера не указан Bitrix User ID")
                crm_lead = self.gateway.create_lead(
                    phone=lead.phone,
                    name=lead.name,
                    comment=lead.comment,
                    responsible_id=lead.manager.bitrix_user_id,
                    source_id=lead.source,
                )
                lead.bitrix_lead_id = crm_lead.lead_id
                lead.sync_status = LeadSyncStatus.SYNCED
                lead.sync_error = None
                lead.sync_attempts = 0
                lead.next_crm_retry_at = None
                lead.last_crm_sync_at = datetime.now(UTC)
                self.db.commit()
                created += 1
            except Exception as exc:
                self.db.rollback()
                current = self.db.get(Lead, lead.id)
                if current:
                    current.sync_attempts += 1
                    current.sync_error = str(exc)[:2000]
                    current.last_crm_sync_at = now
                    if current.sync_attempts >= MAX_BITRIX_SYNC_ATTEMPTS:
                        current.sync_status = LeadSyncStatus.ABANDONED
                        current.next_crm_retry_at = None
                        logger.error(
                            "Giving up on Bitrix lead %s after %s attempts",
                            lead.id,
                            current.sync_attempts,
                        )
                    else:
                        current.sync_status = LeadSyncStatus.FAILED
                        delay = min(3600, 30 * (2 ** min(current.sync_attempts - 1, 7)))
                        current.next_crm_retry_at = now + timedelta(seconds=delay)
                    self.db.commit()
                logger.exception("Cannot create Bitrix lead %s", lead.id)
            _throttle(index, len(leads))
        return created

    def monitor_entities(self) -> int:
        leads = self.db.scalars(
            select(Lead)
            .where(Lead.bitrix_lead_id.is_not(None))
            .order_by(Lead.last_crm_sync_at.asc().nulls_first())
            .limit(BITRIX_SYNC_BATCH_SIZE)
        ).all()
        lead_statuses = self._status_map("STATUS")
        checked = 0
        for index, lead in enumerate(leads):
            try:
                crm_lead = self.gateway.get_lead(lead.bitrix_lead_id or "")
                lead_stage = str(crm_lead.get("STATUS_ID") or "")
                lead_semantic = str(crm_lead.get("STATUS_SEMANTIC_ID") or "") or None
                if lead_stage and lead_stage != lead.bitrix_lead_status_id:
                    lead.bitrix_lead_status_id = lead_stage
                    lead.bitrix_lead_status_name = lead_statuses.get(lead_stage, lead_stage)
                    lead.current_status = f"lead:{lead_stage}"
                self._sync_stage_history(
                    lead, "lead", lead.bitrix_lead_id or "", 1, lead_statuses
                )

                if not lead.bitrix_deal_id and (
                    lead_stage == "CONVERTED" or lead_semantic == "S"
                ):
                    deal = self.gateway.find_deal_by_lead(lead.bitrix_lead_id or "")
                    if deal:
                        lead.bitrix_deal_id = str(deal["ID"])

                if lead.bitrix_deal_id:
                    self._monitor_deal(lead)
                lead.last_crm_sync_at = datetime.now(UTC)
                lead.sync_error = None
                self.db.commit()
                checked += 1
            except Exception as exc:
                self.db.rollback()
                current = self.db.get(Lead, lead.id)
                if current:
                    current.sync_error = str(exc)[:2000]
                    current.last_crm_sync_at = datetime.now(UTC)
                    self.db.commit()
                logger.exception("Cannot monitor Bitrix entities for lead %s", lead.id)
            _throttle(index, len(leads))
        return checked

    def _monitor_deal(self, lead: Lead) -> None:
        deal = self.gateway.get_deal(lead.bitrix_deal_id or "")
        stage_id = str(deal.get("STAGE_ID") or "")
        category_id = str(deal.get("CATEGORY_ID") or "0")
        entity_id = "DEAL_STAGE" if category_id == "0" else f"DEAL_STAGE_{category_id}"
        stages = self._status_map(entity_id)
        semantic = str(deal.get("STAGE_SEMANTIC_ID") or "") or None
        if stage_id and stage_id != lead.bitrix_deal_stage_id:
            lead.bitrix_deal_stage_id = stage_id
            lead.bitrix_deal_stage_name = stages.get(stage_id, stage_id)
            lead.bitrix_deal_category_id = category_id
            lead.bitrix_deal_stage_semantic = semantic
            lead.current_status = f"deal:{stage_id}"
        self._sync_stage_history(lead, "deal", lead.bitrix_deal_id or "", 2, stages)

    def _status_map(self, entity_id: str) -> dict[str, str]:
        if entity_id not in self._status_cache:
            self._status_cache[entity_id] = {
                str(item["STATUS_ID"]): str(item["NAME"])
                for item in self.gateway.list_statuses(entity_id)
            }
        return self._status_cache[entity_id]

    def _sync_stage_history(
        self,
        lead: Lead,
        entity_type: str,
        external_id: str,
        entity_type_id: int,
        names: dict[str, str],
    ) -> None:
        existing = set(
            self.db.scalars(
                select(CrmStageEvent.external_event_id).where(
                    CrmStageEvent.lead_id == lead.id,
                    CrmStageEvent.entity_type == entity_type,
                )
            )
        )
        for item in self.gateway.list_stage_history(entity_type_id, external_id):
            event_id = str(item["ID"])
            if event_id in existing:
                continue
            stage_id = str(item.get("STATUS_ID") or item.get("STAGE_ID") or "")
            semantic = item.get("STATUS_SEMANTIC_ID") or item.get("STAGE_SEMANTIC_ID")
            self.db.add(
                CrmStageEvent(
                    lead_id=lead.id,
                    entity_type=entity_type,
                    external_id=external_id,
                    external_event_id=event_id,
                    stage_id=stage_id,
                    stage_name=names.get(stage_id, stage_id),
                    semantic=str(semantic) if semantic else None,
                    moved_at=_parse_datetime(item.get("CREATED_TIME")),
                    payload=json.dumps(item, ensure_ascii=False, default=str),
                )
            )
