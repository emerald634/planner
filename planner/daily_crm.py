"""Bounded read-only source adapters. Never reads environment or changes CRM."""

import time
import hashlib
import json
from datetime import date, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

import httpx

MOSCOW = ZoneInfo("Europe/Moscow")
HOT_STAGES = ("UC_OM0N7Q", "UC_Q6ZN5G", "EXECUTING", "UC_4FX5NE", "UC_4FG1MT")
READ_METHODS = frozenset(
    ("crm.item.list", "tasks.task.list", "voximplant.statistic.get")
)
MAX_SOURCE_BYTES = 8_000_000
MAX_PAGE_BYTES = 2_000_000


class SourceUnavailable(Exception):
    def __init__(self):
        super().__init__(
            "Источник CRM недоступен или ответ не прошёл проверку. Ручной факт сохранён."
        )


def strict_id(value, zero=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or not str(value).isascii()
        or not str(value).isdigit()
    ):
        raise SourceUnavailable()
    number = int(value)
    if number < (0 if zero else 1):
        raise SourceUnavailable()
    return number


class ReadOnlyCRM:
    """Inject explicitly after authorization; no settings/env lookup. 10k row cap."""

    def __init__(self, webhook, client):
        if not webhook.startswith("https://"):
            raise ValueError("HTTPS required")
        self._url, self._client = webhook.rstrip("/"), client

    def pages(self, method, params, collection, *, deadline=None, normalize=None):
        if method not in READ_METHODS:
            raise SourceUnavailable()
        deadline = deadline or time.monotonic() + 8
        found, start, loaded = {}, 0, 0
        try:
            for _ in range(200):
                if time.monotonic() >= deadline:
                    raise SourceUnavailable()
                with self._client.stream(
                    "POST",
                    self._url + "/" + method + ".json",
                    json={**params, "start": start},
                    timeout=max(0.01, min(2.0, deadline - time.monotonic())),
                    follow_redirects=False,
                ) as response:
                    response.raise_for_status()
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        loaded += len(chunk)
                        if (
                            size > MAX_PAGE_BYTES
                            or loaded > MAX_SOURCE_BYTES
                            or time.monotonic() >= deadline
                        ):
                            raise SourceUnavailable()
                        chunks.append(chunk)
                    payload = json.loads(b"".join(chunks))
                if not isinstance(payload, dict) or "error" in payload:
                    raise SourceUnavailable()
                result = payload["result"]
                items = result[collection] if collection else result
                if not isinstance(items, list):
                    raise SourceUnavailable()
                added = 0
                for item in items:
                    if time.monotonic() >= deadline:
                        raise SourceUnavailable()
                    if not isinstance(item, dict):
                        raise SourceUnavailable()
                    raw = item.get("id", item.get("ID", item.get("CALL_ID")))
                    if (
                        isinstance(raw, bool)
                        or not isinstance(raw, (int, str))
                        or not str(raw)
                        or len(str(raw)) > 100
                    ):
                        raise SourceUnavailable()
                    identifier = str(raw)
                    digest = hashlib.sha256(
                        json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
                    ).digest()
                    safe = normalize(item) if normalize else self.safe_fields(item)
                    previous = found.get(identifier)
                    if previous is not None and previous[0] != digest:
                        raise SourceUnavailable()
                    if previous is None:
                        found[identifier] = (digest, safe)
                        added += 1
                if len(found) > 10000:
                    raise SourceUnavailable()
                nxt = payload.get(
                    "next", result.get("next") if isinstance(result, dict) else None
                )
                if nxt is None:
                    return [entry[1] for entry in found.values()]
                if type(nxt) is not int or nxt <= start or not added:
                    raise SourceUnavailable()
                start = nxt
        except SourceUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
            raise SourceUnavailable() from None
        raise SourceUnavailable()

    @staticmethod
    def safe_fields(row):
        title = row.get("title", row.get("TITLE", ""))
        if not isinstance(title, str):
            raise SourceUnavailable()
        return {
            "id": str(row.get("id", row.get("ID", row.get("CALL_ID")))),
            "title": title[:180],
        }

    def source(self, kind, employee, day, *, deadline=None):
        deadline = deadline or time.monotonic() + 8
        if (
            not isinstance(employee, dict)
            or type(employee.get("bitrix_id")) is not int
            or employee["bitrix_id"] <= 0
        ):
            raise SourceUnavailable()
        first = datetime.combine(date.fromisoformat(day), day_time.min, MOSCOW)
        end = first + timedelta(days=1)
        owner = employee["bitrix_id"]

        def normalize(row):
            if kind in ("leads", "deals"):
                strict_id(row.get("id", row.get("ID")))
                if strict_id(row["assignedById"]) != owner:
                    raise SourceUnavailable()
                if (
                    kind == "leads"
                    and not first <= datetime.fromisoformat(row["createdTime"]) < end
                ):
                    raise SourceUnavailable()
                if kind == "deals" and (
                    strict_id(row["categoryId"], zero=True) != 0
                    or row["stageId"] not in HOT_STAGES
                ):
                    raise SourceUnavailable()
            elif kind == "tasks":
                strict_id(row.get("id", row.get("ID")))
                if (
                    strict_id(row.get("responsibleId", row.get("RESPONSIBLE_ID", 0)))
                    != owner
                ):
                    raise SourceUnavailable()
            elif kind == "calls":
                if (
                    strict_id(row["PORTAL_USER_ID"]) != owner
                    or str(row["CALL_TYPE"]) != "1"
                    or not first <= datetime.fromisoformat(row["CALL_START_DATE"]) < end
                ):
                    raise SourceUnavailable()
            return self.safe_fields(row)

        if kind == "leads":
            rows = self.pages(
                "crm.item.list",
                {
                    "entityTypeId": 1,
                    "select": ["id", "title", "assignedById", "createdTime", "stageId"],
                    "filter": {
                        "=assignedById": owner,
                        ">=createdTime": first.isoformat(),
                        "<createdTime": end.isoformat(),
                    },
                    "order": {"id": "ASC"},
                },
                "items",
                deadline=deadline,
                normalize=normalize,
            )
        elif kind == "deals":
            rows = self.pages(
                "crm.item.list",
                {
                    "entityTypeId": 2,
                    "select": ["id", "title", "assignedById", "categoryId", "stageId"],
                    "filter": {
                        "=assignedById": owner,
                        "=categoryId": 0,
                        "@stageId": list(HOT_STAGES),
                    },
                    "order": {"id": "ASC"},
                },
                "items",
                deadline=deadline,
                normalize=normalize,
            )
        elif kind == "tasks":
            rows = self.pages(
                "tasks.task.list",
                {
                    "filter": {
                        "RESPONSIBLE_ID": owner,
                        "<DEADLINE": end.isoformat(),
                        "!STATUS": 5,
                    },
                    "select": ["ID", "TITLE", "RESPONSIBLE_ID", "DEADLINE", "STATUS"],
                    "order": {"ID": "ASC"},
                },
                "tasks",
                deadline=deadline,
                normalize=normalize,
            )
        elif kind == "calls":
            rows = self.pages(
                "voximplant.statistic.get",
                {
                    "FILTER": {
                        "PORTAL_USER_ID": owner,
                        "CALL_TYPE": 1,
                        ">=CALL_START_DATE": first.isoformat(),
                        "<CALL_START_DATE": end.isoformat(),
                    },
                    "SORT": "ID",
                    "ORDER": "ASC",
                },
                None,
                deadline=deadline,
                normalize=normalize,
            )
        else:
            raise SourceUnavailable()
        # No claims about processing, quality, pain fields or payment receipt.
        if time.monotonic() >= deadline:
            raise SourceUnavailable()
        return rows


SOURCE_NAMES = {
    "leads": "Лиды",
    "deals": "Горячие сделки категории0",
    "tasks": "Задачи",
    "calls": "Телефония",
}


def source_status(store, actor, plan_id, kind, gateway=None):
    if kind not in SOURCE_NAMES:
        raise SourceUnavailable()
    with store.connection() as db:
        plan = store.plan(db, actor, plan_id)
        employee = store.row(
            db, "SELECT * FROM employees WHERE id=?", (plan["employee_id"],)
        )
    result = {"key": kind, "name": SOURCE_NAMES[kind], "updated_at": int(time.time())}
    try:
        if gateway is None:
            raise SourceUnavailable()
        items = gateway.source(
            kind, employee, plan["day"], deadline=time.monotonic() + 8
        )
        result.update(
            status="verified",
            items=items,
            source="Bitrix24 (только чтение)",
            projection=(
                {"calls.actual": len(items)}
                if kind == "calls"
                else {"new_leads.planned": len(items)}
                if kind == "leads"
                else {"pain.planned": len(items)}
                if kind == "deals"
                else {}
            ),
        )
    except (
        SourceUnavailable,
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        AttributeError,
    ):
        result.update(
            status="unavailable",
            items=None,
            projection={},
            error=str(SourceUnavailable()),
        )
    return result


def source_statuses(store, actor, plan_id, gateway=None):
    # Compatibility API: independent sources share a single 9s wall-clock budget.
    # Production uses /sources/{kind}; a stuck source never gates other responses.
    from concurrent.futures import ThreadPoolExecutor, wait

    pool = ThreadPoolExecutor(max_workers=4)
    futures = {
        pool.submit(source_status, store, actor, plan_id, kind, gateway): kind
        for kind in SOURCE_NAMES
    }
    done, _ = wait(futures, timeout=9)
    results = []
    for future, kind in futures.items():
        if future in done:
            results.append(future.result())
        else:
            future.cancel()
            results.append(
                {
                    "key": kind,
                    "name": SOURCE_NAMES[kind],
                    "status": "unavailable",
                    "items": None,
                    "projection": {},
                    "updated_at": int(time.time()),
                    "error": str(SourceUnavailable()),
                }
            )
    pool.shutdown(wait=False, cancel_futures=True)
    return results
