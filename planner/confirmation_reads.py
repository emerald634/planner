"""Bounded fresh confirmation reads; never publishes or changes CRM."""

import asyncio


async def read_dates(crm, dates):
    dates = list(dates)
    if not dates or len(dates) > 15 or len(set(dates)) != len(dates):
        raise ValueError("Invalid confirmation dates")
    gate = asyncio.Semaphore(2)

    async def read(day):
        async with gate:
            return day, await crm.get_leads(day, day, stage_ids=("IN_PROCESS",))

    # TaskGroup cancels siblings on failure; no detached reads after timeout.
    async with asyncio.timeout(8):
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(read(day)) for day in dates]
        except ExceptionGroup as error:
            raise error.exceptions[0] from None
    return dict(task.result() for task in tasks)
