from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import WorkspaceLink


def actor_dependency(store, authorized_ids):
    def actor(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        user_id, role = user.id, user.role
        if role not in {"manager", "supervisor"}:
            raise HTTPException(403, "Права Planner отдельно не назначены.")
        link = db.get(WorkspaceLink, user_id)
        if link is None:
            db.rollback()
            raise HTTPException(403, "Нет подтверждённой привязки сотрудника.")
        employee_id, can_confirm = link.employee_id, link.can_confirm
        # No canonical DB transaction/connection held during SQLite/CRM I/O.
        db.rollback()
        with store.connection() as connection:
            employee = connection.execute(
                "SELECT * FROM employees WHERE id=? AND active=1", (employee_id,)
            ).fetchone()
        if employee is None or employee["role"] != role:
            raise HTTPException(403, "Сотрудник отключён или привязка конфликтует.")
        actor = dict(employee)
        actor["_web_user_id"] = user_id
        actor["_can_confirm"] = bool(can_confirm and employee["telegram_id"] in authorized_ids)
        return actor

    return actor
