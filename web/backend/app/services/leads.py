import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crm_policy import workspace_runtime
from app.integrations.telegram import TelegramGateway
from app.models.lead import Lead, LeadSyncStatus
from app.models.user import User, UserRole
from app.repositories.lead import LeadRepository
from app.schemas.lead import LeadCreate, LeadUpdate

logger = logging.getLogger(__name__)


class NoAvailableManagerError(Exception):
    pass


class LeadService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = LeadRepository(db)

    def create(self, data: LeadCreate) -> Lead:
        values = data.model_dump(exclude={"auto_assign"})
        if workspace_runtime():
            values["sync_status"] = LeadSyncStatus.LOCAL
        if data.auto_assign and data.manager_id is None:
            values["manager_id"] = self.select_manager().id
        lead = Lead(**values)
        if lead.manager_id:
            lead.transferred_at = datetime.now(UTC)
        self.repo.add(lead)
        self.db.commit()
        lead = self.repo.get(lead.id)
        logger.info("Lead created", extra={"lead_id": lead.id, "source": lead.source})
        if lead.manager:
            self._notify_manager(lead)
        return lead

    def _notify_manager(self, lead: Lead) -> None:
        manager = lead.manager
        if not settings.telegram_bot_token or not manager.telegram_chat_id:
            return
        text = (
            f"Новый лид: {lead.name or 'Без имени'}\n"
            f"Телефон: {lead.phone}\n"
            f"Источник: {lead.source}"
        )
        if lead.comment:
            text += f"\nКомментарий: {lead.comment}"
        try:
            TelegramGateway(settings.telegram_bot_token).send(manager.telegram_chat_id, text)
        except Exception:
            logger.exception("Cannot send Telegram notification", extra={"lead_id": lead.id})

    def select_manager(self) -> User:
        """Choose the least-loaded available manager, then the least recently assigned.

        Locks manager rows for the duration of the caller's transaction so concurrent
        lead creations serialize instead of reading the same stale load counts.
        """
        now = datetime.now(UTC)
        managers = self.db.scalars(
            select(User)
            .where(User.role == UserRole.MANAGER, User.is_active.is_(True))
            .with_for_update()
        ).all()
        available = [m for m in managers if m.is_available_at(now, settings.distribution_timezone)]
        if not available:
            raise NoAvailableManagerError("Сейчас нет менеджеров на смене")
        manager_ids = [m.id for m in available]
        load = dict(
            self.db.execute(
                select(Lead.manager_id, func.count(Lead.id))
                .where(Lead.manager_id.in_(manager_ids))
                .group_by(Lead.manager_id)
            ).all()
        )
        last_assigned = dict(
            self.db.execute(
                select(Lead.manager_id, func.max(Lead.transferred_at))
                .where(Lead.manager_id.in_(manager_ids))
                .group_by(Lead.manager_id)
            ).all()
        )
        return min(
            available,
            key=lambda m: (
                load.get(m.id, 0),
                last_assigned[m.id].timestamp() if last_assigned.get(m.id) else float("-inf"),
                m.id,
            ),
        )

    def update(self, lead: Lead, data: LeadUpdate) -> Lead:
        changes = data.model_dump(exclude_unset=True)
        # Neither the workspace API nor a legacy UI can turn a local-only row
        # into export work. CRM IDs are also not attachable through this runtime.
        if workspace_runtime() or lead.sync_status == LeadSyncStatus.LOCAL:
            if any(key in changes for key in ("sync_status", "bitrix_lead_id", "bitrix_deal_id")):
                from fastapi import HTTPException

                raise HTTPException(422, "Экспорт и привязка CRM через этот интерфейс запрещены")
        if "manager_id" in changes and changes["manager_id"] != lead.manager_id:
            lead.transferred_at = datetime.now(UTC) if changes["manager_id"] else None
        for key, value in changes.items():
            setattr(lead, key, value)
        self.db.commit()
        logger.info("Lead updated", extra={"lead_id": lead.id})
        return self.repo.get(lead.id)
