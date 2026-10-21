"""Hotfix compatibility: isolated SQLite, synthetic signed Telegram identities only."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from access import AccessStore
from planner.api import create_app
from planner.settings import Settings
from tests.test_planner import TOKEN, signed


class HotfixRoleCompatibilityTests(unittest.TestCase):
    def test_two_supervisors_and_two_managers_have_independent_access(self):
        with TemporaryDirectory(prefix="hotfix-roles-") as directory:
            root = Path(directory)
            access = AccessStore(root / "access.db")
            access.initialize([101, 102, 901, 902])
            app = create_app(Settings(TOKEN, root / "planner.db", access.path, static_dir=root / "missing"))
            with TestClient(app) as client:
                with app.state.store.connection(True) as db:
                    db.execute("UPDATE employees SET telegram_id=101 WHERE id=1")
                    db.execute("UPDATE employees SET telegram_id=102 WHERE id=2")
                    db.execute("UPDATE employees SET active=0 WHERE role='supervisor'")
                    for identity in (901, 902):
                        db.execute("INSERT INTO employees(telegram_id,name,role,active) VALUES(?,?,'supervisor',1)",
                                   (identity, f"Synthetic supervisor {identity}"))

                def call(identity, path, method="GET", data=None):
                    return client.request(method, "/api" + path, json=data,
                                          headers={"Authorization": "tma " + signed(identity)})

                plans = []
                for identity in (101, 102):
                    me = call(identity, "/me")
                    self.assertEqual(me.status_code, 200)
                    self.assertEqual(me.json()["user"]["role"], "manager")
                    self.assertEqual(call(identity, "/employees").status_code, 403)
                    plan = call(identity, "/plans", "POST", {"day": me.json()["today"]})
                    self.assertEqual(plan.status_code, 201)
                    plans.append(plan.json())
                for identity in (901, 902):
                    self.assertEqual(call(identity, "/me").json()["user"]["role"], "supervisor")
                    staff = call(identity, "/employees").json()
                    self.assertEqual({e["telegram_id"] for e in staff if e["active"]}, {101, 102})
                    self.assertEqual(len(call(identity, "/plans").json()), 2)
                    for plan in plans:
                        self.assertEqual(call(identity, f"/plans/{plan['id']}").status_code, 200)
                self.assertEqual(call(101, f"/plans/{plans[1]['id']}").status_code, 403)
                self.assertEqual(call(102, f"/plans/{plans[0]['id']}").status_code, 403)
                with app.state.store.connection(True) as db:
                    db.execute("UPDATE employees SET active=0 WHERE telegram_id=901")
                self.assertEqual(call(901, "/me").status_code, 403)
                self.assertEqual(call(902, "/employees").status_code, 200)


if __name__ == "__main__":
    unittest.main()
