"""One session boundary. PostgreSQL lock order: user, then session(s).

Authentication linearizes at the short check transaction: already authorized
requests may finish after logout. No network or password hashing while locked.
Foreground visits are SERVICE-ONLY until a reviewed CSRF protocol is available.
"""

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.web_session import WebSession

ABSOLUTE_TTL = timedelta(days=90)
IDLE_TTL = timedelta(days=30)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    # SQLite test fixtures lose tzinfo; PostgreSQL columns are TIMESTAMPTZ.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def digest(token: str | None) -> str | None:
    if not token or not TOKEN_PATTERN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def lock_user(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def revoke_all(db: Session, user: User, now: datetime) -> None:
    # Caller owns the user lock, including during password/active/role updates.
    user.auth_version += 1
    db.execute(
        update(WebSession)
        .where(WebSession.user_id == user.id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


class WebSessions:
    def __init__(self, db: Session, clock: Callable[[], datetime] | None = None):
        self.db = db
        self.clock = clock or utcnow

    def issue_locked(self, user: User) -> str:
        """Caller must have rechecked verified hash/version under the user lock."""
        now = utc(self.clock())
        token = secrets.token_urlsafe(32)
        self.db.add(
            WebSession(
                user_id=user.id,
                token_digest=digest(token),
                auth_version=user.auth_version,
                issued_at=now,
                last_visited_at=now,
                last_checked_at=now,
                absolute_expires_at=now + ABSOLUTE_TTL,
            )
        )
        self.db.commit()  # No cookie may be sent until this succeeds.
        return token

    def _locked(self, token: str | None) -> tuple[User, WebSession] | None:
        hashed = digest(token)
        if hashed is None:
            return None
        user_id = self.db.scalar(
            select(WebSession.user_id).where(WebSession.token_digest == hashed)
        )
        if user_id is None:
            return None
        user = lock_user(self.db, user_id)
        if user is None:
            return None
        session = self.db.scalar(
            select(WebSession)
            .where(WebSession.token_digest == hashed)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (user, session) if session is not None else None

    def check(self, token: str | None, *, foreground: bool = False) -> User | None:
        pair = self._locked(token)
        if pair is None:
            self.db.rollback()
            return None
        user, session = pair
        now = utc(self.clock())  # After locks: no stale timestamp from queued requests.
        invalid = (
            session.revoked_at is not None
            or not user.is_active
            or not user.web_enabled
            or session.auth_version != user.auth_version
            or now < utc(session.last_checked_at)
            or now >= utc(session.absolute_expires_at)
            or now >= utc(session.issued_at) + ABSOLUTE_TTL
            or now >= utc(session.last_visited_at) + IDLE_TTL
        )
        if invalid:
            if session.revoked_at is None:
                session.revoked_at = now
            self.db.commit()  # Observed expiry/clock regression is permanently terminal.
            return None
        session.last_checked_at = now
        if foreground:
            session.last_visited_at = now
        self.db.commit()
        return user

    def logout(self, token: str | None) -> None:
        pair = self._locked(token)
        if pair is not None and pair[1].revoked_at is None:
            pair[1].revoked_at = utc(self.clock())
        self.db.commit()  # Includes idempotent retries; errors must propagate.
