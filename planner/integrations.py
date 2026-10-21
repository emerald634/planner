"""Contracts for stage 2. No network calls or synthetic CRM statistics."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class DeadlineOutcome(StrEnum):
    WORK_DONE_AND_MOVED = "work_done_and_moved"
    DEADLINE_ONLY = "deadline_only"


@dataclass(frozen=True)
class ExternalTask:
    external_id: str
    title: str
    url: str
    deadline: datetime | None
    external_status: str
    # Work completed today is independent of the external task's final status.
    work_done_today: bool = False
    deadline_outcome: DeadlineOutcome | None = None


class ReadOnlyCRM(Protocol):
    async def tasks(self, bitrix_user_id: int, day: str) -> list[ExternalTask]: ...
    async def call_statistics(self, bitrix_user_id: int, day: str, long_call_seconds: int = 180) -> dict: ...
    async def deals(self, bitrix_user_id: int, category_id: int) -> list[dict]: ...


CRM_STATUS = {"connected": False, "message": "Данные Bitrix24 появятся на следующем этапе.",
              "deal_categories": [0, 2], "long_call_seconds": 180, "read_only": True}
