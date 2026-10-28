"""Actual shared routers/sessions/writer on isolated SQLite, never a live CRM."""

import secrets
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from planner.daily import DailyStore
from planner.distribution_queue import DistributionQueue
from planner.server_migration import migrate_server

from app.api.router import api_router
from app.core.security import hash_password
from app.db.session import get_db
from app.models import User, WorkspaceLink
from tests.conftest import TestingSession, override_db
from workspace.application import register_workspace
from workspace.security import install_security
from workspace.writer import writer_app


class Leads:
    async def get_leads(self, first, last, stage_ids=None):
        from datetime import datetime

        from bitrix import Lead
        from planner.distribution_queue import MOSCOW

        return [
            Lead(
                first.toordinal(),
                datetime(first.year, first.month, first.day, 12, tzinfo=MOSCOW),
                "IN_PROCESS",
            )
        ]

    async def counts_for_dates(self, dates, stage_ids=None):
        return {x: 1 for x in dates}

    async def find_previous_nonempty(self, *a, **kw):
        return None


@pytest.fixture
def runtime(tmp_path):
    store = DailyStore(tmp_path / "planner.db")
    store.initialize()
    migrate_server(store)
    queue = DistributionQueue(tmp_path / "queue.db")
    queue.initialize()
    keys = []
    for name in ("web", "bot"):
        p = tmp_path / (name + ".key")
        p.write_text(secrets.token_urlsafe(32), encoding="ascii")
        p.chmod(0o600)
        keys.append(p)
    cfg = SimpleNamespace(
        planner_path=store.path,
        queue_path=queue.path,
        web_service_secret_file=keys[0],
        bot_service_secret_file=keys[1],
        confirmer_ids={8306778724},
        verified_contracts=set(),
    )
    with TestingSession() as db:
        manager = db.query(User).filter_by(email="manager@testing.example.com").one()
        second = db.query(User).filter_by(email="second@testing.example.com").one()
        boss = User(
            email="supervisor@testing.example.com",
            full_name="Synthetic supervisor",
            role="supervisor",
            hashed_password=hash_password("synthetic-password"),
        )
        db.add(boss)
        db.flush()
        db.add_all(
            [
                WorkspaceLink(user_id=manager.id, employee_id=1, can_confirm=True),
                WorkspaceLink(user_id=second.id, employee_id=2),
                WorkspaceLink(user_id=boss.id, employee_id=3),
            ]
        )
        db.commit()
    writer = writer_app(cfg, Leads())
    writer.dependency_overrides[get_db] = override_db
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    install_security(app, "https://workspace.test", b"x" * 32)

    async def relay(request, identifier, index):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=writer), base_url="http://writer"
        ) as client:
            response = await client.post(
                "/web/confirm",
                json={"identifier": identifier, "variant_index": index},
                headers={
                    "authorization": "Bearer " + keys[0].read_text(),
                    "cookie": request.headers.get("cookie", ""),
                },
            )
            from fastapi import HTTPException

            if response.status_code != 200:
                raise HTTPException(response.status_code, "Writer rejected")
            return response.json()

    register_workspace(app, cfg, Leads(), relay)
    yield app, writer, store, queue, cfg
    app.state.crm_pool.shutdown(wait=True, cancel_futures=True)


def mutation(client, path, body=None, method="POST", origin="https://workspace.test"):
    csrf = client.get("/api/v1/auth/csrf").json()["csrf"]
    return client.request(method, path, json=body, headers={"origin": origin, "x-csrf-token": csrf})


def login(client, email="manager@testing.example.com", password="password123"):
    assert (
        mutation(client, "/api/v1/auth/login", {"email": email, "password": password}).status_code
        == 200
    )


def test_session_csrf_direct_ownership_revision_and_reports(runtime):
    app, writer, store, queue, cfg = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        assert c.get("/api/v1/planner/me").status_code == 401
        assert c.post("/api/v1/auth/login", json={}).status_code == 403
        login(c)
        assert c.get("/api/v1/planner/me").json()["user"]["id"] == 1
        assert c.get("/api/v1/planner/plans?employee_id=2").status_code == 403
        p = mutation(c, "/api/v1/planner/plans", {"day": "2026-10-20"}).json()
        daily = c.get(f"/api/v1/planner/plans/{p['id']}/daily").json()
        body = {
            "revision": 0,
            "contracts": 0,
            "indicators": [
                {k: r[k] for k in ("key", "planned", "actual", "morning", "details")}
                for r in daily["indicators"]
            ],
        }
        body["indicators"][0]["actual"] = 12
        url = f"/api/v1/planner/plans/{p['id']}/daily"
        assert mutation(c, url, body, "PUT").status_code == 200
        assert mutation(c, url, body, "PUT").status_code == 409
        assert mutation(c, url, body, "PUT", "https://evil.test").status_code == 403
        report = mutation(c, f"/api/v1/planner/plans/{p['id']}/close").json()
        assert report["daily"]["indicators"][0]["actual"] == 12
        assert mutation(c, url, body, "PUT").status_code == 409
        assert mutation(c, "/api/v1/auth/logout").status_code == 204
        assert c.get("/api/v1/planner/me").status_code == 401


def test_shared_writer_authority_and_reader_cannot_publish(runtime):
    app, writer, store, queue, cfg = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        login(c)
        p = mutation(
            c,
            "/api/v1/planner/distribution/calculate",
            {"employee_ids": [1, 2], "period": 3, "stages": ["IN_PROCESS"]},
        ).json()
        saved = mutation(c, f"/api/v1/planner/distribution/{p['id']}/confirm", {"variant_index": 0})
        assert saved.status_code == 200
        assert (
            mutation(
                c, f"/api/v1/planner/distribution/{p['id']}/confirm", {"variant_index": 0}
            ).json()
            == saved.json()
        )
        assert len(list(queue.read())) == 1
        another = mutation(
            c,
            "/api/v1/planner/distribution/calculate",
            {"employee_ids": [1, 2], "period": 3, "stages": ["IN_PROCESS"]},
        ).json()
        delegated_cookie = "; ".join(k + "=" + v for k, v in c.cookies.items())
        from planner.read_only import ReadOnlyQueue, ReadOnlyStore

        with pytest.raises(PermissionError):
            ReadOnlyQueue(queue.path).publish(saved.json(), cfg.confirmer_ids)
        with pytest.raises(PermissionError):
            with ReadOnlyStore(store.path).connection(True):
                pass
    with TestClient(writer) as c:
        assert c.post("/bot/check", json={"actor_id": 8306778724}).status_code == 403
        headers = {"authorization": "Bearer " + cfg.bot_service_secret_file.read_text()}
        assert (
            c.post("/bot/check", json={"actor_id": 7939114214}, headers=headers).status_code == 403
        )
        assert (
            c.post("/bot/check", json={"actor_id": 8306778724}, headers=headers).status_code == 200
        )

    # Fresh bot command goes through the actual private writer HTTP endpoint.
    cfg2 = SimpleNamespace(**vars(cfg))
    cfg2.queue_path = cfg.planner_path.parent / "bot-first-queue.db"
    second = DistributionQueue(cfg2.queue_path)
    second.initialize()
    second_app = writer_app(cfg2, Leads())
    second_app.dependency_overrides[get_db] = override_db
    with TestClient(second_app) as c:
        headers = {"authorization": "Bearer " + cfg2.bot_service_secret_file.read_text()}
        body = {"actor_id": 8306778724, "snapshot": saved.json()}
        assert c.post("/bot/publish", json=body, headers=headers).json() is True
        assert c.post("/bot/publish", json=body, headers=headers).json() is False
        web = {
            "authorization": "Bearer " + cfg2.web_service_secret_file.read_text(),
            "cookie": delegated_cookie,
        }
        assert (
            c.post(
                "/web/confirm", json={"identifier": another["id"], "variant_index": 0}, headers=web
            ).status_code
            == 409
        )
        assert len(list(second.read())) == 1


def test_admin_unmapped_disabled_and_supervisor_no_implicit_grant(runtime):
    app, writer, store, queue, cfg = runtime
    from sqlalchemy import text

    with TestingSession() as db:
        db.execute(text("INSERT INTO workspace_links(user_id,employee_id) VALUES(1,999)"))
        assert db.get(WorkspaceLink, 1).can_confirm is False
        db.rollback()
    with TestClient(app, base_url="https://workspace.test") as c:
        login(c, "admin@testing.example.com")
        assert c.get("/api/v1/planner/me").status_code == 403
        mutation(c, "/api/v1/auth/logout")
        login(c, "supervisor@testing.example.com", "synthetic-password")
        assert len(c.get("/api/v1/planner/employees").json()) == 2
        assert c.get("/api/v1/planner/distribution/options").json()["can_confirm"] is False
        mutation(c, "/api/v1/auth/logout")
        login(c)
        with store.connection(True) as db:
            db.execute("UPDATE employees SET active=0 WHERE id=1")
        assert c.get("/api/v1/planner/me").status_code == 403


def test_bad_source_does_not_change_manual_values(runtime):
    app, writer, store, queue, cfg = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        login(c)
        p = mutation(c, "/api/v1/planner/plans", {"day": "2026-10-20"}).json()
        url = f"/api/v1/planner/plans/{p['id']}"
        before = c.get(url + "/daily").json()
        for kind in ("calls", "leads", "tasks", "deals"):
            response = mutation(c, url + "/sources/" + kind)
            assert response.status_code == 200 and response.json()["status"] == "unavailable"
        assert c.get(url + "/daily").json() == before


def test_actual_server_factory_and_readonly_recovery(runtime, tmp_path, monkeypatch):
    # Production policy is enabled; only the DB transport is dependency-overridden
    # with synthetic SQLite. This is NOT a real PostgreSQL integration result.
    from app.core.config import settings
    from workspace.application import create_app
    from workspace.config import RuntimeConfig

    _, _, store, queue, cfg = runtime
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text(
        "<!doctype html><title>Workspace build</title>", encoding="utf-8"
    )
    key = tmp_path / "csrf.key"
    key.write_text(secrets.token_urlsafe(32), encoding="ascii")
    key.chmod(0o600)
    config = RuntimeConfig(
        "https://workspace.test",
        store.path,
        queue.path,
        frontend,
        tmp_path / "writer.sock",
        key,
        cfg.web_service_secret_file,
        cfg.bot_service_secret_file,
        frozenset(cfg.confirmer_ids),
    )
    monkeypatch.setattr("workspace.config.load_config", lambda: config)
    for name, value in [
        ("session_environment", "production"),
        ("cookie_secure", True),
        ("public_app_url", config.origin),
        ("frontend_url", config.origin),
        ("database_url", "postgresql+psycopg://synthetic@127.0.0.1/not-connected"),
    ]:
        monkeypatch.setattr(settings, name, value)
    for maintenance in (False, True):
        application = create_app(read_only=maintenance)

        @application.post("/api/v1/auth/future-mutation")
        def future_mutation():
            raise AssertionError("Recovery auth wildcard bypass")

        application.dependency_overrides[get_db] = override_db
        with TestClient(application, base_url=config.origin) as c:
            assert c.get("/").status_code == 200
            assert c.get("/api/v1/local/csrf").status_code == 404
            assert (
                c.get("/ready").status_code == 503
            )  # Test auth DB deliberately has no Alembic gate.
            login(c)
            response = c.get("/api/v1/planner/me")
            assert response.status_code == 200
            assert c.get("/health").json()["read_only"] == maintenance
            if maintenance:
                assert mutation(c, "/api/v1/auth/future-mutation").status_code == 503
                assert mutation(c, "/api/v1/auth/visit").status_code == 200
                for path in (
                    "/api/v1/leads",
                    "/api/v1/planner/tasks/1/timer",
                    "/api/v1/planner/distribution/calculate",
                ):
                    assert mutation(c, path, {}).status_code == 503
                assert (
                    mutation(c, "/api/v1/planner/plans", {"day": "2026-10-19"}).status_code == 503
                )
                assert mutation(c, "/api/v1/auth/logout").status_code == 204
            else:
                assert (
                    mutation(c, "/api/v1/planner/plans", {"day": "2026-10-19"}).status_code == 201
                )


def test_csrf_token_is_bound_to_current_session(runtime):
    app, *_ = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        before = c.get("/api/v1/auth/csrf").json()["csrf"]
        assert (
            c.post(
                "/api/v1/auth/login",
                json={"email": "manager@testing.example.com", "password": "password123"},
                headers={"origin": "https://workspace.test", "x-csrf-token": before},
            ).status_code
            == 200
        )
        assert (
            c.post(
                "/api/v1/planner/plans",
                json={"day": "2026-10-20"},
                headers={"origin": "https://workspace.test", "x-csrf-token": before},
            ).status_code
            == 403
        )
        assert mutation(c, "/api/v1/planner/plans", {"day": "2026-10-20"}).status_code == 201
