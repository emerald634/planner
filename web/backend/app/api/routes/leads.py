from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.crm import CrmSource
from app.models.lead import Lead
from app.models.user import User, UserRole
from app.repositories.lead import LeadRepository
from app.repositories.user import UserRepository
from app.schemas.lead import LeadCreate, LeadList, LeadRead, LeadUpdate
from app.services.leads import LeadService, NoAvailableManagerError

router = APIRouter()


def ensure_manager(db: Session, manager_id: int | None) -> None:
    if manager_id is None:
        return
    manager = UserRepository(db).get(manager_id)
    if not manager or manager.role != UserRole.MANAGER or not manager.is_active:
        raise HTTPException(status_code=422, detail="Назначенный менеджер не найден или неактивен")


def ensure_source(db: Session, source_id: str) -> None:
    source = db.scalar(
        select(CrmSource).where(
            CrmSource.external_id == source_id, CrmSource.is_active.is_(True)
        )
    )
    if not source:
        raise HTTPException(status_code=422, detail="Источник не найден в справочнике Bitrix24")


def visible_lead(db: Session, lead_id: int, actor: User) -> Lead:
    lead = LeadRepository(db).get(lead_id)
    if not lead or (actor.role == UserRole.MANAGER and lead.manager_id != actor.id):
        raise HTTPException(status_code=404, detail="Лид не найден")
    return lead


@router.get("", response_model=LeadList)
def list_leads(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> LeadList:
    manager_id = actor.id if actor.role == UserRole.MANAGER else None
    items, total = LeadRepository(db).list(manager_id=manager_id, page=page, page_size=page_size)
    return LeadList(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    data: LeadCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)),
) -> Lead:
    ensure_manager(db, data.manager_id)
    ensure_source(db, data.source)
    try:
        return LeadService(db).create(data)
    except NoAvailableManagerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Lead:
    return visible_lead(db, lead_id, actor)


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)),
) -> Lead:
    lead = visible_lead(db, lead_id, actor)
    if "manager_id" in data.model_fields_set:
        ensure_manager(db, data.manager_id)
    return LeadService(db).update(lead, data)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.ADMIN)),
) -> Response:
    repo = LeadRepository(db)
    repo.delete(visible_lead(db, lead_id, actor))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
