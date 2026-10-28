from datetime import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import _failed_attempts
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.crm import CrmSource
from app.models.user import User, UserRole

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_database():
    _failed_attempts.clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestingSession() as db:
        db.add_all(
            [
                CrmSource(external_id=code, name=name, sort=index)
                for index, (code, name) in enumerate(
                    [("OTHER", "Другое"), ("website", "Сайт"), ("phone", "Телефон")]
                )
            ]
        )
        db.add_all(
            [
                User(
                    email="admin@testing.example.com",
                    full_name="Admin",
                    hashed_password=hash_password("password123"),
                    role=UserRole.ADMIN,
                ),
                User(
                    email="manager@testing.example.com",
                    full_name="Manager One",
                    hashed_password=hash_password("password123"),
                    role=UserRole.MANAGER,
                    work_days=list(range(7)),
                    workday_start=time(0, 0),
                    workday_end=time(23, 59),
                ),
                User(
                    email="second@testing.example.com",
                    full_name="Manager Two",
                    hashed_password=hash_password("password123"),
                    role=UserRole.MANAGER,
                    work_days=list(range(7)),
                    workday_start=time(0, 0),
                    workday_end=time(23, 59),
                ),
            ]
        )
        db.commit()
    yield


def override_db():
    with TestingSession() as session:
        yield session


app.dependency_overrides[get_db] = override_db


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db() -> Session:
    with TestingSession() as session:
        yield session


def login_as(client: TestClient, email: str) -> None:
    """Logs the given user in on this TestClient, storing the session in its cookie jar."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
