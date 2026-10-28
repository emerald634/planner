import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from planner.distribution_queue import DistributionQueue
from planner.sync import sync_once

from app.db.session import get_db
from app.integrations.bitrix24 import Bitrix24Error, Bitrix24Gateway
from app.models.lead import Lead, LeadSyncStatus
from app.schemas.lead import LeadUpdate
from app.services.bitrix_sync import BitrixSyncService
from app.services.leads import LeadService
from tests.conftest import TestingSession, override_db
from tests.test_workspace_runtime import Leads, login, mutation
from tests.test_workspace_runtime import runtime as runtime
from workspace.writer import writer_app


def preview(runtime, period):
    app, _, _, _, cfg = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        login(c)
        r = mutation(
            c,
            "/api/v1/planner/distribution/calculate",
            {"employee_ids": [1, 2], "period": period, "stages": ["IN_PROCESS"]},
        )
        assert r.status_code == 200
        return r.json(), {
            "authorization": "Bearer " + cfg.web_service_secret_file.read_text(),
            "cookie": "; ".join(k + "=" + v for k, v in c.cookies.items()),
        }


def test_workspace_lead_cannot_feed_even_legacy_worker(runtime, monkeypatch):
    app, *_ = runtime
    with patch("httpx.post", side_effect=AssertionError("External call")) as network:
        with TestClient(app, base_url="https://workspace.test") as c:
            login(c, "supervisor@testing.example.com", "synthetic-password")
            r = mutation(
                c,
                "/api/v1/leads",
                {"phone": "+70000000000", "source": "OTHER", "auto_assign": True},
            )
            assert r.status_code == 201 and r.json()["sync_status"] == "local"
            identifier = r.json()["id"]
            for body in ({"sync_status": "pending"}, {"bitrix_lead_id": "100"}):
                assert mutation(c, f"/api/v1/leads/{identifier}", body, "PATCH").status_code == 422
        monkeypatch.delenv("WORKSPACE_RUNTIME")
        with TestingSession() as db:

            class DeniedGateway:
                def create_lead(self, **kw):
                    raise AssertionError("Local row reached CRM export")

            assert BitrixSyncService(db, DeniedGateway()).create_pending_leads() == 0
            assert db.get(Lead, identifier).sync_status == LeadSyncStatus.LOCAL
            with pytest.raises(Exception) as error:
                LeadService(db).update(db.get(Lead, identifier), LeadUpdate(sync_status="pending"))
            assert error.value.status_code == 422
        assert network.call_count == 0


def test_workspace_worker_service_and_gateway_fail_closed(runtime):
    from app.worker import run

    with patch("httpx.post", side_effect=AssertionError("CRM egress")) as external:
        with pytest.raises(PermissionError):
            run()
        with TestingSession() as db, pytest.raises(PermissionError):
            BitrixSyncService(db, object()).create_pending_leads()
        with pytest.raises(Bitrix24Error):
            Bitrix24Gateway("https://synthetic.invalid")._call("crm.lead.add", {})
        assert external.call_count == 0


def test_file_only_production_settings_and_sanitized_errors(tmp_path, monkeypatch, caplog):
    from app.core.config import Settings
    from app.core.runtime_secrets import private_text, settings_arguments

    for name in ("DATABASE_URL", "FIRST_ADMIN_PASSWORD", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SESSION_ENVIRONMENT", "production")
    key = tmp_path / "auth-dsn"
    secret = "synthetic-password-never-log-this"
    key.write_text(f"postgresql+psycopg://synthetic:{secret}@127.0.0.1/synthetic")
    key.chmod(0o600)
    monkeypatch.setenv("DATABASE_URL_FILE", str(key))
    args = settings_arguments()
    settings = Settings(
        _env_file=None,
        **args,
        cookie_secure=True,
        public_app_url="https://workspace.test",
        frontend_url="https://workspace.test",
    )
    assert secret not in repr(settings)
    monkeypatch.setenv("DATABASE_URL", "inline-secret")
    with pytest.raises(ValueError) as error:
        settings_arguments()
    assert "inline-secret" not in str(error.value)
    key.write_text("x\ny")
    with pytest.raises(ValueError):
        private_text(key)
    assert secret not in caplog.text


def test_secret_permissions_and_compose_no_inline_credentials(tmp_path):
    from app.core.runtime_secrets import private_text

    key = tmp_path / "key"
    key.write_text("synthetic")
    link = tmp_path / "linked"
    os.link(key, link)
    with pytest.raises(ValueError):
        private_text(key)
    assert (
        "DATABASE_URL:"
        not in (
            Path(__file__).resolve().parents[2] / "deploy/compose.workspace-review.yaml"
        ).read_text()
    )
    assert (
        "FIRST_ADMIN_PASSWORD:"
        not in (
            Path(__file__).resolve().parents[2] / "deploy/compose.workspace-review.yaml"
        ).read_text()
    )


@pytest.mark.parametrize("period", [10, 15])
def test_slow_confirm_periods_and_replay_after_lost_response(runtime, period):
    p, headers = preview(runtime, period)
    _, _, store, queue, cfg = runtime

    class Slow(Leads):
        calls = 0
        active = 0
        peak = 0

        async def get_leads(self, *a, **kw):
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.7)
                return await super().get_leads(*a, **kw)
            finally:
                self.active -= 1

    source = Slow()
    app = writer_app(cfg, source)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        start = time.monotonic()
        first = c.post(
            "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
        )
        seconds = time.monotonic() - start
        assert first.status_code == 200
        assert source.calls == period and source.peak == 2 and seconds < 10
        # Response is discarded by the caller AFTER durable publish. Restart app.
    restarted = writer_app(cfg, source)
    restarted.dependency_overrides[get_db] = override_db
    with TestClient(restarted) as c:
        second = c.post(
            "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
        )
        assert second.json() == first.json() and source.calls == period
    assert len(list(queue.read())) == 1
    assert first.json()["total"] == period
    assert sync_once(store, queue.path, cfg.confirmer_ids)
    sync_once(store, queue.path, cfg.confirmer_ids)
    assert len(store.list_plans(store.actor(8306778724))) == 1
    output = Path(__file__).resolve().parents[3] / "test-artifacts/web-review"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"slow-confirm-{period}.json").write_text(
        json.dumps(
            {
                "period": period,
                "seconds": round(seconds, 3),
                "source_delay": 0.7,
                "max_parallel": source.peak,
                "replay_duplicate": False,
            }
        )
    )


@pytest.mark.parametrize("failure", ["crm", "timeout", "queue"])
def test_writer_failure_no_false_success_and_retry(runtime, failure):
    p, headers = preview(runtime, 15)
    _, _, _, queue, cfg = runtime

    class Failure(Leads):
        async def get_leads(self, *a, **kw):
            from bitrix import BitrixError

            if failure == "crm":
                raise BitrixError()
            if failure == "timeout":
                raise TimeoutError()
            return await super().get_leads(*a, **kw)

    app = writer_app(cfg, Failure())
    app.dependency_overrides[get_db] = override_db
    with (
        TestClient(app) as c,
        patch.object(DistributionQueue, "publish", side_effect=OSError("synthetic"))
        if failure == "queue"
        else __import__("contextlib").nullcontext(),
    ):
        r = c.post(
            "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
        )
        assert r.status_code == 503
    assert not list(queue.read())
    retry = writer_app(cfg, Leads())
    retry.dependency_overrides[get_db] = override_db
    with TestClient(retry) as c:
        assert (
            c.post(
                "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
            ).status_code
            == 200
        )
    assert len(list(queue.read())) == 1


def test_parallel_confirmations_one_slot_immutable(runtime):
    p, headers = preview(runtime, 10)
    other, _ = preview(runtime, 10)
    _, _, _, queue, cfg = runtime
    app = writer_app(cfg, Leads())
    # StaticPool's ONE SQLite connection is unsuitable for simultaneous auth
    # transactions. Use separate real connections to this synthetic file instead.
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    engine = create_engine("sqlite:///" + str(cfg.planner_path.parent / "parallel-auth.db"))
    Base.metadata.create_all(engine)
    with TestingSession() as source, engine.begin() as destination:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in source.execute(select(table)).mappings()]
            if rows:
                destination.execute(table.insert(), rows)
    local = sessionmaker(engine)

    def parallel_db():
        with local() as db:
            yield db

    app.dependency_overrides[get_db] = parallel_db
    with TestClient(app) as c, ThreadPoolExecutor(2) as pool:

        def send(identifier):
            return c.post(
                "/web/confirm", json={"identifier": identifier, "variant_index": 0}, headers=headers
            )

        responses = list(pool.map(send, [p["id"], other["id"]]))
        assert sorted(r.status_code for r in responses) == [200, 409]
        snapshot = next(r.json() for r in responses if r.status_code == 200)
        with pytest.raises(Exception):
            with __import__("sqlite3").connect(queue.path) as db:
                db.execute("UPDATE confirmations SET payload='{}'")
        assert list(queue.read()) == [snapshot]
    engine.dispose()


def test_closed_report_api_rejects_refresh_and_keeps_snapshot(runtime):
    app, _, store, _, _ = runtime
    with TestClient(app, base_url="https://workspace.test") as c:
        login(c)
        plan = mutation(c, "/api/v1/planner/plans", {"day": "2026-10-28"}).json()
        url = f"/api/v1/planner/plans/{plan['id']}"
        report = mutation(c, url + "/close").json()
        with patch("planner.daily_crm.source_status", side_effect=AssertionError("CRM refresh")):
            assert mutation(c, url + "/sources/calls").status_code == 409
            assert c.get(url + "/daily").json() == report["daily"]
            assert store.report(store.actor(8306778724), plan["id"]) == report


def test_actual_bot_broker_writer_importer_chain(runtime, monkeypatch):
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from bot import confirm_distribution
    from distribution import best_distributions
    from planner.distribution_queue import MOSCOW
    from planner.queue_broker import BrokerQueue

    _, writer, store, queue, cfg = runtime
    dates = [datetime.now(MOSCOW).date() - timedelta(days=n) for n in range(1, 16)]
    data = {
        "stage_ids": ("IN_PROCESS",),
        "variants": best_distributions(
            {day: 1 for day in dates}, ["Synthetic first", "Synthetic second"]
        ),
        "variant_index": 0,
        "selected": [0, 1],
        "distribution_session": str(uuid4()),
    }
    config = SimpleNamespace(
        distribution_confirmer_ids=cfg.confirmer_ids,
        distribution_queue_path=None,
        queue_writer_socket=store.path.parent / "private.sock",
        queue_writer_key_file=cfg.bot_service_secret_file,
        manager_names=("Synthetic first", "Synthetic second"),
        manager_telegram_ids=(8306778724, 7939114214),
        planner_active_manager_ids={8306778724, 7939114214},
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=8306778724),
        answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock()),
    )
    state = SimpleNamespace(get_data=AsyncMock(return_value=data))
    with TestClient(writer) as transport:
        # Actual BrokerQueue serializer/auth/errors; ONLY physical UDS is replaced
        # with the actual writer ASGI transport on this Windows test.
        class Transport:
            lost = False
            publishes = 0

            def post(self, *a, **kw):
                response = transport.post(*a, **kw)
                if a[0] == "/bot/publish":
                    self.publishes += 1
                    assert response.status_code == 200
                    if not self.lost:
                        self.lost = True
                        raise httpx.ReadTimeout("Synthetic response lost after durable commit")
                return response

            def close(self):
                pass

        channel = Transport()

        def broker(socket, key, actor):
            return BrokerQueue(socket, key, actor, channel)

        with (
            patch("planner.queue_broker.BrokerQueue", broker),
            patch("bot.DistributionQueue", side_effect=AssertionError("Direct queue fallback")),
        ):
            asyncio.run(confirm_distribution(callback, state, config, Leads()))
            asyncio.run(confirm_distribution(callback, state, config, Leads()))
        assert channel.lost and channel.publishes == 1
    snapshots = list(queue.read())
    assert len(snapshots) == 1 and snapshots[0]["total"] == 15
    assert sync_once(store, queue.path, cfg.confirmer_ids) == ["imported"]
    # A new importer/store instance after process restart sees the durable state.
    assert sync_once(type(store)(store.path), queue.path, cfg.confirmer_ids) == []
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM distribution_tasks").fetchone()[0] == 2


def test_web_retry_after_commit_without_response(runtime):
    p, headers = preview(runtime, 15)
    _, _, _, queue, cfg = runtime
    app = writer_app(cfg, Leads())
    app.dependency_overrides[get_db] = override_db
    original = DistributionQueue.publish

    def commit_then_lose(self, *args):
        original(self, *args)
        raise OSError("Synthetic lost response")

    with TestClient(app) as c:
        with patch.object(DistributionQueue, "publish", commit_then_lose):
            failed = c.post(
                "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
            )
            assert failed.status_code == 503
        snapshot = list(queue.read())[0]
        repeated = c.post(
            "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
        )
        assert repeated.status_code == 200 and repeated.json() == snapshot
        assert list(queue.read()) == [snapshot]


def test_real_confirmation_budget_cancels_slow_reads(runtime):
    p, headers = preview(runtime, 15)
    _, _, _, queue, cfg = runtime

    class Stalled(Leads):
        active = 0

        async def get_leads(self, *args, **kwargs):
            self.active += 1
            try:
                await asyncio.sleep(30)
            finally:
                self.active -= 1

    stalled = Stalled()
    app = writer_app(cfg, stalled)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        start = time.monotonic()
        response = c.post(
            "/web/confirm", json={"identifier": p["id"], "variant_index": 0}, headers=headers
        )
        elapsed = time.monotonic() - start
    assert response.status_code == 503 and 7.5 <= elapsed < 10
    assert stalled.active == 0 and not list(queue.read())
