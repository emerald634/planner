from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.web_sessions import lock_user, revoke_all, utcnow


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def create(self, data: UserCreate) -> User:
        values = data.model_dump(exclude={"password"})
        values["email"] = data.email.lower()
        user = User(**values, hashed_password=hash_password(data.password))
        self.repo.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(self, user: User, data: UserUpdate) -> User:
        changes = data.model_dump(exclude_unset=True)
        password = changes.pop("password", None)
        # Hash before acquiring the target user lock. Auth dependency has already
        # committed its short check, so no auth locks survive into Argon2 here.
        new_hash = hash_password(password) if password else None
        user = lock_user(self.db, user.id)
        if user is None:
            raise LookupError("User was deleted concurrently")
        sensitive = bool(password) or any(
            key in changes and changes[key] != getattr(user, key)
            for key in ("is_active", "web_enabled", "role")
        )
        if password:
            user.hashed_password = new_hash
        for key, value in changes.items():
            setattr(user, key, value.lower() if key == "email" else value)
        if sensitive:
            revoke_all(self.db, user, utcnow())
        self.db.commit()
        self.db.refresh(user)
        return user
