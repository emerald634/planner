"""Persistent web calculations, original algorithm and schema1 queue authority.

Queue.publish is the SAME atomic per-Moscow-day authority used by Telegram.
This service never writes CRM or modifies an existing confirmation.
"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from distribution import best_distributions, previous_days

from .distribution_queue import BINDINGS, MOSCOW, canonical, validate
from .confirmation_reads import read_dates
from .store import DomainError


def initialize_previews(store):
    with store.connection(True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS web_distribution_previews(
            id TEXT PRIMARY KEY, actor_id INTEGER NOT NULL REFERENCES employees(id),
            workday TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL)""")


class WebDistribution:
    def __init__(self, store, queue, crm, authorized_ids):
        self.store, self.queue, self.crm = store, queue, crm
        self.authorized_ids = frozenset(authorized_ids)

    def check(self, actor, confirm=False):
        with self.store.connection() as db:
            row = self.store.row(
                db, "SELECT * FROM employees WHERE id=? AND active=1", (actor["id"],)
            )
        if row["role"] != actor["role"] or not row.get("telegram_id"):
            raise DomainError("Нет подтверждённой привязки распределителя.", 403)
        if confirm and row["telegram_id"] not in self.authorized_ids:
            raise DomainError("Нет отдельного права подтверждать распределение.", 403)
        return row

    def managers(self, actor):
        self.check(actor)
        with self.store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,name,telegram_id,bitrix_id FROM employees WHERE active=1 AND role='manager'"
                )
                if BINDINGS.get(r["telegram_id"]) == r["bitrix_id"]
            ]

    async def calculate(self, actor, employee_ids, period, stages, dates=None):
        self.check(actor)
        if (
            not employee_ids
            or len(employee_ids) > 2
            or len(set(employee_ids)) != len(employee_ids)
        ):
            raise DomainError(
                "Выберите одного или двух разных активных менеджеров.", 422
            )
        managers = {m["id"]: m for m in self.managers(actor)}
        if any(i not in managers for i in employee_ids):
            raise DomainError("Есть сотрудник без активной привязки.", 422)
        if (
            not stages
            or len(set(stages)) != len(stages)
            or not set(stages) <= {"IN_PROCESS", "PROCESSED", "NEW"}
        ):
            raise DomainError("Некорректные стадии.", 422)
        now = datetime.now(MOSCOW)
        with self.store.connection() as db:
            count = db.execute(
                "SELECT count(*) FROM web_distribution_previews WHERE actor_id=? AND workday=?",
                (actor["id"], now.date().isoformat()),
            ).fetchone()[0]
            if count >= 50:
                raise DomainError(
                    "Достигнут лимит50 расчётов на сотрудника в день. Используйте сохранённый расчёт."
                )
        defaults = previous_days(period, MOSCOW, now)
        dates = (
            [date.fromisoformat(x) for x in dates]
            if dates is not None
            else list(defaults)
        )
        if (
            len(dates) != period
            or len(set(dates)) != len(dates)
            or any(
                d >= now.date() or d < now.date() - timedelta(days=3660) for d in dates
            )
        ):
            raise DomainError("Выберите разные прошлые даты в пределах10 лет.", 422)
        counts = await self.crm.counts_for_dates(dates, stage_ids=tuple(stages))
        variants = best_distributions(
            counts, [managers[i]["name"] for i in employee_ids]
        )
        identifier = str(uuid4())
        payload = {
            "id": identifier,
            "workday": now.date().isoformat(),
            "stages": stages,
            "managers": [managers[i] for i in employee_ids],
            "dates": [{"day": d.isoformat(), "count": counts[d]} for d in dates],
            "variants": [
                [
                    {
                        "employee_id": employee_ids[i],
                        "name": a.manager,
                        "dates": [
                            {"day": d.isoformat(), "count": n} for d, n in a.days
                        ],
                        "count": a.total,
                    }
                    for i, a in enumerate(v.allocations)
                ]
                for v in variants
            ],
        }
        with self.store.connection(True) as db:
            # Recheck under write lock: simultaneous requests share the quota.
            if (
                db.execute(
                    "SELECT count(*) FROM web_distribution_previews WHERE actor_id=? AND workday=?",
                    (actor["id"], payload["workday"]),
                ).fetchone()[0]
                >= 50
            ):
                raise DomainError("Достигнут дневной лимит расчётов.")
            db.execute(
                "INSERT INTO web_distribution_previews VALUES(?,?,?,?,?)",
                (
                    identifier,
                    actor["id"],
                    payload["workday"],
                    canonical(payload),
                    int(time.time()),
                ),
            )
        return payload

    async def previous(self, actor, before, excluded, stages):
        self.check(actor)
        if (
            date.fromisoformat(before) >= datetime.now(MOSCOW).date()
            or len(excluded) > 15
        ):
            raise DomainError("Некорректная дата.", 422)
        found = await self.crm.find_previous_nonempty(
            date.fromisoformat(before),
            [date.fromisoformat(x) for x in excluded],
            stage_ids=tuple(stages),
        )
        return {"day": found[0].isoformat(), "count": found[1]} if found else None

    async def confirm(self, actor, identifier, variant_index):
        actor = self.check(actor, True)
        with self.store.connection() as db:
            row = self.store.row(
                db,
                "SELECT * FROM web_distribution_previews WHERE id=? AND actor_id=?",
                (identifier, actor["id"]),
            )
        preview = json.loads(row["payload"])
        if type(variant_index) is not int or not 0 <= variant_index < len(
            preview["variants"]
        ):
            raise DomainError("Устаревший вариант.", 422)
        confirmation_id = str(uuid5(UUID(identifier), str(variant_index)))
        existing = await asyncio.to_thread(self.queue.find, confirmation_id)
        if existing is not None:
            return existing
        now = datetime.now(MOSCOW)
        if (
            preview["workday"] != now.date().isoformat()
            or int(time.time()) - row["created_at"] > 3600
            or preview["stages"] != ["IN_PROCESS"]
        ):
            raise DomainError(
                "Расчёт устарел или содержит стадии вне IN_PROCESS. Обновите расчёт."
            )
        active = {m["id"]: m for m in self.managers(actor)}
        allocations = []
        seen = set()
        seen_dates = set()
        fresh_by_day = await read_dates(self.crm, [
            date.fromisoformat(bucket["day"])
            for item in preview["variants"][variant_index] for bucket in item["dates"]
        ])
        for item in preview["variants"][variant_index]:
            manager = active.get(item["employee_id"])
            original = next(
                (m for m in preview["managers"] if m["id"] == item["employee_id"]), None
            )
            if manager != original:
                raise DomainError("Привязка сотрудника изменилась. Обновите расчёт.")
            leads = []
            for bucket in item["dates"]:
                day = date.fromisoformat(bucket["day"])
                fresh = fresh_by_day[day]
                if len(fresh) != bucket["count"] or day in seen_dates:
                    raise DomainError(
                        "Количество или даты изменились. Обновите расчёт."
                    )
                seen_dates.add(day)
                for lead in fresh:
                    if (
                        lead.id in seen
                        or lead.stage_id != "IN_PROCESS"
                        or lead.created_at.astimezone(MOSCOW).date() != day
                    ):
                        raise DomainError(
                            "Повтор или неверная дата лида. Обновите расчёт."
                        )
                    seen.add(lead.id)
                    leads.append(
                        {
                            "id": lead.id,
                            "created_date": day.isoformat(),
                            "stage_id": lead.stage_id,
                        }
                    )
            allocations.append(
                {
                    "telegram_id": manager["telegram_id"],
                    "bitrix_id": manager["bitrix_id"],
                    "name": manager["name"],
                    "dates": [d["day"] for d in item["dates"]],
                    "leads": sorted(leads, key=lambda l: l["id"]),
                    "count": len(leads),
                }
            )
        snapshot = {
            "schema": 1,
            "distribution_id": confirmation_id,
            "variant_id": confirmation_id,
            "variant_index": variant_index,
            "workday": preview["workday"],
            "confirmed_at": now.isoformat(),
            "confirmed_by": actor["telegram_id"],
            "stage_id": "IN_PROCESS",
            "allocations": allocations,
            "total": len(seen),
        }
        validate(snapshot)
        # Recheck active bindings after CRM I/O. No cross-DB write locks are held.
        self.check(actor,True)
        current={m['id']:m for m in self.managers(actor)}
        if any(current.get(m['id'])!=m for m in preview['managers']):
            raise DomainError('Привязки изменились во время проверки. Обновите расчёт.')
        try:
            await asyncio.to_thread(self.queue.publish, snapshot, self.authorized_ids)
        except ValueError:
            # Concurrent same-variant request has a different timestamp: return
            # the ORIGINAL authoritative snapshot rather than rewrite it.
            existing = await asyncio.to_thread(self.queue.find, confirmation_id)
            if existing is not None:
                return existing
            raise DomainError(
                "На этот московский день уже подтверждён другой вариант."
            ) from None
        return snapshot

    def history(self, actor):
        actor = self.check(actor)
        result = []
        for snapshot in self.queue.read():
            allocations = (
                snapshot["allocations"]
                if actor["role"] == "supervisor"
                else [
                    x
                    for x in snapshot["allocations"]
                    if x["telegram_id"] == actor["telegram_id"] and x["bitrix_id"] == actor["bitrix_id"]
                ]
            )
            if not allocations:
                continue
            with self.store.connection() as db:
                imported = db.execute(
                    "SELECT status,reason FROM distributions WHERE id=?",
                    (snapshot["distribution_id"],),
                ).fetchone()
            result.append(
                {
                    "id": snapshot["distribution_id"],
                    "workday": snapshot["workday"],
                    "allocations": allocations,
                    "status": imported["status"] if imported else "pending",
                    "reason": imported["reason"] if imported else "",
                }
            )
        return result[-60:]
