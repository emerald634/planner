from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.users import UserService

router = APIRouter()


@router.get("", response_model=list[UserRead])
def list_users(
    role: UserRole | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)),
) -> list[User]:
    return UserRepository(db).list(role=role)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    try:
        return UserService(db).create(data)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Пользователь с таким email уже существует"
        ) from None


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)),
) -> User:
    user = UserRepository(db).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    user = UserRepository(db).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    try:
        return UserService(db).update(user, data)
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Пользователь не найден") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Пользователь с таким email уже существует"
        ) from None


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.ADMIN)),
) -> Response:
    if actor.id == user_id:
        raise HTTPException(status_code=400, detail="Нельзя удалить собственную учетную запись")
    repo = UserRepository(db)
    user = repo.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    repo.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
