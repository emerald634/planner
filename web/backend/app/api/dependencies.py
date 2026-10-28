from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.web_sessions import WebSessions

ACCESS_TOKEN_COOKIE = settings.session_cookie_name


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация"
    )
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    try:
        user = WebSessions(db).check(token)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Проверка сессии временно недоступна") from None
    if user is None:
        raise unauthorized
    return user


def require_roles(*roles: UserRole) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return dependency
