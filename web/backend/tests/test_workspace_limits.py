import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from app.api.routes import auth
from app.core import security


def test_password_memory_concurrency_is_bounded():
    entered = threading.Barrier(3)
    release = threading.Event()

    def hash_fake(value):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        return "not-a-real-hash"

    with patch.object(security.password_hash, "hash", side_effect=hash_fake):
        with ThreadPoolExecutor(2) as pool:
            tasks = [pool.submit(security.hash_password, "synthetic") for _ in range(2)]
            entered.wait(timeout=5)
            try:
                with pytest.raises(security.HashCapacityExceeded):
                    security.hash_password("synthetic")
            finally:
                release.set()
            assert [t.result() for t in tasks] == ["not-a-real-hash"] * 2


def test_rate_limit_dictionary_cannot_grow_unbounded():
    for i in range(auth._LOGIN_MAX_KEYS + 100):
        key = f"owned-synthetic:{i}"
        if not auth._is_rate_limited(key):
            auth._register_failed_attempt(key)
    assert len(auth._failed_attempts) <= auth._LOGIN_MAX_KEYS


def test_server_factory_rejects_local_session_fallback(tmp_path, monkeypatch):
    from app.core.config import settings
    from workspace.application import server_policy
    from workspace.config import RuntimeConfig

    config = RuntimeConfig(
        "https://workspace.test",
        tmp_path / "planner.db",
        tmp_path / "queue.db",
        tmp_path / "frontend",
        tmp_path / "writer.sock",
        tmp_path / "csrf.key",
        tmp_path / "web.key",
        tmp_path / "bot.key",
        frozenset(),
    )
    monkeypatch.setattr(settings, "session_environment", "local")
    with pytest.raises(ValueError, match="production sessions"):
        server_policy(config)


def test_bounded_lead_response_size():
    import asyncio
    from datetime import date

    import httpx
    from bitrix import BitrixError
    from planner.distribution_queue import MOSCOW

    from workspace.crm import BoundedLeads, LimitedTransport

    async def probe():
        async with httpx.AsyncClient(
            transport=LimitedTransport(
                httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2_000_001))
            )
        ) as client:
            with pytest.raises(BitrixError):
                await BoundedLeads(
                    "https://synthetic.invalid/rest/x", "IN_PROCESS", MOSCOW, client
                ).get_leads(date(2026, 10, 20), date(2026, 10, 20))

    asyncio.run(probe())
