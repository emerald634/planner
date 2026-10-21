import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from planner.distribution_import import import_snapshot
from planner.store import today
from tests.test_distribution_import import snapshot, Y, V
from tests import test_planner as baseline
from tests.test_planner import MANAGER, SUPERVISOR, OTHER


class ConfirmationTests(unittest.TestCase):
    setUp = baseline.PlannerTests.setUp
    call = baseline.PlannerTests.call
    plan = baseline.PlannerTests.plan
    task = baseline.PlannerTests.task

    def imported(self):
        with self.store.connection(True) as db:
            db.execute("UPDATE employees SET telegram_id=? WHERE bitrix_id=110", (Y,))
        self.access.add_user(Y, MANAGER)
        value = snapshot()
        value["workday"] = today()
        value["confirmed_at"] = today() + "T10:00:00+03:00"
        first = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
        second = (date.fromisoformat(today()) - timedelta(days=2)).isoformat()
        for allocation, day in zip(value["allocations"], (first, second)):
            allocation["dates"] = [day]
            allocation["leads"][0]["created_date"] = day
        import_snapshot(self.store, value, {V})
        plan = self.store.list_plans(self.store.actor(V), day=today())[0]
        return self.call("GET", f"/plans/{plan['id']}").json()

    def test_confirm_own_repeat_preserves_snapshot_time_history_and_role(self):
        plan = self.plan()
        self.task(plan)
        response = self.call("POST", f"/plans/{plan['id']}/confirm")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["approved_by"], self.store.actor(MANAGER)["id"])
        original = (result["initial_snapshot"], result["approved_at"])
        history = self.call("GET", f"/plans/{plan['id']}/history").json()
        event = [r for r in history if r["action"] == "plan_confirmed"]
        self.assertEqual(len(event), 1)
        self.assertEqual(event[0]["after_json"]["confirmed_by_telegram_id"], MANAGER)
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 200)
        again = self.call("GET", f"/plans/{plan['id']}").json()
        self.assertEqual(original, (again["initial_snapshot"], again["approved_at"]))
        self.assertEqual(history, self.call("GET", f"/plans/{plan['id']}/history").json())
        self.assertEqual(self.call("GET", "/me").json()["user"]["role"], "manager")

    def test_foreign_supervisor_closed_unauthorized_and_old_approve(self):
        plan = self.plan()
        for user in (OTHER, SUPERVISOR):
            self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm", user=user).status_code, 403)
        self.assertEqual(self.client.post(f"/api/plans/{plan['id']}/confirm").status_code, 401)
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/approve").status_code, 403)
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/approve", user=SUPERVISOR).status_code, 200)
        before = self.call("GET", f"/plans/{plan['id']}").json()["initial_snapshot"]
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 200)
        self.assertEqual(before, self.call("GET", f"/plans/{plan['id']}").json()["initial_snapshot"])
        self.call("POST", f"/plans/{plan['id']}/close")
        report = self.call("GET", f"/plans/{plan['id']}/report").json()
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 409)
        self.assertEqual(report, self.call("GET", f"/plans/{plan['id']}/report").json())

    def test_concurrent_confirm_only_one_event(self):
        plan = self.plan()
        actor = self.store.actor(MANAGER)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.store.confirm_plan(actor, plan["id"]), range(2)))
        self.assertEqual(results[0]["initial_snapshot"], results[1]["initial_snapshot"])
        events = self.store.history(actor, plan["id"])
        self.assertEqual(sum(e["action"] == "plan_confirmed" for e in events), 1)

    def test_disabled_manager_denied_and_other_goals_use_approval(self):
        plan = self.plan()
        task = self.task(plan)
        with self.store.connection(True) as db:
            db.execute("UPDATE employees SET active=0 WHERE telegram_id=?", (MANAGER,))
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 403)
        with self.store.connection(True) as db:
            db.execute("UPDATE employees SET active=1 WHERE telegram_id=?", (MANAGER,))
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 200)
        path = f"/tasks/{task['id']}"
        self.assertEqual(self.call("PATCH", path, {"revision": task["revision"], "target": 30}).status_code, 403)
        request = self.call("POST", path + "/requests", {"field": "target", "proposed": 30, "reason": "Больше работы"})
        self.assertEqual(request.status_code, 201)
        self.assertEqual(self.call("POST", f"/requests/{request.json()['id']}/decision", {"decision": "approved"}, SUPERVISOR).status_code, 200)
        after = self.call("GET", f"/plans/{plan['id']}").json()
        self.assertEqual(after["tasks"][0]["target"], 30)
        self.assertEqual(after["initial_snapshot"]["tasks"][0]["target"], 20)

    def test_imported_target_all_roles_requests_move_delete_and_forgery(self):
        plan = self.imported()
        task = plan["tasks"][0]
        path = f"/tasks/{task['id']}"
        for user in (MANAGER, SUPERVISOR):
            self.assertEqual(self.call("PATCH", path, {"revision": task["revision"], "target": 999}, user).status_code, 403)
            self.assertEqual(self.call("POST", path + "/move", {"revision": task["revision"], "day": (date.fromisoformat(today()) + timedelta(days=1)).isoformat(), "reason": "test"}, user).status_code, 403)
            self.assertIn(self.call("DELETE", path, user=user).status_code, (404, 405))
        self.assertEqual(self.call("POST", path + "/requests", {"field": "target", "proposed": 99, "reason": "test"}).status_code, 403)
        for field in ("distribution_target_locked", "locked", "plan_id", "kind", "source_task_id"):
            self.assertEqual(self.call("PATCH", path, {"revision": task["revision"], field: 0}).status_code, 422)
        # Legacy pending request cannot bypass the new approval guard.
        with self.store.connection(True) as db:
            request = db.execute("INSERT INTO goal_requests(task_id,employee_id,field,old_value,proposed,reason,created_at) VALUES(?,?,'target',1,99,'legacy',1)", (task["id"], task["employee_id"])).lastrowid
        self.assertEqual(self.call("POST", f"/requests/{request}/decision", {"decision": "approved"}, SUPERVISOR).status_code, 403)
        self.assertEqual(self.call("GET", f"/plans/{plan['id']}").json()["tasks"][0]["target"], 1)

    def test_copy_skips_imported_but_keeps_other_tasks(self):
        plan = self.imported()
        self.task(plan, title="Обычная цель")
        day = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
        result = self.call("POST", "/plans", {"day": day, "from_previous": True})
        self.assertEqual(result.status_code, 201)
        self.assertEqual([t["title"] for t in result.json()["tasks"]], ["Обычная цель"])

    def test_execution_and_time_approval_continue_after_confirmation(self):
        plan = self.imported()
        task = plan["tasks"][0]
        self.assertEqual(self.call("POST", f"/plans/{plan['id']}/confirm").status_code, 200)
        path = f"/tasks/{task['id']}"
        self.assertEqual(self.call("POST", path + "/timer", {"action": "start"}).status_code, 200)
        self.assertEqual(self.call("POST", path + "/timer", {"action": "stop"}).status_code, 200)
        current = self.call("GET", f"/plans/{plan['id']}").json()["tasks"][0]
        self.assertEqual(self.call("PATCH", path, {"revision": current["revision"], "actual_value": 1, "actual_minutes": 3, "comment": "Готово", "result": "Обработано", "status": "done"}).status_code, 200)
        request = self.call("POST", path + "/requests", {"field": "planned_minutes", "proposed": 20, "reason": "Нужно время"})
        self.assertEqual(request.status_code, 201)
        self.assertEqual(self.call("POST", f"/requests/{request.json()['id']}/decision", {"decision": "approved"}, SUPERVISOR).status_code, 200)
        current = self.call("GET", f"/plans/{plan['id']}").json()["tasks"][0]
        self.assertEqual((current["actual_value"], current["planned_minutes"], current["target"]), (1, 20, 1))
