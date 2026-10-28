from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.lead import Lead


class LeadRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, lead_id: int) -> Lead | None:
        return self.db.scalar(
            select(Lead)
            .options(joinedload(Lead.manager), selectinload(Lead.crm_events))
            .where(Lead.id == lead_id)
        )

    def list(self, *, manager_id: int | None, page: int, page_size: int) -> tuple[list[Lead], int]:
        filters = [] if manager_id is None else [Lead.manager_id == manager_id]
        total = self.db.scalar(select(func.count(Lead.id)).where(*filters)) or 0
        query = (
            select(Lead)
            .options(joinedload(Lead.manager), selectinload(Lead.crm_events))
            .where(*filters)
            .order_by(Lead.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(query)), total

    def add(self, lead: Lead) -> Lead:
        self.db.add(lead)
        self.db.flush()
        return lead

    def delete(self, lead: Lead) -> None:
        self.db.delete(lead)
