"""Ordinary server factory, canonical LeadFlow sessions; no seed or local guard removal."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from planner.daily import DailyStore
from planner.read_only import ReadOnlyQueue
from planner.runtime_files import secret_file
from planner.store import DomainError
from planner.web_distribution import WebDistribution
from sqlalchemy.exc import SQLAlchemyError

from workspace.identity import actor_dependency
from workspace.routes import register_routes
from workspace.security import install_security


def server_policy(config):
    from app.core.config import settings

    config.validate()
    if (
        settings.session_environment != "production"
        or not settings.cookie_secure
        or settings.public_app_url != config.origin
        or settings.frontend_url != config.origin
    ):
        raise ValueError("Canonical production sessions and matching HTTPS origins required")
    if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Canonical PostgreSQL auth required; no SQLite production fallback")


def register_workspace(app, config, leads, confirm_remote, gateway=None):
    """Testable registration. Production factory separately enforces server_policy."""
    from app.core.security import HashCapacityExceeded

    @app.exception_handler(HashCapacityExceeded)
    async def hash_busy(request, e):
        return JSONResponse({"detail": "Проверка пароля занята. Повторите позднее."}, 429)

    store = DailyStore(config.planner_path)
    # Fail closed; never create or migrate a missing/old DB during app startup.
    if not store.path.is_file():
        raise ValueError("Prepared Planner database required")
    with store.connection() as db:
        if (
            db.execute("PRAGMA user_version").fetchone()[0] != 4
            or not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='web_distribution_previews'"
            ).fetchone()
            or not db.execute("SELECT 1 FROM sqlite_master WHERE name='daily_records'").fetchone()
        ):
            raise ValueError("Explicit reviewed daily migration required before startup")
        row = db.execute(
            "SELECT version FROM workspace_extensions WHERE name='crm_observations'"
        ).fetchone()
        if (
            not row
            or row[0] != 1
            or not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='crm_observations'"
            ).fetchone()
        ):
            raise ValueError("Unknown/missing CRM observation extension; review a copy first")
    queue = ReadOnlyQueue(config.queue_path)
    queue.path.resolve(strict=True)
    actor = actor_dependency(store, config.confirmer_ids)
    distribution = WebDistribution(store, queue, leads, config.confirmer_ids)
    register_routes(app, store, actor, distribution, confirm_remote, gateway)

    @app.exception_handler(DomainError)
    async def domain(request, e):
        return JSONResponse({"detail": e.message}, e.status)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, e):
        return JSONResponse({"detail": "Конфликт данных. Обновите план."}, 409)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(OSError)
    async def unavailable(request, e):
        return JSONResponse({"detail": "Хранилище временно недоступно."}, 503)

    @app.exception_handler(ValueError)
    async def invalid_source(request, e):
        return JSONResponse({"detail": "Источник вернул некорректные данные."}, 503)

    from bitrix import BitrixError

    @app.exception_handler(BitrixError)
    async def crm_unavailable(request, e):
        return JSONResponse({"detail": "Источник CRM недоступен. Ручные данные сохранены."}, 503)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid(request, e):
        return JSONResponse({"detail": "Проверьте формат полей."}, 422)

    from concurrent.futures import ThreadPoolExecutor

    from planner.daily_crm import SOURCE_NAMES, source_status
    from planner.server_migration import save_observation

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crm-read")
    app.state.crm_pool = pool

    @app.post("/api/v1/planner/plans/{plan_id}/sources/{kind}")
    async def refresh_source(plan_id: int, kind: str, user=Depends(actor)):
        if kind not in SOURCE_NAMES:
            raise HTTPException(422, "Неизвестный источник.")
        with store.connection() as db:
            store.plan(db, user, plan_id, True)
        try:
            observation = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    pool, source_status, store, user, plan_id, kind, gateway
                ),
                9,
            )
        except TimeoutError:
            observation = source_status(store, user, plan_id, kind)
        return await asyncio.to_thread(
            save_observation, store, user, plan_id, kind, observation, config.verified_contracts
        )

    from sqlalchemy.orm import Session

    from app.api.dependencies import ACCESS_TOKEN_COOKIE
    from app.db.session import get_db
    from app.services.web_sessions import WebSessions

    @app.post("/api/v1/auth/visit")
    def visit(request: Request, db: Session = Depends(get_db)):
        if WebSessions(db).check(request.cookies.get(ACCESS_TOKEN_COOKIE), foreground=True) is None:
            raise HTTPException(401, "Требуется вход.")
        return {"visited": True}

    return store, actor


class NoCRM:
    async def counts_for_dates(self, *args, **kwargs):
        raise HTTPException(503, "CRM не подключена.")

    async def find_previous_nonempty(self, *args, **kwargs):
        raise HTTPException(503, "CRM не подключена.")


def create_app(*, read_only=False):
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    import httpx
    from planner.daily_crm import ReadOnlyCRM
    from planner.distribution_queue import MOSCOW
    from planner.sync import sync_loop
    from sqlalchemy.orm import Session

    from app.api.dependencies import ACCESS_TOKEN_COOKIE
    from app.api.router import api_router
    from app.db.session import get_db
    from workspace.config import crm_url, load_config
    from workspace.crm import BoundedLeads, LimitedTransport

    config = load_config()
    server_policy(config)
    csrf = secret_file(config.csrf_secret_file).encode()
    web_key = secret_file(config.web_service_secret_file)
    # No bot service key or queue RW directory is needed by the web process.
    url = crm_url(config.crm_secret_file)
    http = httpx.AsyncClient(
        transport=LimitedTransport(), trust_env=False, limits=httpx.Limits(max_connections=4)
    )
    sync_http = httpx.Client(
        trust_env=False, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2)
    )
    writer = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=str(config.writer_socket)),
        base_url="http://writer",
        timeout=12,
        trust_env=False,
    )

    async def remote(request: Request, identifier, index):
        try:
            response = await writer.post(
                "/web/confirm",
                json={"identifier": identifier, "variant_index": index},
                headers={
                    "Authorization": "Bearer " + web_key,
                    "Cookie": ACCESS_TOKEN_COOKIE
                    + "="
                    + request.cookies.get(ACCESS_TOKEN_COOKIE, ""),
                },
            )
            if response.status_code not in (200, 401, 403, 409, 422, 503):
                raise HTTPException(503, "Writer вернул ошибку.")
            if response.status_code != 200:
                raise HTTPException(
                    response.status_code,
                    "Подтверждение отклонено. Проверьте права, данные и историю.",
                )
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                503, "Сервис подтверждений недоступен; проверьте историю перед повтором."
            ) from None

    app = FastAPI(title="Рабочее пространство", docs_url=None, redoc_url=None)
    if read_only:

        @app.middleware("http")
        async def maintenance(request, call_next):
            allowed_session_write = request.method == "POST" and request.url.path in {
                "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/visit",
            }
            if request.method not in ("GET", "HEAD", "OPTIONS") and not allowed_session_write:
                return JSONResponse(
                    {"detail": "Режим восстановления: изменения временно запрещены."}, 503
                )
            return await call_next(request)

    install_security(app, config.origin, csrf, secure=True)
    app.include_router(api_router, prefix="/api/v1")
    store, _ = register_workspace(
        app,
        config,
        BoundedLeads(url, "IN_PROCESS", MOSCOW, http) if url else NoCRM(),
        remote,
        ReadOnlyCRM(url, sync_http) if url else None,
    )

    @app.get("/health")
    def health():
        with store.connection() as db:
            db.execute("SELECT 1 FROM daily_records LIMIT 1").fetchone()
        return {
            "status": "ok",
            "read_only": read_only,
            "worker_running": app.state.worker is not None and not app.state.worker.done(),
        }

    @app.get("/ready")
    def ready(db: Session = Depends(get_db)):
        from contextlib import closing

        from sqlalchemy import text

        try:
            version = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if version != "0005_workspace_links":
                raise ValueError("Auth schema not ready")
            db.execute(text("SELECT user_id FROM workspace_links LIMIT 1")).fetchall()
            with closing(
                sqlite3.connect(
                    config.queue_path.resolve(strict=True).as_uri() + "?mode=ro",
                    uri=True,
                    timeout=2,
                )
            ) as q:
                if (
                    q.execute("PRAGMA user_version").fetchone()[0] != 1
                    or q.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                ):
                    raise ValueError("Queue schema not ready")
            if not read_only and (app.state.worker is None or app.state.worker.done()):
                raise ValueError("Worker stopped")
            return {"status": "ready", "read_only": read_only}
        except (SQLAlchemyError, sqlite3.Error, OSError, ValueError):
            db.rollback()
            raise HTTPException(
                503, "Runtime пока не готов. Проверьте миграции и зависимости."
            ) from None

    @asynccontextmanager
    async def lifespan(application):
        app.state.worker = (
            None
            if read_only
            else asyncio.create_task(
                sync_loop(store, config.queue_path, config.confirmer_ids, interval=30)
            )
        )
        try:
            yield
        finally:
            if app.state.worker is not None:
                app.state.worker.cancel()
                with suppress(asyncio.CancelledError):
                    await app.state.worker
            await writer.aclose()
            await http.aclose()
            sync_http.close()
            app.state.crm_pool.shutdown(wait=False, cancel_futures=True)

    app.router.lifespan_context = lifespan
    if not (config.frontend_path / "index.html").is_file():
        raise ValueError("Production frontend build required")
    app.mount("/assets", StaticFiles(directory=config.frontend_path / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith(("api/", "local-control/")):
            raise HTTPException(404)
        return FileResponse(config.frontend_path / "index.html")

    return app


def create_readonly_app():
    """Compatible recovery backend: no business writes, no automatic import."""
    return create_app(read_only=True)
