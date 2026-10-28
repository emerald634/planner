"""Synthetic CRM for owned loopback runs only. Never imports a live client."""

from datetime import datetime, timedelta

from bitrix import Lead
from planner.distribution_queue import MOSCOW


class SyntheticLeads:
    async def get_leads(self, first_day, last_day, stage_ids=None):
        stages = tuple(stage_ids or ("IN_PROCESS",))
        found = []
        day = first_day
        while day <= last_day:
            # Stable synthetic IDs. Every fourth date is empty, for replacement tests.
            for stage_index, stage in enumerate(("IN_PROCESS", "PROCESSED", "NEW")):
                if stage in stages:
                    for n in range(0 if day.toordinal() % 4 == 0 else day.toordinal() % 5 + 1):
                        found.append(
                            Lead(
                                day.toordinal() * 100 + stage_index * 20 + n,
                                datetime(day.year, day.month, day.day, 12, tzinfo=MOSCOW),
                                stage,
                            )
                        )
            day += timedelta(days=1)
        return found

    async def counts_for_dates(self, dates, stage_ids=None):
        return {d: len(await self.get_leads(d, d, stage_ids)) for d in dates}

    async def find_previous_nonempty(self, before, excluded=(), stage_ids=None):
        for offset in range(1, 367):
            day = before - timedelta(days=offset)
            if day not in excluded:
                count = len(await self.get_leads(day, day, stage_ids))
                if count:
                    return day, count
        return None
