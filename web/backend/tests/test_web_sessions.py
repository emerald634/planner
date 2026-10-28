"""Synthetic session contracts; SQLite does NOT test PostgreSQL row locks."""

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from alembic import command
from app.api.dependencies import ACCESS_TOKEN_COOKIE
from app.api.routes import auth
from app.core.config import Settings, settings
from app.core.security import hash_password
from app.main import app
from app.models.user import User, UserRole
from app.models.web_session import WebSession
from app.schemas.user import UserUpdate
from app.services import web_sessions
from app.services.users import UserService
from app.services.web_sessions import ABSOLUTE_TTL, WebSessions, digest, lock_user, revoke_all
from tests.conftest import TestingSession, login_as

START = datetime(2026, 1, 1, tzinfo=UTC)
MANAGER = "manager@testing.example.com"


@pytest.fixture
def clock(monkeypatch):
    value = [START]
    monkeypatch.setattr(web_sessions, "utcnow", lambda: value[0])
    return value


def record(db):
    return db.scalar(select(WebSession).order_by(WebSession.issued_at))


def login(client, email=MANAGER, password="password123"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_cookie_digest_and_no_secret_outputs(client, db, clock, caplog):
    response = login(client)
    assert response.status_code == 200
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    assert len(token) == 43
    row = record(db)
    assert row.token_digest == digest(token) and row.token_digest != token
    assert web_sessions.utc(row.absolute_expires_at) == START + ABSOLUTE_TTL
    header = response.headers.get_list("set-cookie")[0].lower()
    assert "httponly" in header and "max-age=7776000" in header and "path=/" in header
    assert "domain=" not in header and "samesite=lax" in header
    assert token not in response.text + caplog.text
    assert "password123" not in response.text + caplog.text
    assert "hashed_password" not in response.text


@pytest.mark.parametrize(
    "email,password", [(MANAGER, "wrong-password"), ("absent@testing.example.com", "password123")]
)
def test_invalid_login(client, email, password):
    assert login(client, email, password).status_code == 401
    assert not client.cookies.get(ACCESS_TOKEN_COOKIE)


@pytest.mark.parametrize("field", ["is_active", "web_enabled"])
def test_disabled_login(client, db, field):
    user = db.scalar(select(User).where(User.email == MANAGER))
    setattr(user, field, False)
    db.commit()
    assert login(client).status_code == 401


@pytest.mark.parametrize("token", [None, "forged", "A" * 43, "x" * 5000, "expired-jwt"])
def test_unrecognized_cookie_and_telegram_are_denied(client, token):
    if token == "expired-jwt":
        token = jwt.encode(
            {"sub": "1", "exp": START + timedelta(days=5000)},
            "synthetic-only-signing-key-at-least-32-bytes",
            algorithm="HS256",
        )
    if token:
        client.cookies.set(ACCESS_TOKEN_COOKIE, token)
        client.cookies.set("access_token", token)
    assert (
        client.get("/api/v1/auth/me", headers={"X-Telegram-Init-Data": "synthetic"}).status_code
        == 401
    )


@pytest.mark.parametrize("delta,allowed", [(timedelta(days=29), True), (timedelta(days=30), False)])
def test_idle_boundary(client, clock, delta, allowed):
    login_as(client, MANAGER)
    clock[0] += delta
    assert client.get("/api/v1/auth/me").status_code == (200 if allowed else 401)


@pytest.mark.parametrize(
    "delta,allowed", [(timedelta(days=89, hours=23), True), (timedelta(days=90), False)]
)
def test_absolute_boundary_with_recent_visit(client, db, clock, delta, allowed):
    login_as(client, MANAGER)
    row = record(db)
    row.last_visited_at = row.last_checked_at = START + timedelta(days=89)
    db.commit()
    clock[0] = START + delta
    assert client.get("/api/v1/auth/me").status_code == (200 if allowed else 401)


def test_polling_never_visits_but_service_contract_does(client, db, clock):
    login_as(client, MANAGER)
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    clock[0] += timedelta(days=20)
    for path in ("/auth/me", "/leads", "/auth/me"):
        assert client.get("/api/v1" + path).status_code == 200
    db.expire_all()
    assert web_sessions.utc(record(db).last_visited_at) == START
    assert WebSessions(db).check(token, foreground=True) is not None
    db.expire_all()
    row = record(db)
    assert web_sessions.utc(row.last_visited_at) == clock[0]
    assert web_sessions.utc(row.absolute_expires_at) == START + ABSOLUTE_TTL
    assert client.post("/api/v1/auth/visit").status_code == 404
    assert not any("planner-poc" in getattr(r, "path", "") for r in app.routes)


def test_observed_expiry_and_backward_clock_never_revive(client, db, clock):
    login_as(client, MANAGER)
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    clock[0] += timedelta(days=30)
    assert WebSessions(db).check(token, foreground=True) is None
    clock[0] = START
    assert WebSessions(db).check(token, foreground=True) is None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_backward_clock_during_lifetime_is_terminal(client, clock):
    login_as(client, MANAGER)
    clock[0] += timedelta(days=1)
    assert client.get("/api/v1/auth/me").status_code == 200
    clock[0] = START
    assert client.get("/api/v1/auth/me").status_code == 401
    clock[0] += timedelta(days=2)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_accidentally_extended_stored_expiry_cannot_extend_ninety_days(client, db, clock):
    login_as(client, MANAGER)
    row = record(db)
    row.absolute_expires_at = START + timedelta(days=365)
    row.last_visited_at = row.last_checked_at = START + timedelta(days=89)
    db.commit()
    clock[0] = START + timedelta(days=90)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_restart_is_new_db_session_not_memory_cache(client, clock):
    login_as(client, MANAGER)
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    with TestingSession() as first:
        assert WebSessions(first).check(token)
    with TestingSession() as after_restart:
        assert WebSessions(after_restart).check(token)


def test_logout_replay_retry_and_independent_devices(client, db):
    other = TestClient(app)
    login_as(client, MANAGER)
    first = client.cookies.get(ACCESS_TOKEN_COOKIE)
    login_as(other, MANAGER)
    second = other.cookies.get(ACCESS_TOKEN_COOKIE)
    assert first != second
    for _ in range(2):
        client.cookies.set(ACCESS_TOKEN_COOKIE, first)
        assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set(ACCESS_TOKEN_COOKIE, first)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert other.get("/api/v1/auth/me").status_code == 200
    db.expire_all()
    assert db.scalar(select(WebSession).where(WebSession.token_digest == digest(first))).revoked_at


@pytest.mark.parametrize(
    "changes",
    [
        {"is_active": False},
        {"web_enabled": False},
        {"password": "different-password123"},
        {"role": "supervisor"},
    ],
)
def test_sensitive_changes_revoke_all_and_reenable_never_revives(client, db, changes):
    login_as(client, MANAGER)
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    user = db.scalar(select(User).where(User.email == MANAGER))
    version = user.auth_version
    UserService(db).update(user, UserUpdate(**changes))
    assert user.auth_version == version + 1
    assert record(db).revoked_at is not None
    if "is_active" in changes or "web_enabled" in changes:
        UserService(db).update(user, UserUpdate(**{key: True for key in changes}))
    client.cookies.set(ACCESS_TOKEN_COOKIE, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_version_mismatch_alone_is_terminal(client, db):
    login_as(client, MANAGER)
    user = db.scalar(select(User).where(User.email == MANAGER))
    user.auth_version += 1
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("change", ["disable", "password", "version", "reenable"])
def test_interleaved_login_rechecks_after_unlocked_hash(client, db, monkeypatch, change):
    original = auth.verify_password

    def verify(password, stored):
        # Simulates a different transaction committing while Argon2 runs.
        user = db.scalar(select(User).where(User.email == MANAGER))
        locked = lock_user(db, user.id)
        if change == "password":
            locked.hashed_password = hash_password("new-synthetic-password")
        elif change == "disable":
            locked.web_enabled = False
        revoke_all(db, locked, web_sessions.utcnow())
        db.commit()
        return original(password, stored)

    monkeypatch.setattr(auth, "verify_password", verify)
    response = login(client)
    assert response.status_code == 401
    assert not client.cookies.get(ACCESS_TOKEN_COOKIE)
    assert record(db) is None


def test_failed_logout_commit_is_not_success_and_retry_revokes(client, db, monkeypatch):
    login_as(client, MANAGER)
    token = client.cookies.get(ACCESS_TOKEN_COOKIE)
    original = Session.commit

    def fail(session):
        raise SQLAlchemyError("synthetic failure")

    monkeypatch.setattr(Session, "commit", fail)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert token not in response.text
    monkeypatch.setattr(Session, "commit", original)
    db.expire_all()
    assert record(db).revoked_at is None
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set(ACCESS_TOKEN_COOKIE, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_failed_issue_commit_never_sends_cookie(client, monkeypatch):
    monkeypatch.setattr(
        Session, "commit", lambda self: (_ for _ in ()).throw(SQLAlchemyError("synthetic"))
    )
    response = login(client)
    assert response.status_code == 503
    assert not client.cookies.get(ACCESS_TOKEN_COOKIE)


def test_manager_supervisor_admin_rules(client, db):
    login_as(client, MANAGER)
    assert client.get("/api/v1/users").status_code == 403
    user = db.scalar(select(User).where(User.email == MANAGER))
    UserService(db).update(user, UserUpdate(role=UserRole.SUPERVISOR))
    login_as(client, MANAGER)
    assert client.get("/api/v1/users").status_code == 200
    assert client.post("/api/v1/users", json={}).status_code == 403
    login_as(client, "admin@testing.example.com")
    assert client.get("/api/v1/users").status_code == 200


def test_admin_patch_password_revokes_existing_device(client, db):
    manager_device = TestClient(app)
    login_as(manager_device, MANAGER)
    login_as(client, "admin@testing.example.com")
    user = db.scalar(select(User).where(User.email == MANAGER))
    response = client.patch(f"/api/v1/users/{user.id}", json={"password": "synthetic-replacement"})
    assert response.status_code == 200
    assert manager_device.get("/api/v1/auth/me").status_code == 401
    assert login(manager_device).status_code == 401
    assert login(manager_device, password="synthetic-replacement").status_code == 200


def test_non_sensitive_update_preserves_password_and_session(client, db):
    login_as(client, MANAGER)
    user = db.scalar(select(User).where(User.email == MANAGER))
    original = (user.id, user.hashed_password, user.auth_version, user.role, user.is_active)
    UserService(db).update(user, UserUpdate(full_name="Synthetic Renamed"))
    assert (user.id, user.hashed_password, user.auth_version, user.role, user.is_active) == original
    assert client.get("/api/v1/auth/me").status_code == 200


def test_sensitive_change_commit_failure_rolls_back_state_and_revoke(client, db, monkeypatch):
    login_as(client, MANAGER)
    user = db.scalar(select(User).where(User.email == MANAGER))
    version = user.auth_version
    original = Session.commit
    monkeypatch.setattr(
        Session, "commit", lambda self: (_ for _ in ()).throw(SQLAlchemyError("synthetic"))
    )
    with pytest.raises(SQLAlchemyError):
        UserService(db).update(user, UserUpdate(web_enabled=False))
    db.rollback()
    monkeypatch.setattr(Session, "commit", original)
    db.refresh(user)
    assert user.web_enabled and user.auth_version == version
    assert record(db).revoked_at is None
    assert client.get("/api/v1/auth/me").status_code == 200


def test_database_read_failure_fails_closed(client, monkeypatch):
    monkeypatch.setattr(
        Session, "scalar", lambda *a, **k: (_ for _ in ()).throw(SQLAlchemyError("synthetic"))
    )
    assert login(client).status_code == 503
    client.cookies.set(ACCESS_TOKEN_COOKIE, "A" * 43)
    assert client.get("/api/v1/auth/me").status_code == 503
    assert client.post("/api/v1/auth/logout").status_code == 503


@pytest.mark.parametrize("field", ["web_enabled", "is_active", "role"])
def test_null_auth_mutations_rejected(client, field):
    login_as(client, "admin@testing.example.com")
    assert client.patch("/api/v1/users/2", json={field: None}).status_code == 422


def test_secure_host_cookie_ignores_untrusted_forwarded_headers(monkeypatch):
    from app.api import dependencies

    monkeypatch.setattr(auth, "ACCESS_TOKEN_COOKIE", "__Host-leadflow_session")
    monkeypatch.setattr(dependencies, "ACCESS_TOKEN_COOKIE", "__Host-leadflow_session")
    monkeypatch.setattr(settings, "cookie_secure", True)
    with TestClient(app, base_url="https://synthetic.invalid") as browser:
        response = browser.post(
            "/api/v1/auth/login",
            json={"email": MANAGER, "password": "password123"},
            headers={"X-Forwarded-Proto": "http"},
        )
        header = response.headers.get_list("set-cookie")[0]
        assert "__Host-leadflow_session=" in header and "Secure" in header
        assert "Domain" not in header and "HttpOnly" in header and "Path=/" in header
        assert browser.get("/api/v1/auth/me").status_code == 200
        assert browser.post("/api/v1/auth/logout").status_code == 204


def production_config(**overrides):
    values = dict(
        session_environment="production",
        cookie_secure=True,
        public_app_url="https://synthetic.invalid",
        frontend_url="https://synthetic.invalid",
        database_url="postgresql+psycopg://synthetic@127.0.0.1/synthetic",
        first_admin_password="synthetic-nondefault-password",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"cookie_secure": False},
        {"public_app_url": "http://synthetic.invalid"},
        {"database_url": "sqlite://"},
        {"first_admin_password": "ChangeMe123!"},
    ],
)
def test_production_bad_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        production_config(**overrides)


def test_host_cookie_and_local_mode_configuration():
    assert production_config().session_cookie_name == "__Host-leadflow_session"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, session_environment="local", public_app_url="https://public.invalid"
        )


def test_migration_offline_pg_ddl_only_no_database(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url", "postgresql+psycopg://synthetic@127.0.0.1/synthetic"
    )
    output = io.StringIO()
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "head", sql=True)
    ddl = output.getvalue()
    assert "0004_web_sessions" in ddl and "TIMESTAMP WITH TIME ZONE" in ddl
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in ddl
    assert "UNIQUE (token_digest)" in ddl
    assert (
        "UPDATE users" not in ddl
        and "hashed_password"
        not in ddl.split("-- Running upgrade 0003_bitrix_sync -> 0004_web_sessions")[1]
    )
    query = str(select(User).with_for_update().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in query
