"""Read-only Bitrix24 client: the only REST method used is crm.item.list."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)
USER_ERROR = "Не удалось получить данные из Bitrix24. Попробуйте позже."


class BitrixError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(USER_ERROR)


@dataclass(frozen=True)
class Lead:
    id: int
    created_at: datetime
    stage_id: str


class BitrixClient:
    def __init__(self, webhook_url: str, stage_id: str, timezone: ZoneInfo,
                 client: httpx.AsyncClient) -> None:
        self._url = webhook_url.rstrip("/") + "/crm.item.list.json"
        self._stage_id = stage_id
        self._timezone = timezone
        self._client = client

    def _midnight(self, day: date) -> str:
        return datetime.combine(day, time.min, self._timezone).isoformat()

    async def _page(self, filters: dict[str, Any], start: int = 0,
                    newest_first: bool = False,
                    stage_ids: Iterable[str] | None = None) -> tuple[list[Lead], int | None]:
        stages = tuple(dict.fromkeys(stage_ids)) if stage_ids is not None else (self._stage_id,)
        if not stages or any(not stage for stage in stages):
            raise ValueError("Выберите хотя бы одну настроенную стадию.")
        stage_filter = {"=stageId": stages[0]} if len(stages) == 1 else {"@stageId": list(stages)}
        payload = {
            "entityTypeId": 1,
            "select": ["id", "createdTime", "stageId"],
            "filter": {**stage_filter, **filters},
            "order": {"createdTime": "DESC", "id": "DESC"} if newest_first else {"id": "ASC"},
            "start": start,
        }
        try:
            response = await self._client.post(self._url, json=payload, timeout=30.0,
                                               follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            logger.warning("Bitrix request failed: type=%s status=%s", type(exc).__name__, status)
            raise BitrixError() from None
        try:
            data = response.json()
            if not isinstance(data, dict) or "error" in data:
                raise ValueError("API error")
            items = data["result"]["items"]
            if not isinstance(items, list):
                raise ValueError("items must be a list")
            leads = [self._parse_lead(item) for item in items]
            if any(lead.stage_id not in stages for lead in leads):
                raise ValueError("Unexpected lead stage")
            next_page = data.get("next")
            if next_page is not None and (type(next_page) is not int or next_page <= start or not leads):
                raise ValueError("Invalid pagination")
            return leads, next_page
        except (ValueError, TypeError, KeyError, OverflowError):
            logger.warning("Bitrix returned an API error or an invalid response structure")
            raise BitrixError() from None

    def _parse_lead(self, item: Any) -> Lead:
        if not isinstance(item, dict):
            raise ValueError("Invalid lead")
        raw_id = item["id"]
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            raise ValueError("Invalid lead ID")
        lead_id = int(raw_id)
        if lead_id <= 0:
            raise ValueError("Invalid lead ID")
        created_at = datetime.fromisoformat(item["createdTime"])
        if created_at.tzinfo is None:
            raise ValueError("Missing timezone")
        stage_id = item["stageId"]
        if not isinstance(stage_id, str) or not stage_id:
            raise ValueError("Invalid lead stage")
        return Lead(lead_id, created_at.astimezone(self._timezone), stage_id)

    async def get_leads(self, first_day: date, last_day: date,
                        stage_ids: Iterable[str] | None = None) -> list[Lead]:
        """Inclusive calendar range, expressed as [midnight, next midnight)."""
        if first_day > last_day:
            raise ValueError("Invalid date range")
        filters = {">=createdTime": self._midnight(first_day),
                   "<createdTime": self._midnight(last_day + timedelta(days=1))}
        start = 0
        stages = tuple(stage_ids) if stage_ids is not None else None
        found: dict[int, Lead] = {}
        while True:
            leads, next_page = await self._page(filters, start, stage_ids=stages)
            if next_page is not None and all(lead.id in found for lead in leads):
                logger.warning("Bitrix pagination made no progress")
                raise BitrixError()
            for lead in leads:
                if not first_day <= lead.created_at.date() <= last_day:
                    logger.warning("Bitrix returned a lead outside the requested date range")
                    raise BitrixError()
                found[lead.id] = lead
            if next_page is None:
                return list(found.values())
            start = next_page

    async def counts_for_dates(self, dates: Iterable[date],
                               stage_ids: Iterable[str] | None = None) -> dict[date, int]:
        breakdown = await self.counts_by_stage_for_dates(dates, stage_ids)
        return {day: sum(counts.values()) for day, counts in breakdown.items()}

    async def counts_by_stage_for_dates(self, dates: Iterable[date],
                                        stage_ids: Iterable[str] | None = None) -> dict[date, dict[str, int]]:
        """Fetch contiguous ranges together, without downloading gaps between them."""
        days = sorted(set(dates))
        stages = tuple(dict.fromkeys(stage_ids)) if stage_ids is not None else (self._stage_id,)
        counts = {day: dict.fromkeys(stages, 0) for day in days}
        if not days:
            return counts
        ranges: list[tuple[date, date]] = []
        first = last = days[0]
        for day in days[1:]:
            if day - last == timedelta(days=1):
                last = day
            else:
                ranges.append((first, last))
                first = last = day
        ranges.append((first, last))
        for first, last in ranges:
            for lead in await self.get_leads(first, last, stages):
                counts[lead.created_at.date()][lead.stage_id] += 1
        return counts

    async def count_for_date(self, day: date, stage_ids: Iterable[str] | None = None) -> int:
        return (await self.counts_for_dates([day], stage_ids))[day]

    async def find_previous_nonempty(self, before: date,
                                     excluded: Iterable[date] = (),
                                     stage_ids: Iterable[str] | None = None) -> tuple[date, int] | None:
        found = await self.find_previous_nonempty_by_stage(before, excluded, stage_ids)
        return (found[0], sum(found[1].values())) if found else None

    async def find_previous_nonempty_by_stage(self, before: date,
                                             excluded: Iterable[date] = (),
                                             stage_ids: Iterable[str] | None = None) -> tuple[date, dict[str, int]] | None:
        """Jump over empty history using the most recent lead before the cursor."""
        excluded_days = set(excluded)
        stages = tuple(stage_ids) if stage_ids is not None else None
        while True:
            leads, _ = await self._page({"<createdTime": self._midnight(before)}, newest_first=True, stage_ids=stages)
            if not leads:
                return None
            day = max(lead.created_at.date() for lead in leads)
            if day >= before:
                logger.warning("Bitrix returned an invalid previous date")
                raise BitrixError()
            if day not in excluded_days:
                counts = (await self.counts_by_stage_for_dates([day], stages))[day]
                if sum(counts.values()):
                    return day, counts
            before = day
