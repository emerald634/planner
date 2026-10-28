import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import ACCESS_TOKEN_COOKIE, get_current_user
from app.core.config import settings
from app.core.security import verify_password
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserRead
from app.services.web_sessions import ABSOLUTE_TTL, WebSessions, lock_user

router = APIRouter()

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_MAX_KEYS = 2048


def _capacity(key: str, now: float) -> bool:
    if key in _failed_attempts or len(_failed_attempts) < _LOGIN_MAX_KEYS:
        return True
    for old in list(_failed_attempts):
        if not _failed_attempts[old] or now - _failed_attempts[old][-1] >= _LOGIN_WINDOW_SECONDS:
            _failed_attempts.pop(old, None)
    return len(_failed_attempts) < _LOGIN_MAX_KEYS


def _register_failed_attempt(key: str) -> None:
    now = time.monotonic()
    if not _capacity(key, now):
        return
    recent = [t for t in _failed_attempts[key] if now - t < _LOGIN_WINDOW_SECONDS]
    recent.append(now)
    _failed_attempts[key] = recent


def _is_rate_limited(key: str) -> bool:
    now = time.monotonic()
    if not _capacity(key, now):
        return True
    recent = [t for t in _failed_attempts[key] if now - t < _LOGIN_WINDOW_SECONDS]
    _failed_attempts[key] = recent
    return len(recent) >= _LOGIN_MAX_ATTEMPTS


@router.post("/login", response_model=UserRead)
def login(
    data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> User:
    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{data.email}"
    if _is_rate_limited(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа, попробуйте позже",
        )
    try:
        user = UserRepository(db).get_by_email(data.email)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Вход временно недоступен") from None
    snapshot = (user.id, user.hashed_password, user.auth_version, user.email) if user else None
    allowed = bool(user and user.is_active and user.web_enabled)
    db.rollback()  # End read transaction before expensive Argon2 verification.
    if not allowed or not snapshot or not verify_password(data.password, snapshot[1]):
        _register_failed_attempt(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль"
        )
    try:
        user = lock_user(db, snapshot[0])
        if (
            not user
            or not user.is_active
            or not user.web_enabled
            or (user.hashed_password, user.auth_version, user.email) != snapshot[1:]
        ):
            db.rollback()
            raise HTTPException(status_code=401, detail="Данные входа изменились, повторите вход")
        token = WebSessions(db).issue_locked(user)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Вход временно недоступен") from None
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=int(ABSOLUTE_TTL.total_seconds()),
        path="/",
    )
    response.delete_cookie(key="access_token", path="/")  # Legacy JWT is never accepted.
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    try:
        WebSessions(db).logout(request.cookies.get(ACCESS_TOKEN_COOKIE))
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Выход не подтверждён, повторите попытку"
        ) from None
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(key="access_token", path="/")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
