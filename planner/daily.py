"""Additive daily indicators over the existing Store; explicit extension migration only.

No network, implicit seeding, or changes to the core schema version. Old reports
remain byte-for-byte immutable. Enable only in a reviewed application factory.
"""

import json
import time
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import DomainError, Store, encode

KEYS = (
    "calls",
    "new_leads",
    "missed",
    "consultations",
    "pain",
    "conversations",
    "overdue",
    "payments",
)
LABELS = (
    "Исходящие звонки",
    "Новые заявки",
    "Недозвоны",
    "Качественные консультации",
    "Выгрузка боли по горячим сделкам",
    "Разговоры с действующими и завершёнными",
    "Просроченные задачи Bitrix24",
    "Ожидающие оплату",
)
Count = Annotated[int, Field(strict=True, ge=0, le=1000000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Attempt(Strict):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    time: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    call: bool = False
    message: bool = False
    connected: bool = False
    result: Annotated[str, Field(max_length=1000)] = ""

    @model_validator(mode="after")
    def connection_needs_call(self):
        if self.connected and not self.call:
            raise ValueError("Разговор требует отметки звонка.")
        return self


class Detail(Strict):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    client: Annotated[str, Field(min_length=1, max_length=180)]
    entity_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    group: Literal["active", "completed", ""] = ""
    done: bool = False
    recommendation: bool = False
    payment_date: date | None = None
    touch_date: date | None = None
    result: Annotated[str, Field(max_length=2000)] = ""
    attempts: Annotated[list[Attempt], Field(max_length=30)] = []

    @model_validator(mode="after")
    def unique_attempts(self):
        if len({a.id for a in self.attempts}) != len(self.attempts):
            raise ValueError("Повтор попытки.")
        return self


class Indicator(Strict):
    key: Literal[
        "calls",
        "new_leads",
        "missed",
        "consultations",
        "pain",
        "conversations",
        "overdue",
        "payments",
    ]
    planned: Count = 0
    actual: Count = 0
    morning: Count = 0
    details: Annotated[list[Detail], Field(max_length=500)] = []

    @model_validator(mode="after")
    def unique_details(self):
        if len({d.id for d in self.details}) != len(self.details):
            raise ValueError("Повтор записи.")
        ids = [d.entity_id for d in self.details if d.entity_id is not None]
        if len(set(ids)) != len(ids):
            raise ValueError("Повтор CRM-карточки.")
        if self.key in ("consultations", "conversations"):
            if self.actual != sum(d.done for d in self.details):
                raise ValueError("Факт должен совпадать с детализацией клиентов.")
            if any(d.done and not d.result for d in self.details):
                raise ValueError("Укажите результат разговора/консультации.")
            if self.key == "conversations" and any(d.group == "" for d in self.details):
                raise ValueError("Укажите группу клиента.")
        return self


class DailyInput(Strict):
    revision: Annotated[int, Field(strict=True, ge=0)]
    indicators: Annotated[list[Indicator], Field(min_length=8, max_length=8)]
    contracts: Count = 0  # Weekly total, deliberately not a ninth daily row.

    @model_validator(mode="after")
    def keys(self):
        if {r.key for r in self.indicators} != set(KEYS):
            raise ValueError("Нужны все восемь показателей без повторов.")
        return self


def initialize_daily(store):
    """Explicit transaction; run on synthetic copy before considering release."""
    with store.connection(True) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise DomainError("Расширение требует проверенную core-схему4.")
        db.execute(
            "CREATE TABLE IF NOT EXISTS daily_extension(version INTEGER PRIMARY KEY CHECK(version=1))"
        )
        db.execute("INSERT OR IGNORE INTO daily_extension VALUES(1)")
        db.execute("""CREATE TABLE IF NOT EXISTS daily_records(
            plan_id INTEGER PRIMARY KEY REFERENCES plans(id), revision INTEGER NOT NULL,
            payload TEXT NOT NULL, updated_at INTEGER NOT NULL)""")


class DailyStore(Store):
    """Small opt-in extension; the original Store and Telegram API are unchanged."""

    def assigned(self, db, plan):
        return [
            dict(r)
            for r in db.execute(
                """SELECT l.lead_id,l.created_date
            FROM distribution_leads l JOIN distributions d ON d.id=l.distribution_id
            JOIN distribution_tasks t ON t.distribution_id=d.id AND t.employee_id=l.employee_id
            WHERE l.employee_id=? AND d.workday=? AND t.status='imported' ORDER BY l.lead_id""",
                (plan["employee_id"], plan["day"]),
            )
        ]

    def daily_detail(self, db, actor, plan_id):
        plan = self.plan(db, actor, plan_id)
        row = db.execute(
            "SELECT * FROM daily_records WHERE plan_id=?", (plan_id,)
        ).fetchone()
        assigned = self.assigned(db, plan)
        data = (
            json.loads(row["payload"])
            if row
            else {
                "indicators": [
                    {
                        "key": key,
                        "planned": {
                            "calls": 40,
                            "consultations": 2,
                            "conversations": 4,
                        }.get(key, 0),
                        "actual": 0,
                        "morning": 0,
                        "details": [],
                    }
                    for key in KEYS
                ],
                "contracts": 0,
            }
        )
        data.update(
            revision=row["revision"] if row else 0,
            updated_at=row["updated_at"] if row else None,
        )
        for item in data["indicators"]:
            item["label"] = LABELS[KEYS.index(item["key"])]
            item["source"] = data.get('seed_sources',{}).get(item['key'],"Ручной ввод сотрудника")
            if item["key"] == "missed":
                item["planned"] = len(assigned)
                item["source"] = (
                    "Подтверждённое распределение; попытки — ручные отметки"
                )
                by_id = {d["entity_id"]: d for d in item["details"]}
                item["details"] = [
                    dict(
                        by_id.get(
                            x["lead_id"],
                            {
                                "id": str(x["lead_id"]),
                                "entity_id": x["lead_id"],
                                "client": "Лид " + str(x["lead_id"]),
                                "attempts": [],
                            },
                        ),
                        created_date=x["created_date"],
                    )
                    for x in assigned
                ]
                item["actual"] = sum(
                    any(a["call"] for a in d["attempts"])
                    and any(a["message"] for a in d["attempts"])
                    for d in item["details"]
                )
                item["connected"] = sum(
                    any(a["connected"] for a in d["attempts"]) for d in item["details"]
                )
            item["remaining"] = max(0, item["planned"] - item["actual"])
        from .server_migration import seed_verified_draft

        seed_verified_draft(db, plan, data)
        return data

    def daily_get(self, actor, plan_id):
        with self.connection() as db:
            if self.plan(db, actor, plan_id)["status"] == "closed":
                report = json.loads(self.row(db, "SELECT snapshot FROM reports WHERE plan_id=?", (plan_id,))["snapshot"])
                if "daily" not in report:
                    raise DomainError("В прежнем отчёте нет дневных показателей.", 404)
                return report["daily"]
            return self.daily_detail(db, actor, plan_id)

    def daily_save(self, actor, plan_id, body):
        # Validate again at the service boundary (not only HTTP).
        body = DailyInput.model_validate(body).model_dump(mode="json")
        with self.connection(True) as db:
            current_actor = self.row(
                db, "SELECT * FROM employees WHERE id=? AND active=1", (actor["id"],)
            )
            if current_actor["role"] != actor["role"]:
                raise DomainError("Полномочия изменились.", 403)
            plan = self.plan(db, current_actor, plan_id, True)
            old = self.daily_detail(db, current_actor, plan_id)
            if old["revision"] != body.pop("revision"):
                raise DomainError(
                    "Показатели изменились. Обновите данные перед повтором."
                )
            old_by_key = {r["key"]: r for r in old["indicators"]}
            for item in body["indicators"]:
                key = item["key"]
                previous = old_by_key[key]
                if key in ("new_leads", "pain", "payments"):
                    if item["actual"] > item["planned"]:
                        raise DomainError("Факт не может превышать исходный список.")
                    if item["details"] and item["actual"] != sum(
                        d["done"] for d in item["details"]
                    ):
                        raise DomainError(
                            "Факт должен совпадать с выполненными карточками."
                        )
                if key == "payments" and any(
                    d["payment_date"] is None or d["touch_date"] != plan["day"]
                    for d in item["details"]
                ):
                    raise DomainError(
                        "Укажите ожидаемую оплату и касание на дату плана."
                    )
                if key == "missed":
                    ids = {x["lead_id"] for x in self.assigned(db, plan)}
                    if (
                        item["planned"] != len(ids)
                        or {d["entity_id"] for d in item["details"]} != ids
                    ):
                        raise DomainError("Исходный список недозвонов нельзя менять.")
                    if item["actual"] != previous["actual"]:
                        # Actual is derived below from call AND message, never trusted.
                        item["actual"] = previous["actual"]
                elif key in ("calls", "consultations", "conversations", "overdue"):
                    if item["planned"] != previous["planned"]:
                        raise DomainError(
                            "Норматив шаблона не изменяется этим действием."
                        )
                elif (
                    plan["status"] == "approved"
                    and actor["role"] == "manager"
                    and item["planned"] < previous["planned"]
                ):
                    raise DomainError(
                        "Снижение утверждённой цели требует решения руководителя."
                    )
            revision = old["revision"] + 1
            db.execute(
                """INSERT INTO daily_records VALUES(?,?,?,?) ON CONFLICT(plan_id)
                DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated_at=excluded.updated_at""",
                (plan_id, revision, encode(body), int(time.time())),
            )
            after = self.daily_detail(db, current_actor, plan_id)
            self.audit(
                db, current_actor, "daily", plan_id, "daily_saved", old, after, plan_id
            )
            return after

    def weekly(self, actor, employee_id, day):
        self.owner(actor, employee_id)
        start = date.fromisoformat(day)
        start -= timedelta(days=start.weekday())
        totals = {"calls": 0, "consultations": 0, "conversations": 0, "contracts": 0}
        days = []
        with self.connection() as db:
            for row in db.execute(
                "SELECT id,day FROM plans WHERE employee_id=? AND day>=? AND day<=?",
                (
                    employee_id,
                    start.isoformat(),
                    (start + timedelta(days=6)).isoformat(),
                ),
            ).fetchall():
                daily = self.daily_detail(db, actor, row["id"])
                for item in daily["indicators"]:
                    if item["key"] in totals:
                        totals[item["key"]] += item["actual"]
                totals["contracts"] += daily["contracts"]
                days.append(row["day"])
        return {
            "start": start.isoformat(),
            "totals": totals,
            "days": days,
            "targets": {
                "calls": 200,
                "consultations": 10,
                "conversations": 20,
                "contracts": 2,
            },
            "consultations_stretch": 15,
        }
