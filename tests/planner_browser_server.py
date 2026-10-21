"""Isolated UI test server: fake token, temporary databases, localhost only.

Run: python -m tests.planner_browser_server
Never use this module as the production entry point.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from datetime import date, timedelta

import uvicorn

from access import AccessStore
from planner.api import create_app
from planner.settings import ROOT, Settings


def main():
    with TemporaryDirectory(prefix="planner-ui-test-") as directory:
        root = Path(directory)
        access = AccessStore(root / "access.db")
        access.initialize([8306778724, 7939114214, 1073597301])
        extra = {}
        if '--hotfix' in sys.argv:
            from planner.store import Store
            store = Store(root / 'planner.db')
            store.initialize()
            with store.connection(True) as db:
                db.execute('UPDATE employees SET active=0 WHERE telegram_id=1073597301')
                db.execute("INSERT INTO employees(telegram_id,name,role,active) VALUES(4444444444,'Другой тестовый руководитель','supervisor',1)")
            access.add_user(4444444444, 8306778724)
        if '--distributions' in sys.argv:
            from planner.store import Store, today
            from planner.distribution_queue import DistributionQueue
            from tests.test_distribution_import import snapshot, V, S
            store = Store(root / 'planner.db')
            store.initialize()
            plan = store.create_plan(store.actor(V), today())
            store.approve_plan(store.actor(S), plan['id'])
            value = snapshot()
            value['workday'] = today()
            value['confirmed_at'] = today() + 'T10:00:00+03:00'
            for n, allocation in enumerate(value['allocations'], 1):
                day = (date.fromisoformat(today()) - timedelta(days=n)).isoformat()
                allocation['dates'] = [day]
                allocation['leads'][0]['created_date'] = day
            queue = DistributionQueue(root / 'queue.db')
            queue.initialize()
            queue.publish(value, {V})
            extra = dict(distribution_queue=queue.path, distribution_confirmer_ids=frozenset({V}), distribution_poll_seconds=0.05)
        app = create_app(Settings("123456:synthetic_planner_test_token", root / "planner.db", access.path,
                                  static_dir=ROOT / "miniapp" / "dist", **extra))
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
