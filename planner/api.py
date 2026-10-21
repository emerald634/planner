import sqlite3
import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import InvalidInitData, validate_init_data
from .frontend import validate_static
from .integrations import CRM_STATUS
from .models import (DecisionInput, EmployeeInput, EmployeePatch, GoalInput, MoveInput,
                     PlanInput, TaskInput, TaskPatch, TimerInput)
from .settings import WORKDAY, Settings, load_settings
from .store import DomainError, Store, today


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    if (settings.database.resolve() == settings.access_database.resolve()
            or (settings.database.exists() and settings.access_database.exists() and settings.database.samefile(settings.access_database))):
        raise ValueError("Базы планировщика и доступа должны отличаться.")
    store = Store(settings.database)

    @asynccontextmanager
    async def lifespan(app):
        if settings.production:
            try:
                validate_static(settings.static_dir, settings.static_dir.parent.parent / "frontend-build.json")
            except (ValueError, OSError):
                raise RuntimeError("Нет проверенной production-сборки Mini App или нарушена её целостность.") from None
        store.initialize()
        from .sync import sync_loop
        worker = asyncio.create_task(sync_loop(store, settings.distribution_queue, settings.distribution_confirmer_ids, settings.distribution_poll_seconds)) if settings.distribution_queue else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app = FastAPI(title="План дня", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "Запись уже существует или конфликтует с другим изменением. Обновите данные."}, status_code=409)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Хранилище временно недоступно. Повторите позже."}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Never echo raw inputs, initData, or exception context back to the client.
        return JSONResponse({"detail": "Проверьте заполнение полей и допустимые значения."}, status_code=422)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
        )
        return response

    def actor(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("tma "):
            raise HTTPException(401, "Откройте приложение из Telegram.")
        try:
            telegram_id = validate_init_data(authorization[4:], settings.bot_token, settings.init_data_max_age)
        except InvalidInitData as exc:
            raise HTTPException(401, str(exc)) from None
        # Read-only connection cannot create or migrate the existing access DB.
        if telegram_id not in settings.bot_admin_ids:
            try:
                connection = sqlite3.connect(settings.access_database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
                try:
                    allowed = connection.execute("SELECT 1 FROM allowed_users WHERE telegram_id=?", (telegram_id,)).fetchone()
                finally:
                    connection.close()
            except sqlite3.Error:
                raise HTTPException(503, "Не удалось проверить доступ к боту.") from None
            if not allowed:
                raise HTTPException(403, "Нет доступа к боту. Обратитесь к администратору.")
        # An existing bot admin never becomes a Mini App supervisor automatically.
        return store.actor(telegram_id)

    @app.get("/api/me")
    def me(user=Depends(actor)):
        return {"user": user, "today": today(), "timezone": "Europe/Moscow", "workday": WORKDAY, "crm": CRM_STATUS}

    @app.get("/healthz", include_in_schema=False)
    def health():
        # No identity or business data; readiness requires both databases.
        try:
            for path, sql in ((settings.database, "SELECT 1 FROM plans LIMIT 1"),
                              (settings.access_database, "SELECT 1 FROM allowed_users LIMIT 1")):
                connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
                try:
                    connection.execute(sql).fetchone()
                finally:
                    connection.close()
        except sqlite3.Error:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.get("/api/employees")
    def employees(user=Depends(actor)):
        return store.employees(user)

    @app.get("/api/distributions")
    def distributions(employee_id: int | None = None, user=Depends(actor)):
        from .sync import distribution_notices
        return distribution_notices(store, user, employee_id)

    @app.post("/api/employees", status_code=201)
    def add_employee(body: EmployeeInput, user=Depends(actor)):
        return store.save_employee(user, body.model_dump())

    @app.patch("/api/employees/{employee_id}")
    def edit_employee(employee_id: int, body: EmployeePatch, user=Depends(actor)):
        return store.save_employee(user, body.model_dump(), employee_id)

    @app.get("/api/plans")
    def plans(employee_id: int | None = None, day: date | None = None, user=Depends(actor)):
        return store.list_plans(user, employee_id, day.isoformat() if day else None)

    @app.post("/api/plans", status_code=201)
    def add_plan(body: PlanInput, user=Depends(actor)):
        return store.create_plan(user, body.day.isoformat(), body.employee_id, body.from_previous)

    @app.get("/api/plans/{plan_id}")
    def plan(plan_id: int, user=Depends(actor)):
        return store.get_plan(user, plan_id)

    @app.post("/api/plans/{plan_id}/approve")
    def approve(plan_id: int, user=Depends(actor)):
        return store.approve_plan(user, plan_id)

    @app.post("/api/plans/{plan_id}/confirm")
    def confirm(plan_id: int, user=Depends(actor)):
        return store.confirm_plan(user, plan_id)

    @app.post("/api/plans/{plan_id}/close")
    def close(plan_id: int, user=Depends(actor)):
        return store.close_plan(user, plan_id)

    @app.get("/api/plans/{plan_id}/report")
    def report(plan_id: int, user=Depends(actor)):
        return store.report(user, plan_id)

    @app.get("/api/plans/{plan_id}/history")
    def history(plan_id: int, user=Depends(actor)):
        return store.history(user, plan_id)

    @app.post("/api/plans/{plan_id}/tasks", status_code=201)
    def add_task(plan_id: int, body: TaskInput, user=Depends(actor)):
        return store.add_task(user, plan_id, body.model_dump())

    @app.patch("/api/tasks/{task_id}")
    def edit_task(task_id: int, body: TaskPatch, user=Depends(actor)):
        return store.patch_task(user, task_id, body.model_dump(exclude_unset=True))

    @app.post("/api/tasks/{task_id}/timer")
    def timer(task_id: int, body: TimerInput, user=Depends(actor)):
        return store.timer(user, task_id, body.action)

    @app.post("/api/tasks/{task_id}/move")
    def move(task_id: int, body: MoveInput, user=Depends(actor)):
        return store.move(user, task_id, body.day.isoformat(), body.reason, body.revision)

    @app.post("/api/tasks/{task_id}/requests", status_code=201)
    def goal_request(task_id: int, body: GoalInput, user=Depends(actor)):
        return store.request_goal(user, task_id, body.model_dump())

    @app.get("/api/requests")
    def requests(user=Depends(actor)):
        return store.requests(user)

    @app.post("/api/requests/{request_id}/decision")
    def decision(request_id: int, body: DecisionInput, user=Depends(actor)):
        return store.decide(user, request_id, body.decision, body.comment)

    # Only compiled frontend assets are served, never the workspace or .env.
    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="miniapp")
    return app
