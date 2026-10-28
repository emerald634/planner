import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User, UserRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_first_admin() -> None:
    from app.core.crm_policy import workspace_runtime

    if workspace_runtime() or not settings.first_admin_password:
        raise PermissionError("Explicit standalone bootstrap configuration required")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == settings.first_admin_email.lower())):
            return
        db.add(
            User(
                email=settings.first_admin_email.lower(),
                full_name="Администратор",
                hashed_password=hash_password(settings.first_admin_password),
                role=UserRole.ADMIN,
            )
        )
        db.commit()
        logger.info("Initial administrator created: %s", settings.first_admin_email)


if __name__ == "__main__":
    create_first_admin()
