"""Thin local transport over original Planner Store and LeadFlow session boundary."""

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import ACCESS_TOKEN_COOKIE, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app as original_app
from app.models.user import User
from app.schemas.lead import LeadCreate


class CalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_ids: list[int] = Field(min_length=1, max_length=2)
    period: int
    stages: list[str] = Field(min_length=1, max_length=3)
    dates: list[str] | None = Field(default=None, max_length=15)


class PreviousInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str
    excluded: list[str] = Field(max_length=15)
    stages: list[str] = Field(min_length=1, max_length=3)


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_index: int = Field(strict=True, ge=0, le=5)


class AssignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    manager_id: int | None = Field(default=None, gt=0)


class LocalLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    lead: LeadCreate


def create_local_app(root: Path, origin: str, csrf_secret: bytes, control_secret: str):
    # The launcher validates ownership and pins imports to the existing Planner checkout.
    if (
        root.resolve().parent
        != (Path(__file__).resolve().parents[3] / ".workbench/browser").resolve()
        or not (root / "owner.json").is_file()
        or not root.name.startswith("lfweb_")
    ):
        raise ValueError("Owned synthetic run directory required")
    info = json.loads((root / "owner.json").read_text(encoding="utf-8"))
    database_url = make_url(settings.database_url)
    if (
        info.get("kind") != "leadflow-planner-local-mvp"
        or info.get("run_id") != root.name
        or origin != f"http://127.0.0.1:{info['port']}"
        or settings.session_environment != "local"
        or settings.cookie_secure
        or settings.public_app_url != origin
        or settings.frontend_url != origin
        or database_url.get_backend_name() != "sqlite"
        or not database_url.database
        or Path(database_url.database).resolve() != root / "auth.sqlite"
        or len(csrf_secret) < 32
        or len(control_secret) < 32
    ):
        raise ValueError("Local MVP cannot be registered in a production auth environment")
    from planner.daily import DailyInput, DailyStore
    from planner.models import DecisionInput, GoalInput, PlanInput, TaskInput, TaskPatch, TimerInput
    from planner.store import DomainError, today

    if not (root / "planner.sqlite").is_file() or not (root / "auth.sqlite").is_file():
        raise ValueError(
            "Prepare a new synthetic run first; never create databases implicitly at startup"
        )
    store = DailyStore(root / "planner.sqlite")
    with store.connection() as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise ValueError("Local MVP requires synthetic Planner schema4")
    app = original_app
    if getattr(app.state, "local_planner", False):
        raise RuntimeError("Local app may be configured once per process")
    app.state.local_planner = True
    app.state.planner_store = store
    from planner.daily_crm import source_statuses
    from planner.distribution_queue import DistributionQueue
    from planner.sync import sync_loop
    from planner.web_distribution import WebDistribution

    from local_web.fixtures import SyntheticLeads

    # Explicit synthetic capability: manager A only, NOT every manager/supervisor.
    authorized = frozenset({8306778724})
    queue = DistributionQueue(root / "distribution-queue.sqlite")
    distribution = WebDistribution(store, queue, SyntheticLeads(), authorized)
    prior_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with prior_lifespan(application):
            worker = asyncio.create_task(sync_loop(store, queue.path, authorized, interval=5))
            try:
                yield
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app.router.lifespan_context = lifespan
    csrf_cookie = "lfweb_csrf_nonce"
    mutation_lock = asyncio.Lock()  # Single-process local SQLite mode, NOT a PG lock substitute.

    def signature(session, nonce):
        return hmac.new(csrf_secret, (session + ":" + nonce).encode(), hashlib.sha256).hexdigest()

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        expected_host = origin.removeprefix("http://")
        document_navigation = (
            request.method == "GET"
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document"
            and not request.url.path.startswith(("/api/", "/local-control/"))
        )
        if (
            request.headers.get("host") != expected_host
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("origin", origin) != origin
            or (
                request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
                and not document_navigation
            )
        ):
            return JSONResponse({"detail": "Разрешён только локальный origin приложения."}, 403)
        if request.url.path == "/local-control/stop":
            if not hmac.compare_digest(
                request.headers.get("authorization", ""), "LocalStop " + control_secret
            ):
                return JSONResponse({"detail": "Нет доступа к управлению процессом."}, 403)
        elif request.method not in {"GET", "HEAD", "OPTIONS"}:
            nonce = request.cookies.get(csrf_cookie, "")
            csrf = request.headers.get("x-csrf-token", "")
            if (
                request.headers.get("origin") != origin
                or not nonce
                or len(nonce) > 100
                or not hmac.compare_digest(
                    csrf, signature(request.cookies.get(ACCESS_TOKEN_COOKIE, ""), nonce)
                )
            ):
                return JSONResponse(
                    {"detail": "Проверка безопасности не пройдена. Обновите страницу."}, 403
                )
            if request.url.path.startswith("/api/v1/leads"):
                return JSONResponse(
                    {"detail": "CRM в локальной версии доступна только для чтения."}, 403
                )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            async with mutation_lock:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"detail": error.message}, error.status)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, error):
        return JSONResponse({"detail": "Конфликт данных. Обновите план."}, 409)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(OSError)
    async def unavailable(request, error):
        return JSONResponse({"detail": "Хранилище временно недоступно."}, 503)

    @app.exception_handler(ValueError)
    async def invalid_source(request, error):
        return JSONResponse(
            {
                "detail": (
                    "Источник вернул некорректные данные. Обновите расчёт; "
                    "исходное подтверждение не изменено."
                )
            },
            503,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({"detail": "Проверьте формат и значения полей."}, 422)

    @app.get("/api/v1/local/csrf")
    def csrf(request: Request):
        nonce = request.cookies.get(csrf_cookie, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", nonce):
            nonce = secrets.token_urlsafe(24)
        response = JSONResponse(
            {"csrf": signature(request.cookies.get(ACCESS_TOKEN_COOKIE, ""), nonce)}
        )
        response.set_cookie(csrf_cookie, nonce, httponly=True, samesite="strict", path="/")
        return response

    @app.post("/local-control/stop", include_in_schema=False)
    def stop():
        app.state.on_stop()
        return {"stopping": True}

    def actor(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        if user.role not in {"manager", "supervisor"}:
            raise HTTPException(403, "Права планировщика отдельно не назначены.")
        link = (
            db.execute(
                text("SELECT employee_id,role FROM local_planner_links WHERE user_id=:id"),
                {"id": user.id},
            )
            .mappings()
            .first()
        )
        if not link or link["role"] != user.role:
            raise HTTPException(403, "Нет подтверждённого соответствия сотрудника.")
        with store.connection() as connection:
            employee = connection.execute(
                "SELECT * FROM employees WHERE id=? AND active=1", (link["employee_id"],)
            ).fetchone()
        if not employee or employee["role"] != user.role:
            raise HTTPException(403, "Сотрудник отключён или привязка конфликтует.")
        return dict(employee)

    prefix = "/api/v1/planner"

    @app.get(prefix + "/me")
    def me(user=Depends(actor)):
        return {
            "user": user,
            "today": today(),
            "timezone": "Europe/Moscow",
            "crm": {
                "connected": False,
                "message": "CRM-показатели недоступны. Подключение не выполняется.",
            },
        }

    @app.get(prefix + "/employees")
    def employees(user=Depends(actor)):
        return [employee for employee in store.employees(user) if employee["active"]]

    @app.get(prefix + "/plans")
    def plans(employee_id: int | None = None, day: date | None = None, user=Depends(actor)):
        return store.list_plans(user, employee_id, day.isoformat() if day else None)

    @app.post(prefix + "/plans", status_code=201)
    def add_plan(body: PlanInput, user=Depends(actor)):
        return store.create_plan(user, body.day.isoformat(), body.employee_id, body.from_previous)

    @app.get(prefix + "/plans/{plan_id}")
    def plan(plan_id: int, user=Depends(actor)):
        return store.get_plan(user, plan_id)

    @app.post(prefix + "/plans/{plan_id}/confirm")
    def confirm(plan_id: int, user=Depends(actor)):
        return store.confirm_plan(user, plan_id)

    @app.post(prefix + "/plans/{plan_id}/approve")
    def approve(plan_id: int, user=Depends(actor)):
        return store.approve_plan(user, plan_id)

    @app.post(prefix + "/plans/{plan_id}/close")
    def close(plan_id: int, user=Depends(actor)):
        return store.close_plan(user, plan_id)

    @app.post(prefix + "/plans/{plan_id}/tasks", status_code=201)
    def add_task(plan_id: int, body: TaskInput, user=Depends(actor)):
        return store.add_task(user, plan_id, body.model_dump())

    @app.patch(prefix + "/tasks/{task_id}")
    def edit_task(task_id: int, body: TaskPatch, user=Depends(actor)):
        return store.patch_task(user, task_id, body.model_dump(exclude_unset=True))

    @app.post(prefix + "/tasks/{task_id}/timer")
    def timer(task_id: int, body: TimerInput, user=Depends(actor)):
        return store.timer(user, task_id, body.action)

    @app.post(prefix + "/tasks/{task_id}/requests", status_code=201)
    def goal_request(task_id: int, body: GoalInput, user=Depends(actor)):
        return store.request_goal(user, task_id, body.model_dump())

    @app.get(prefix + "/requests")
    def requests(user=Depends(actor)):
        return store.requests(user)

    @app.post(prefix + "/requests/{request_id}/decision")
    def decide(request_id: int, body: DecisionInput, user=Depends(actor)):
        return store.decide(user, request_id, body.decision, body.comment)

    @app.get(prefix + "/plans/{plan_id}/history")
    def history(plan_id: int, user=Depends(actor)):
        return store.history(user, plan_id)

    @app.get(prefix + "/plans/{plan_id}/report")
    def report(plan_id: int, user=Depends(actor)):
        return store.report(user, plan_id)

    @app.get(prefix + "/plans/{plan_id}/daily")
    def daily(plan_id: int, user=Depends(actor)):
        return store.daily_get(user, plan_id)

    @app.put(prefix + "/plans/{plan_id}/daily")
    def save_daily(plan_id: int, body: DailyInput, user=Depends(actor)):
        return store.daily_save(user, plan_id, body.model_dump(mode="json"))

    @app.get(prefix + "/weekly")
    def weekly(employee_id: int, day: date, user=Depends(actor)):
        return store.weekly(user, employee_id, day.isoformat())

    @app.get(prefix + "/plans/{plan_id}/sources")
    def sources(plan_id: int, user=Depends(actor)):
        # No live credential is loaded by this isolated local application.
        return source_statuses(store, user, plan_id)

    @app.post(prefix + "/plans/{plan_id}/sources/{kind}")
    def source_one(plan_id: int, kind: str, user=Depends(actor)):
        from planner.daily_crm import source_status

        with store.connection() as db:
            store.plan(db, user, plan_id, True)
        return source_status(store, user, plan_id, kind)

    def lead_operator(user):
        if user.role not in {"supervisor", "admin"}:
            raise HTTPException(
                403, "Назначение лидов доступно руководителю или администратору LeadFlow."
            )

    def remembered(db, user, identifier, operation):
        row = (
            db.execute(
                text("SELECT * FROM local_lead_operations WHERE id=:id"), {"id": str(identifier)}
            )
            .mappings()
            .first()
        )
        if row and (row["actor_id"] != user.id or row["operation"] != operation):
            raise HTTPException(409, "Ключ операции уже использован. Обновите список.")
        return row

    @app.post("/api/v1/local-leads/{lead_id}/assign")
    def assign_local_lead(
        lead_id: int,
        body: AssignInput,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        from app.api.routes.leads import ensure_manager, visible_lead
        from app.schemas.lead import LeadRead
        from app.services.leads import LeadService, NoAvailableManagerError

        lead_operator(user)
        operation = f"assign:{lead_id}:{body.manager_id}"
        old = remembered(db, user, body.request_id, operation)
        lead = visible_lead(db, lead_id, user)
        if not old:
            ensure_manager(db, body.manager_id)
            try:
                manager_id = body.manager_id or LeadService(db).select_manager().id
            except NoAvailableManagerError:
                raise HTTPException(409, "Нет доступных менеджеров на смене.") from None
            from datetime import UTC, datetime

            if lead.manager_id != manager_id:
                lead.manager_id = manager_id
                lead.transferred_at = datetime.now(UTC)
            db.execute(
                text("INSERT INTO local_lead_operations VALUES(:id,:actor,:operation,:lead)"),
                {
                    "id": str(body.request_id),
                    "actor": user.id,
                    "operation": operation,
                    "lead": lead.id,
                },
            )
            db.commit()
            db.refresh(lead)
        return LeadRead.model_validate(lead)

    @app.post("/api/v1/local-leads", status_code=201)
    def create_local_lead(
        body: LocalLeadInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ):
        from app.api.routes.leads import ensure_manager, ensure_source, visible_lead
        from app.models.lead import Lead
        from app.schemas.lead import LeadRead
        from app.services.leads import LeadService, NoAvailableManagerError

        lead_operator(user)
        operation = "create:" + hashlib.sha256(body.lead.model_dump_json().encode()).hexdigest()
        old = remembered(db, user, body.request_id, operation)
        if old:
            return LeadRead.model_validate(visible_lead(db, old["lead_id"], user))
        values = body.lead.model_dump(exclude={"auto_assign"})
        ensure_manager(db, values["manager_id"])
        ensure_source(db, values["source"])
        try:
            if body.lead.auto_assign and values["manager_id"] is None:
                values["manager_id"] = LeadService(db).select_manager().id
        except NoAvailableManagerError:
            raise HTTPException(409, "Нет доступных менеджеров на смене.") from None
        lead = Lead(**values)
        db.add(lead)
        db.flush()
        db.execute(
            text("INSERT INTO local_lead_operations VALUES(:id,:actor,:operation,:lead)"),
            {"id": str(body.request_id), "actor": user.id, "operation": operation, "lead": lead.id},
        )
        db.commit()
        db.refresh(lead)
        # No LeadService.create notification and no CRM worker in this factory.
        return LeadRead.model_validate(lead)

    @app.get(prefix + "/distribution/options")
    def distribution_options(user=Depends(actor)):
        return {
            "managers": distribution.managers(user),
            "can_confirm": user.get("telegram_id") in authorized,
            "source": "Искусственный источник для изолированных локальных тестов",
            "confirm_stage": "IN_PROCESS",
        }

    @app.post(prefix + "/distribution/calculate")
    async def calculate(body: CalculationInput, user=Depends(actor)):
        try:
            return await asyncio.wait_for(
                distribution.calculate(
                    user, body.employee_ids, body.period, body.stages, body.dates
                ),
                12,
            )
        except (ValueError, TimeoutError):
            raise HTTPException(422, "Расчёт недоступен. Проверьте даты и повторите.") from None

    @app.post(prefix + "/distribution/previous")
    async def previous(body: PreviousInput, user=Depends(actor)):
        if not set(body.stages) <= {"IN_PROCESS", "PROCESSED", "NEW"}:
            raise HTTPException(422, "Некорректные стадии.")
        try:
            return await asyncio.wait_for(
                distribution.previous(user, body.before, body.excluded, body.stages), 12
            )
        except (ValueError, TimeoutError):
            raise HTTPException(422, "Дата или источник недоступны.") from None

    @app.post(prefix + "/distribution/{identifier}/confirm")
    async def distribution_confirm(identifier: str, body: ConfirmInput, user=Depends(actor)):
        try:
            return await asyncio.wait_for(
                distribution.confirm(user, identifier, body.variant_index), 12
            )
        except TimeoutError:
            raise HTTPException(
                503,
                (
                    "Источник не ответил вовремя. Сначала проверьте историю; "
                    "повтор того же варианта безопасен."
                ),
            ) from None

    @app.get(prefix + "/distribution/history")
    def distribution_history(user=Depends(actor)):
        return distribution.history(user)

    assets = root / "frontend" / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="local-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith(("api/", "local-control/")):
            raise HTTPException(404)
        return FileResponse(root / "frontend" / "index.html")

    return app
