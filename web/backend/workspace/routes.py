"""Shared business routes for server runtime; no local identities or fixture imports."""

import asyncio
from datetime import date

from fastapi import Depends, HTTPException, Request
from planner.daily import DailyInput
from planner.daily_crm import SOURCE_NAMES, source_status
from planner.models import DecisionInput, GoalInput, PlanInput, TaskInput, TaskPatch, TimerInput
from planner.server_migration import cached_observation
from planner.store import today
from pydantic import BaseModel, ConfigDict, Field


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


def register_routes(
    app, store, actor, distribution, confirm_remote, gateway=None, refresh_source=None
):
    prefix = "/api/v1/planner"

    @app.get(prefix + "/me")
    def me(user=Depends(actor)):
        return {
            "user": user,
            "today": today(),
            "timezone": "Europe/Moscow",
            "crm": {
                "connected": False,
                "configured": gateway is not None,
                "message": (
                    "Доступность каждого источника CRM проверяется отдельно. "
                    "Ручной учёт сохраняется."
                ),
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
        return [
            cached_observation(store, user, plan_id, kind)
            or source_status(store, user, plan_id, kind)
            for kind in SOURCE_NAMES
        ]

    @app.get(prefix + "/distribution/options")
    def distribution_options(user=Depends(actor)):
        return {
            "managers": distribution.managers(user),
            "can_confirm": user.get("_can_confirm", False),
            "source": "Bitrix24: только чтение; состояние доступа проверяется отдельно",
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
    async def distribution_confirm(
        identifier: str, body: ConfirmInput, request: Request, user=Depends(actor)
    ):
        if not user.get("_can_confirm"):
            raise HTTPException(403, "Нет отдельного права подтверждения.")
        return await confirm_remote(request, identifier, body.variant_index)

    @app.get(prefix + "/distribution/history")
    def distribution_history(user=Depends(actor)):
        return distribution.history(user)

    @app.get(prefix + "/plans/{plan_id}/sources/{kind}")
    def source(plan_id: int, kind: str, user=Depends(actor)):
        return cached_observation(store, user, plan_id, kind) or source_status(
            store, user, plan_id, kind
        )
