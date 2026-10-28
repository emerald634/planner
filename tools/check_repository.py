"""Check a single tracked checkout, without importing apps/config/real data."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check():
    required = [
        "bot.py",
        "planner/store.py",
        "planner/distribution_queue.py",
        "web/backend/app/models/workspace.py",
        "web/backend/workspace/writer.py",
        "web/frontend/src/App.tsx",
        "web/frontend/pnpm-lock.yaml",
        "miniapp/src/App.tsx",
        "miniapp/pnpm-lock.yaml",
    ]
    for name in required:
        assert (ROOT / name).is_file(), name
    for folder in (ROOT / "web/backend", ROOT / "web/tools", ROOT / "tools"):
        for path in folder.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8-sig")
            ast.parse(source, filename=str(path))
            assert not any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "home"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "Path"
                for n in ast.walk(ast.parse(source))
            ), str(path)
            assert not re.search(
                r"[A-Z]:[\\/].*(?:bitrix_missed_calls_bot|lead-flow-auth-poc)", source
            ), str(path)
    assert not (ROOT / "web/planner").exists(), "Duplicated Planner core"
    assert not (ROOT / "web/distribution.py").exists(), "Duplicated algorithm"
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"ssh-action|workflow_run|DEPLOY_HOST|docker compose up|crm\.lead\.add",
            text,
        )
    return {
        "self_contained_paths": True,
        "single_planner_core": True,
        "no_auto_deployment_workflow": True,
        "linux_or_postgres_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(check()))
