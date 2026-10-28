"""Stop exactly one owned review harness through its private control + CSRF."""

import argparse
import json

import httpx
from run_working_web import owned


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    args = p.parse_args()
    root, info = owned(args.run)
    origin = f"http://127.0.0.1:{info['port']}"
    secret = json.loads((root / "control.json").read_text())["secret"]
    with httpx.Client(base_url=origin, trust_env=False, timeout=5) as c:
        token = c.get("/api/v1/auth/csrf").json()["csrf"]
        r = c.post(
            "/local-control/stop",
            headers={
                "Origin": origin,
                "X-CSRF-Token": token,
                "Authorization": "LocalStop " + secret,
            },
        )
        assert r.status_code == 200, (
            "Own control did not accept stop; no process killed"
        )
    print("Own runtime review server stopped")


if __name__ == "__main__":
    main()
