from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.crm import CrmSource
from app.models.user import User
from app.schemas.source import SourceRead

router = APIRouter()


@router.get("", response_model=list[SourceRead])
def list_sources(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[CrmSource]:
    return list(
        db.scalars(
            select(CrmSource)
            .where(CrmSource.is_active.is_(True))
            .order_by(CrmSource.sort, CrmSource.name)
        )
    )
