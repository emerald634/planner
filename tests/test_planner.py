import hashlib
import hmac
import json
import sqlite3
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from unittest.mock import patch

from fastapi.testclient import TestClient

from access import AccessStore
from planner.api import create_app
from planner.auth import InvalidInitData, validate_init_data
from planner.settings import Settings
from planner.store import Store, today

TOKEN = "123456:synthetic_planner_test_token"
MANAGER = 8306778724
SUPERVISOR = 1073597301
OTHER = 22222222
ADMIN = 33333333


def signed(user=MANAGER, timestamp=None, token=TOKEN, **extra):
    values = {"auth_date": str(int(time.time()) if timestamp is None else timestamp),
              "user": json.dumps({"id": user, "first_name": "Test"}, separators=(",", ":")), **extra}
    secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
    values["hash"] = hmac.digest(secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), "sha256").hex()
    return urlencode(values)


class AuthTests(unittest.TestCase):
    def test_valid_signature_and_unicode(self):
        self.assertEqual(validate_init_data(signed(signature="abc", query_id="тест"), TOKEN), MANAGER)

    def test_invalid_missing_duplicate_expired_future_or_forged_identity(self):
        valid = signed()
        cases = ["", "user=1", valid + "&auth_date=1", valid.replace(str(MANAGER), str(OTHER)),
                 signed(token="different"), signed(timestamp=int(time.time()) - 43201),
                 signed(timestamp=int(time.time()) + 60), signed(user="8306778724"), signed(user=True),
                 signed(user=0), signed(user=2**63), "a" * 16385]
        for value in cases:
            with self.subTest(value=value[:30]), self.assertRaises(InvalidInitData):
                validate_init_data(value, TOKEN)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.access = AccessStore(self.root / "access.db")
        self.access.initialize([MANAGER, SUPERVISOR, OTHER, ADMIN])
        self.settings = Settings(TOKEN, self.root / "planner.db", self.access.path, frozenset({ADMIN}), static_dir=self.root / "missing")
        self.before_access = self.access.path.read_bytes()
        self.app = create_app(self.settings)
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.app.state.store
        self.supervisor = self.store.actor(SUPERVISOR)
        self.store.save_employee(self.supervisor, {"name": "Яна", "telegram_id": OTHER, "bitrix_id": 110, "active": True}, 2)

    def call(self, method, path, data=None, user=MANAGER):
        return self.client.request(method, "/api" + path, json=data, headers={"Authorization": "tma " + signed(user)})

    def plan(self, day=None, user=MANAGER, employee_id=None):
        response = self.call("POST", "/plans", {"day": day or today(), "employee_id": employee_id}, user)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, plan, user=MANAGER, **changes):
        response = self.call("POST", f"/plans/{plan['id']}/tasks", {"title": "Звонки", "kind": "quantitative", "target": 20, "planned_minutes": 60, **changes}, user)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_access_db_unchanged_and_roles_independent(self):
        self.assertEqual(self.access.path.read_bytes(), self.before_access)
        self.assertEqual(self.call("GET", "/me").json()["user"]["role"], "manager")
        self.assertEqual(self.call("GET", "/me", user=ADMIN).status_code, 403)
        self.assertEqual(self.call("GET", "/employees").status_code, 403)
        self.assertEqual(self.call("GET", "/employees", user=SUPERVISOR).status_code, 200)
        self.access.remove_user(MANAGER)
        self.assertEqual(self.call("GET", "/me").status_code, 403)

    def test_no_public_auth_bypass_or_client_roles(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.get("/api/plans?telegram_id=8306778724&role=supervisor").status_code, 401)
        self.assertEqual(self.call("POST", "/employees", {"name": "X", "role": "supervisor"}, SUPERVISOR).status_code, 422)
        self.assertEqual(self.client.get("/.env").status_code, 404)
        self.assertEqual(self.client.get("/docs").status_code, 404)

    def test_disabled_employee_and_missing_access_db_fail_closed(self):
        self.store.save_employee(self.supervisor, {"name": "Яна", "telegram_id": OTHER, "bitrix_id": 110, "active": False}, 2)
        self.assertEqual(self.call("GET", "/me", user=OTHER).status_code, 403)
        self.access.path.unlink()
        self.assertEqual(self.call("GET", "/me").status_code, 503)
        self.assertFalse(self.access.path.exists())

    def test_owner_checks_every_plan_task_report_and_request(self):
        plan = self.plan()
        task = self.task(plan)
        paths = [("GET", f"/plans/{plan['id']}", None), ("GET", f"/plans/{plan['id']}/history", None),
                 ("GET", f"/plans/{plan['id']}/report", None), ("GET", "/plans?employee_id=1", None),
                 ("POST", f"/plans/{plan['id']}/tasks", {"title": "чужая"}),
                 ("POST", f"/plans/{plan['id']}/close", None),
                 ("PATCH", f"/tasks/{task['id']}", {"revision": 1, "target": 9}),
                 ("POST", f"/tasks/{task['id']}/timer", {"action": "start"}),
                 ("POST", f"/tasks/{task['id']}/move", {"revision": 1, "day": "2099-01-01", "reason": "X"}),
                 ("POST", f"/tasks/{task['id']}/requests", {"proposed": 9, "reason": "X"})]
        for method, path, data in paths:
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, data, OTHER).status_code, 403)
        self.assertEqual(self.call("GET", f"/plans/{plan['id']}", user=SUPERVISOR).status_code, 200)

    def test_goal_approval_old_target_and_audit(self):
        plan = self.plan()
        task = self.task(plan)
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/approve").status_code, 403)
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/approve", user=SUPERVISOR).status_code, 200)
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "target": 8}).status_code, 403)
        req = self.call("POST", f"/tasks/{task['id']}/requests", {"proposed": 8, "reason": "Сложные переговоры"}).json()
        self.assertEqual(self.call("GET", f"/plans/{plan['id']}").json()["tasks"][0]["target"], 20)
        self.assertEqual(self.call("GET", "/requests", user=OTHER).json(), [])
        self.assertEqual(self.call("POST", f"/requests/{req['id']}/decision", {"decision": "approved"}).status_code, 403)
        self.assertEqual(self.call("POST", f"/requests/{req['id']}/decision", {"decision": "approved", "comment": "Согласовано"}, SUPERVISOR).status_code, 200)
        self.assertEqual(self.call("POST", f"/requests/{req['id']}/decision", {"decision": "approved"}, SUPERVISOR).status_code, 409)
        updated = self.call("GET", f"/plans/{plan['id']}").json()
        self.assertEqual(updated["tasks"][0]["target"], 8)
        self.assertEqual(updated["initial_snapshot"]["tasks"][0]["target"], 20)
        audit = self.call("GET", f"/plans/{plan['id']}/history").json()
        event = next(a for a in audit if a["action"] == "goal_changed")
        self.assertEqual(event["before_json"]["target"], 20)
        self.assertEqual(event["after_json"]["target"], 8)

    def test_supervisor_task_lock_fact_edit_and_rejection(self):
        plan = self.plan()
        task = self.task(plan, user=SUPERVISOR)
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "title": "обход"}).status_code, 403)
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "actual_value": 5, "comment": "Готово"}).status_code, 200)
        req = self.call("POST", f"/tasks/{task['id']}/requests", {"field": "planned_minutes", "proposed": 30, "reason": "X"}).json()
        self.assertEqual(self.call("POST", f"/requests/{req['id']}/decision", {"decision": "rejected", "comment": "Оставляем план"}, SUPERVISOR).status_code, 200)
        self.assertEqual(self.call("GET", f"/plans/{plan['id']}").json()["tasks"][0]["planned_minutes"], 60)

    def test_stale_goal_request_cannot_overwrite_new_supervisor_value(self):
        plan = self.plan()
        task = self.task(plan)
        req = self.call("POST", f"/tasks/{task['id']}/requests", {"proposed": 8, "reason": "X"}).json()
        self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "target": 50}, SUPERVISOR)
        self.assertEqual(self.call("POST", f"/requests/{req['id']}/decision", {"decision": "approved"}, SUPERVISOR).status_code, 409)

    def test_timer_restores_after_new_store_and_prevents_overlap(self):
        plan = self.plan()
        task = self.task(plan)
        other = self.task(plan)
        with patch("planner.store.time.time", return_value=1000):
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/timer", {"action": "start"}).status_code, 200)
        with patch("planner.store.time.time", return_value=1065):
            # patched time module is shared with auth/signer, which still sign consistently.
            fresh = Store(self.settings.database)
            self.assertEqual(fresh.get_plan(fresh.actor(MANAGER), plan["id"])["tasks"][0]["elapsed_seconds"], 65)
            self.assertEqual(self.call("POST", f"/tasks/{other['id']}/timer", {"action": "start"}).status_code, 409)
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/timer", {"action": "pause"}).json()["actual_seconds"], 65)
        with patch("planner.store.time.time", return_value=1100):
            self.call("POST", f"/tasks/{task['id']}/timer", {"action": "start"})
        with patch("planner.store.time.time", return_value=1120):
            stopped = self.call("POST", f"/tasks/{task['id']}/timer", {"action": "stop"}).json()
            self.assertEqual(stopped["actual_seconds"], 85)
            self.assertIsNone(stopped["timer_started"])

    def test_concurrent_timers_and_stale_revision(self):
        plan = self.plan()
        tasks = [self.task(plan), self.task(plan)]
        with ThreadPoolExecutor(2) as pool:
            statuses = list(pool.map(lambda t: self.call("POST", f"/tasks/{t['id']}/timer", {"action": "start"}).status_code, tasks))
        self.assertEqual(sorted(statuses), [200, 409])
        task = next(t for t in self.call("GET", f"/plans/{plan['id']}").json()["tasks"] if t["timer_started"])
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": task["revision"], "actual_minutes": 10}).status_code, 409)
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "comment": "stale"}).status_code, 409)

    def test_move_retains_fact_and_is_not_completion(self):
        plan = self.plan()
        task = self.task(plan, user=SUPERVISOR)
        current = self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "actual_minutes": 15, "actual_value": 5}).json()
        req = self.call("POST", f"/tasks/{task['id']}/requests", {"proposed": 8, "reason": "X"}).json()
        tomorrow = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
        moved = self.call("POST", f"/tasks/{task['id']}/move", {"revision": current["revision"], "day": tomorrow, "reason": "Продолжу завтра"})
        self.assertEqual(moved.status_code, 200, moved.text)
        new = moved.json()
        self.assertEqual((new["actual_seconds"], new["actual_value"], new["status"], new["locked"]), (0, 0, "todo", 1))
        original = self.call("GET", f"/plans/{plan['id']}").json()
        self.assertEqual(original["tasks"][0]["actual_seconds"], 900)
        self.assertEqual(original["summary"]["done"], 0)
        self.assertEqual(original["summary"]["moved"], 1)
        self.assertEqual(self.call("GET", "/requests").json()[0]["status"], "cancelled")
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": current["revision"] + 1, "status": "done"}).status_code, 409)

    def test_closed_report_immutable_and_timers_stopped(self):
        plan = self.plan()
        task = self.task(plan)
        self.call("POST", f"/tasks/{task['id']}/timer", {"action": "start"})
        snapshot = self.call("POST", f"/plans/{plan['id']}/close").json()
        self.assertIsNone(snapshot["tasks"][0]["timer_started"])
        self.assertEqual(snapshot, self.call("GET", f"/plans/{plan['id']}/report").json())
        self.assertEqual(snapshot, self.call("POST", f"/plans/{plan['id']}/close").json())
        for user in (MANAGER, SUPERVISOR):
            self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 3, "comment": "rewrite"}, user).status_code, 409)
            self.assertEqual(self.call("POST", f"/plans/{plan['id']}/tasks", {"title": "late"}, user).status_code, 409)
        with self.store.connection(True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE reports SET snapshot='{}'")

    def test_copy_previous_weekday_resets_fact_and_preserves_lock(self):
        friday = self.plan("2026-10-09")
        task = self.task(friday, user=SUPERVISOR)
        self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "actual_value": 15, "status": "done"})
        weekend = self.plan("2026-10-11")
        self.task(weekend, title="Выходной")
        response = self.call("POST", "/plans", {"day": "2026-10-12", "from_previous": True})
        self.assertEqual(response.status_code, 201, response.text)
        copied = response.json()["tasks"][0]
        self.assertEqual((copied["title"], copied["actual_value"], copied["status"], copied["locked"]), ("Звонки", 0, "todo", 1))

    def test_external_tasks_read_only_no_fake_statistics(self):
        plan = self.plan()
        task = self.task(plan)
        with self.store.connection(True) as db:
            db.execute("UPDATE tasks SET kind='bitrix',external_id='test' WHERE id=?", (task["id"],))
        for user in (MANAGER, SUPERVISOR):
            self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"revision": 1, "status": "done"}, user).status_code, 403)
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/timer", {"action": "start"}, user).status_code, 403)
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", {"revision": 1, "day": "2099-01-01", "reason": "X"}, user).status_code, 403)
        self.assertFalse(self.call("GET", "/me").json()["crm"]["connected"])

    def test_invalid_values_and_task_kind_and_mass_assignment(self):
        plan = self.plan()
        for data in ({"title": ""}, {"title": "X", "kind": "bitrix"}, {"title": "X", "kind": "quantitative"},
                     {"title": "X", "employee_id": 2}, {"title": "X", "planned_minutes": -1},
                     {"title": "X", "planned_minutes": 1.2}, {"title": "X", "target": 10}):
            self.assertEqual(self.call("POST", f"/plans/{plan['id']}/tasks", data).status_code, 422)
        task = self.task(plan)
        for data in ({"revision": 1, "target": None}, {"revision": 1, "locked": 0}, {"revision": 1, "plan_id": 2}, {"revision": 1, "actual_value": -1}):
            self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", data).status_code, 422)

    def test_migration_is_idempotent_and_refuses_access_database(self):
        self.store.initialize()
        self.assertEqual(len(self.store.employees(self.supervisor)), 2)
        with self.assertRaises(RuntimeError):
            Store(self.access.path).initialize()
        self.assertEqual(self.access.path.read_bytes(), self.before_access)
        with self.assertRaises(ValueError):
            create_app(Settings(TOKEN, self.access.path, self.access.path))
