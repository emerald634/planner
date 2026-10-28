"""Real HTTP contract checks against ONE owned synthetic local MVP, never production."""

import argparse
import json
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
from run_working_web import owned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root, info = owned(args.run)
    origin = f"http://127.0.0.1:{info['port']}"
    accounts = json.loads((root / "credentials.json").read_text(encoding="utf-8"))
    results = []

    @contextmanager
    def client(name):
        browser = httpx.Client(base_url=origin, timeout=15, trust_env=False)
        account = next(a for a in accounts if a["email"].startswith(name + "@"))
        response = mutation(
            browser,
            "/auth/login",
            {"email": account["email"], "password": account["password"]},
        )
        assert response.status_code == 200, "Synthetic login failed"
        try:
            yield browser
        finally:
            browser.close()

    def mutation(browser, path, body=None, method="POST"):
        bootstrap = browser.get("/api/v1/local/csrf")
        assert bootstrap.status_code == 200
        return browser.request(
            method,
            "/api/v1" + path,
            json=body,
            headers={"Origin": origin, "X-CSRF-Token": bootstrap.json()["csrf"]},
        )

    with (
        client("manager") as manager,
        client("supervisor") as supervisor,
        client("admin") as admin,
    ):
        day = (date(2000, 1, 1) + timedelta(days=random.randrange(7000))).isoformat()
        while manager.get(f"/api/v1/planner/plans?day={day}").json():
            day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        response = mutation(manager, "/planner/plans", {"day": day, "employee_id": 1})
        assert response.status_code == 201
        plan = response.json()
        response = mutation(
            manager,
            f"/planner/plans/{plan['id']}/tasks",
            {
                "title": "Контрактная синтетическая задача",
                "kind": "quantitative",
                "target": 12,
                "planned_minutes": 30,
            },
        )
        assert response.status_code == 201
        task = response.json()
        response = mutation(
            manager,
            f"/planner/tasks/{task['id']}",
            {
                "revision": task["revision"],
                "actual_value": 4,
                "result": "Сохранено",
                "comment": "Только искусственные данные",
            },
            "PATCH",
        )
        assert response.status_code == 200
        stale = mutation(
            manager,
            f"/planner/tasks/{task['id']}",
            {"revision": task["revision"], "result": "Не должно сохраниться"},
            "PATCH",
        )
        assert stale.status_code == 409
        results.append("real Store revision/409 and persisted task")
        confirmed = mutation(manager, f"/planner/plans/{plan['id']}/confirm").json()
        again = mutation(manager, f"/planner/plans/{plan['id']}/confirm").json()
        assert confirmed["approved_at"] == again["approved_at"]
        assert confirmed["initial_snapshot"] == again["initial_snapshot"]
        history = manager.get(f"/api/v1/planner/plans/{plan['id']}/history").json()
        assert sum(event["action"] == "plan_confirmed" for event in history) == 1
        current = manager.get(f"/api/v1/planner/plans/{plan['id']}").json()["tasks"][0]
        assert (
            mutation(
                manager,
                f"/planner/tasks/{task['id']}",
                {"revision": current["revision"], "target": 100},
                "PATCH",
            ).status_code
            == 403
        )
        results.append(
            "repeat confirmation preserves snapshot/audit; approved targets protected"
        )
        # Synthetic inbox fixture ONLY; does not claim a Bitrix/queue import.
        with sqlite3.connect(root / "planner.sqlite") as fixture:
            fixture.execute("PRAGMA foreign_keys=ON")
            distribution = "synthetic-" + uuid.uuid4().hex
            payload = json.dumps(
                {
                    "allocations": [
                        {"telegram_id": None, "bitrix_id": None, "dates": [day]}
                    ]
                }
            )
            fixture.execute(
                "INSERT INTO distributions VALUES(?,?,?,?,'imported','',0)",
                (distribution, day, "a" * 64, payload),
            )
            fixture.execute(
                "INSERT INTO distribution_tasks VALUES(?,?,?,'imported')",
                (distribution, 1, task["id"]),
            )
        assert (
            mutation(
                supervisor,
                f"/planner/tasks/{task['id']}",
                {"revision": current["revision"], "target": 99},
                "PATCH",
            ).status_code
            == 403
        )
        assert (
            mutation(
                manager,
                f"/planner/tasks/{task['id']}/requests",
                {"field": "target", "proposed": 99, "reason": "Не должно пройти"},
            ).status_code
            == 403
        )
        results.append(
            "synthetic imported target protected for supervisor and manager goal request"
        )
        goal = mutation(
            manager,
            f"/planner/tasks/{task['id']}/requests",
            {
                "field": "planned_minutes",
                "proposed": 45,
                "reason": "Синтетическое согласование",
            },
        )
        assert goal.status_code == 201
        assert (
            mutation(
                manager,
                f"/planner/requests/{goal.json()['id']}/decision",
                {"decision": "approved"},
            ).status_code
            == 403
        )
        assert (
            mutation(
                supervisor,
                f"/planner/requests/{goal.json()['id']}/decision",
                {"decision": "approved"},
            ).status_code
            == 200
        )
        rejected = mutation(
            manager,
            f"/planner/tasks/{task['id']}/requests",
            {"field": "planned_minutes", "proposed": 60, "reason": "Тест отклонения"},
        )
        assert (
            mutation(
                supervisor,
                f"/planner/requests/{rejected.json()['id']}/decision",
                {"decision": "rejected"},
            ).status_code
            == 200
        )
        current = manager.get(f"/api/v1/planner/plans/{plan['id']}").json()["tasks"][0]
        assert current["planned_minutes"] == 45
        assert (
            mutation(
                manager,
                f"/planner/tasks/{task['id']}",
                {"revision": current["revision"], "employee_id": 2},
                "PATCH",
            ).status_code
            == 422
        )
        results.append(
            "supervisor approves/rejects goals; client actor injection rejected"
        )
        assert (
            mutation(manager, f"/planner/plans/{plan['id']}/close").status_code == 200
        )
        report = manager.get(f"/api/v1/planner/plans/{plan['id']}/report").json()
        assert (
            mutation(
                manager,
                f"/planner/tasks/{task['id']}",
                {"revision": current["revision"], "comment": "Закрыто"},
                "PATCH",
            ).status_code
            == 409
        )
        assert (
            manager.get(f"/api/v1/planner/plans/{plan['id']}/report").json() == report
        )
        results.append("closed day immutable; saved report remains identical")
        assert len(supervisor.get("/api/v1/planner/employees").json()) == 2
        assert manager.get("/api/v1/planner/employees").status_code == 403
        assert manager.get("/api/v1/planner/plans?employee_id=2").status_code == 403
        assert admin.get("/api/v1/planner/me").status_code == 403
        results.append("ownership, supervisor gate, no automatic admin promotion")
        cookie = manager.cookies.get("leadflow_local_session")
        assert mutation(manager, "/auth/logout").status_code == 204
        with httpx.Client(
            base_url=origin,
            trust_env=False,
            headers={"Cookie": "leadflow_local_session=" + cookie},
        ) as replay:
            assert replay.get("/api/v1/planner/me").status_code == 401
        results.append("logout revokes exact server token; replay denied")
        with client("manager") as other_device:
            old_cookie = other_device.cookies.get("leadflow_local_session")
            try:
                assert (
                    mutation(
                        admin, "/users/101", {"is_active": False}, "PATCH"
                    ).status_code
                    == 200
                )
                assert other_device.get("/api/v1/planner/me").status_code == 401
            finally:
                assert (
                    mutation(
                        admin, "/users/101", {"is_active": True}, "PATCH"
                    ).status_code
                    == 200
                )
            assert other_device.get("/api/v1/planner/me").status_code == 401
            assert old_cookie
        results.append("disable/re-enable does not revive a session")
        try:
            assert (
                mutation(
                    admin, "/users/101", {"role": "supervisor"}, "PATCH"
                ).status_code
                == 200
            )
            with client("manager") as conflict:
                assert conflict.get("/api/v1/planner/me").status_code == 403
        finally:
            assert (
                mutation(admin, "/users/101", {"role": "manager"}, "PATCH").status_code
                == 200
            )
        results.append("conflicting mapping fails closed after canonical role change")
        with client("unmapped") as unmapped:
            assert unmapped.get("/api/v1/planner/me").status_code == 403
        foreign = admin.post(
            "/api/v1/planner/plans",
            headers={"Origin": "https://foreign.invalid"},
            json={},
        )
        assert foreign.status_code == 403
        assert (
            admin.post(
                "/api/v1/planner/plans", headers={"Origin": origin}, json={}
            ).status_code
            == 403
        )
        assert (
            admin.get(
                "/api/v1/planner/me", headers={"Host": "foreign.invalid"}
            ).status_code
            == 403
        )
        results.append(
            "unmapped identity, cross-origin, missing CSRF and foreign Host denied"
        )
    with httpx.Client(base_url=origin, trust_env=False) as anonymous:
        assert (
            anonymous.get(
                "/api/v1/planner/me",
                headers={"Authorization": "tma synthetic-not-a-web-session"},
            ).status_code
            == 401
        )
    results.append("Telegram initData does not replace shared web session")
    output = Path(__file__).resolve().parents[2] / "test-artifacts/browser-core" / args.run
    output.mkdir(parents=True, exist_ok=True)
    (output / "api-contract-results.json").write_text(
        json.dumps(
            {
                "success": True,
                "checks": results,
                "synthetic_plan_id": plan["id"],
                "synthetic_task_id": task["id"],
                "saved_report": {
                    "day": report["day"],
                    "status": report["status"],
                    "tasks": len(report["tasks"]),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"success": True, "checks": len(results)}))


if __name__ == "__main__":
    main()
