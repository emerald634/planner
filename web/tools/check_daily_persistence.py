"""Hash-only persistence checks on a generated OWNED synthetic run, no secrets output."""

import argparse
import hashlib
import json
import os

import httpx
from run_working_web import owned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "verify", "queue-fault"))
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root, info = owned(args.run)
    origin = f"http://127.0.0.1:{info['port']}"
    account = next(
        a
        for a in json.loads((root / "credentials.json").read_text(encoding="utf-8"))
        if a["id"] == 101
    )
    with httpx.Client(base_url=origin, trust_env=False, timeout=15) as client:
        csrf = client.get("/api/v1/local/csrf").json()["csrf"]
        response = client.post(
            "/api/v1/auth/login",
            json={"email": account["email"], "password": account["password"]},
            headers={"Origin": origin, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        if args.mode == "queue-fault":
            queue = root / "distribution-queue.sqlite"
            hidden = root / "distribution-queue.sqlite.synthetic-hidden"
            assert queue.resolve().parent == root.resolve() and not hidden.exists()
            os.replace(queue, hidden)
            try:
                response = client.get("/api/v1/planner/distribution/history")
                assert response.status_code == 503
                assert set(response.json()) == {"detail"}
                # Ordinary plans stay usable while the queue is inaccessible.
                assert client.get("/api/v1/planner/plans").status_code == 200
            finally:
                os.replace(hidden, queue)
            assert client.get("/api/v1/planner/distribution/history").status_code == 200
            print("Synthetic queue unavailable503, plans200, queue restored200: passed")
            return
        plans = client.get("/api/v1/planner/plans").json()
        report = client.get(f"/api/v1/planner/plans/{plans[0]['id']}/report")
        assert report.status_code == 200
        history = client.get("/api/v1/planner/distribution/history")
        assert history.status_code == 200
        state = {
            "report_sha256": hashlib.sha256(report.content).hexdigest(),
            "plans": len(plans),
            "confirmations": len(history.json()),
            "daily_revision": report.json()["daily"]["revision"],
        }
        artifact = (
            root.parent.parent
            / "daily-workspace-checks"
            / args.run
            / "restart-state.json"
        )
        if args.mode == "snapshot":
            artifact.parent.mkdir(exist_ok=True, parents=True)
            artifact.write_text(json.dumps(state, indent=2), encoding="utf-8")
        else:
            assert json.loads(artifact.read_text(encoding="utf-8")) == state
        print(json.dumps({"mode": args.mode, "successful": True, **state}))


if __name__ == "__main__":
    main()
