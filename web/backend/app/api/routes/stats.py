from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.lead import Lead, LeadSyncStatus
from app.models.user import User, UserRole

router = APIRouter()


class StatsRead(BaseModel):
    total_leads: int
    assigned_leads: int
    pending_sync: int
    managers: int


@router.get("/summary", response_model=StatsRead)
def summary(db: Session = Depends(get_db), actor: User = Depends(get_current_user)) -> StatsRead:
    lead_filter = [] if actor.role != UserRole.MANAGER else [Lead.manager_id == actor.id]
    total = db.scalar(select(func.count(Lead.id)).where(*lead_filter)) or 0
    assigned = (
        db.scalar(select(func.count(Lead.id)).where(*lead_filter, Lead.manager_id.is_not(None)))
        or 0
    )
    pending = (
        db.scalar(
            select(func.count(Lead.id)).where(
                *lead_filter, Lead.sync_status == LeadSyncStatus.PENDING
            )
        )
        or 0
    )
    managers = (
        db.scalar(select(func.count(User.id)).where(User.role == UserRole.MANAGER, User.is_active))
        or 0
    )
    return StatsRead(
        total_leads=total, assigned_leads=assigned, pending_sync=pending, managers=managers
    )
