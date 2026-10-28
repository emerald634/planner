"""Async bounded read-only lead transport for the shared writer/web calculation."""

import asyncio
import time
from contextvars import ContextVar

import httpx
from bitrix import BitrixClient, BitrixError


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        deadline = time.monotonic() + 8
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2_000_000 or time.monotonic() > deadline:
                raise httpx.ReadError("Source budget exceeded")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class LimitedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner=None):
        self.inner = inner or httpx.AsyncHTTPTransport(
            retries=0, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2)
        )

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        response.stream = LimitedStream(response.stream)
        return response

    async def aclose(self):
        await self.inner.aclose()


class BoundedLeads(BitrixClient):
    def __init__(self, *args):
        super().__init__(*args)
        self.budget = ContextVar("lead_budget", default=None)

    async def _page(self, *args, **kwargs):
        rows, nxt = await super()._page(*args, **kwargs)
        if len(rows) > 1000:
            raise BitrixError()
        budget = self.budget.get()
        if budget is not None:
            budget["pages"] += 1
            budget["ids"].update(x.id for x in rows)
            if budget["pages"] > 200 or len(budget["ids"]) > 10000:
                raise BitrixError()
        return rows, nxt

    async def get_leads(self, *args, **kwargs):
        token = self.budget.set({"pages": 0, "ids": set()})
        try:
            return await asyncio.wait_for(super().get_leads(*args, **kwargs), 8)
        except TimeoutError:
            raise BitrixError() from None
        finally:
            self.budget.reset(token)
