"""Private UDS writer. No public port, frontend, seeds, or Telegram polling."""

import asyncio
import hmac
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from planner.distribution_queue import DistributionQueue, validate
from planner.read_only import ReadOnlyStore
from planner.runtime_files import secret_file
from planner.store import DomainError
from planner.web_distribution import WebDistribution
from pydantic import BaseModel, ConfigDict, Field


class BotCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: int = Field(strict=True, gt=0)
    identifier: str | None = None
    snapshot: dict | None = None


class WebCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(min_length=36, max_length=36)
    variant_index: int = Field(strict=True, ge=0, le=5)


def writer_app(config, leads):
    from workspace.identity import actor_dependency

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = ReadOnlyStore(config.planner_path)
    queue = DistributionQueue(config.queue_path)
    # Never initialize/migrate the queue or Planner at startup.
    queue.path.resolve(strict=True)
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(queue.path.resolve().as_uri() + "?mode=ro", uri=True)) as check:
        if (
            check.execute("PRAGMA user_version").fetchone()[0] != 1
            or check.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        ):
            raise ValueError("Existing schema1 DELETE-journal queue required")
    web_key = secret_file(config.web_service_secret_file)
    bot_key = secret_file(config.bot_service_secret_file)
    if hmac.compare_digest(web_key, bot_key):
        raise ValueError("Separate purpose keys required")
    actor = actor_dependency(store, config.confirmer_ids)
    service = WebDistribution(store, queue, leads, config.confirmer_ids)
    gate = asyncio.Semaphore(2)

    @app.middleware("http")
    async def service_boundary(request, call_next):
        purpose = web_key if request.url.path == "/web/confirm" else bot_key
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + purpose):
            return JSONResponse({"detail": "Нет доступа к writer."}, 403)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 512000:
                return JSONResponse({"detail": "Слишком большой запрос."}, 413)
            body.extend(chunk)
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain(request, e):
        return JSONResponse({"detail": e.message}, e.status)

    @app.exception_handler(ValueError)
    async def conflict(request, e):
        return JSONResponse({"detail": "Данные изменились или дневной слот занят."}, 409)

    import sqlite3

    from bitrix import BitrixError
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def bad_request(request, e):
        return JSONResponse({"detail": "Некорректная команда writer."}, 422)

    @app.exception_handler(BitrixError)
    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def unavailable(request, e):
        return JSONResponse({"detail": "Writer или источник временно недоступен."}, 503)

    @app.post("/web/confirm")
    async def web_confirm(body: WebCommand, user=Depends(actor)):
        if not user["_can_confirm"]:
            raise HTTPException(403, "Нет отдельного права подтверждения.")
        try:
            async with gate:
                return await asyncio.wait_for(
                    service.confirm(user, body.identifier, body.variant_index), 10
                )
        except (OSError, TimeoutError):
            raise HTTPException(
                503, "Writer временно недоступен; проверьте историю перед повтором."
            ) from None

    def bot_actor(body):
        if body.actor_id not in config.confirmer_ids:
            raise HTTPException(403, "Нет права подтверждения.")
        employee = store.actor(body.actor_id)
        if not employee["active"]:
            raise HTTPException(403, "Инициатор отключён.")
        return employee

    @app.post("/bot/check")
    async def check(body: BotCommand):
        bot_actor(body)
        return {"ready": True}

    @app.post("/bot/find")
    async def find(body: BotCommand):
        bot_actor(body)
        old = await asyncio.to_thread(queue.find, body.identifier)
        # Do not allow a trusted bot client to retrieve another author's IDs.
        return old if old is None or old["confirmed_by"] == body.actor_id else None

    @app.post("/bot/publish")
    async def publish(body: BotCommand):
        bot_actor(body)
        snapshot = body.snapshot
        validate(snapshot)
        if snapshot["confirmed_by"] != body.actor_id:
            raise HTTPException(403, "Неверный инициатор.")

        async def process():
            old = await asyncio.to_thread(queue.find, snapshot["distribution_id"])
            if old is not None:
                if old != snapshot:
                    raise ValueError("Different snapshot")
                return False
            from datetime import datetime

            from planner.distribution_queue import MOSCOW

            if snapshot["workday"] != datetime.now(MOSCOW).date().isoformat():
                raise ValueError("Stale confirmation")
            active = {m["telegram_id"]: m for m in service.managers(store.actor(body.actor_id))}
            from planner.confirmation_reads import read_dates

            fresh_by_day = await read_dates(
                leads,
                [
                    date.fromisoformat(day)
                    for allocation in snapshot["allocations"]
                    for day in allocation["dates"]
                ],
            )
            for allocation in snapshot["allocations"]:
                m = active.get(allocation["telegram_id"])
                if m is None or m["bitrix_id"] != allocation["bitrix_id"]:
                    raise ValueError("Inactive manager")
                observed = []
                for day in allocation["dates"]:
                    fresh = fresh_by_day[date.fromisoformat(day)]
                    observed.extend(
                        {
                            "id": x.id,
                            "created_date": x.created_at.astimezone(
                                __import__("planner.distribution_queue", fromlist=["MOSCOW"]).MOSCOW
                            )
                            .date()
                            .isoformat(),
                            "stage_id": x.stage_id,
                        }
                        for x in fresh
                    )
                if sorted(observed, key=lambda x: x["id"]) != allocation["leads"]:
                    raise ValueError("CRM changed")
            return await asyncio.to_thread(queue.publish, snapshot, config.confirmer_ids)

        try:
            async with gate:
                return await asyncio.wait_for(process(), 10)
        except (OSError, TimeoutError):
            raise HTTPException(503, "Writer временно недоступен.") from None

    return app


def create_writer():
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    import httpx
    from planner.distribution_queue import MOSCOW

    from workspace.application import server_policy
    from workspace.config import crm_url, load_config
    from workspace.crm import BoundedLeads, LimitedTransport

    config = load_config()
    server_policy(config)
    url = crm_url(config.crm_secret_file)
    if url is None:
        raise ValueError("Writer needs explicitly provided read-only CRM secret")
    client = httpx.AsyncClient(
        transport=LimitedTransport(), trust_env=False, limits=httpx.Limits(max_connections=2)
    )
    app = writer_app(config, BoundedLeads(url, "IN_PROCESS", MOSCOW, client))
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifetime(app):
        try:
            yield
        finally:
            await client.aclose()

    app.router.lifespan_context = lifetime
    return app
