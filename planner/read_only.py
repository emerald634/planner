"""Filesystem-enforced companions for server queue/identity boundaries."""

import sqlite3
from contextlib import contextmanager

from .daily import DailyStore
from .distribution_queue import DistributionQueue


class ReadOnlyStore(DailyStore):
    @contextmanager
    def connection(self, write=False):
        if write:
            raise PermissionError("Writer cannot change planner.db")
        connection = sqlite3.connect(
            self.path.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=2
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()


class ReadOnlyQueue(DistributionQueue):
    def initialize(self):
        raise PermissionError("Reader cannot initialize queue")

    def publish(self, *args):
        raise PermissionError("Reader cannot publish")
