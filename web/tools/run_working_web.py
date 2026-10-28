"""Local working MVP only. Own scratch, shared LeadFlow auth, original Planner Store."""

import argparse
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO = Path(__file__).resolve().parents[1]
HOME = REPO.parent / ".workbench/browser"


def owned(run_id):
    if not re.fullmatch(r"lfweb_[a-f0-9]{32}", run_id):
        raise ValueError("Select a generated run ID, not an arbitrary path")
    root = (HOME / run_id).resolve()
    if root.parent != HOME.resolve() or root.is_symlink():
        raise ValueError("Scratch ownership check failed")
    marker = root / "owner.json"
    info = json.loads(marker.read_text(encoding="utf-8"))
    if info.get("kind") != "leadflow-planner-local-mvp" or info.get("run_id") != run_id:
        raise ValueError("Unknown scratch ownership")
    for file in root.iterdir():
        if file.is_symlink() or (file.is_file() and file.stat().st_nlink != 1):
            raise ValueError("Linked scratch files are forbidden")
    return root, info


def write_private(path, data):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
        "w",
        encoding="utf-8",
    ) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def configure(root, info):
    for key in tuple(os.environ):
        if key.startswith("PG") or any(
            part in key.upper()
            for part in ("TOKEN", "SECRET", "PASSWORD", "WEBHOOK", "DATABASE_URL")
        ):
            os.environ.pop(key, None)
    origin = f"http://127.0.0.1:{info['port']}"
    os.environ.update(
        SESSION_ENVIRONMENT="local",
        COOKIE_SECURE="false",
        PUBLIC_APP_URL=origin,
        FRONTEND_URL=origin,
        DATABASE_URL="sqlite:///" + (root / "auth.sqlite").as_posix(),
        FIRST_ADMIN_PASSWORD=secrets.token_urlsafe(32),
        JWT_SECRET=secrets.token_urlsafe(48),
        TELEGRAM_BOT_TOKEN="",
        BITRIX24_WEBHOOK_URL="",
        PYTHONDONTWRITEBYTECODE="1",
    )
    source = Path(info["planner_source"]).resolve()
    if source != REPO.parent.resolve():
        raise ValueError("External source checkout forbidden")
    if (
        hashlib.sha256((source / "planner/store.py").read_bytes()).hexdigest()
        != info["store_sha256"]
    ):
        raise ValueError(
            "Planner Store changed since prepare; review before opening existing run"
        )
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(REPO / "backend"))

    def guard(event, args):
        candidate = str(args[0]) if event == "sqlite3.connect" else ""
        if candidate.startswith("file:"):
            candidate = (
                unquote(urlparse(candidate).path).lstrip("/")
                if os.name == "nt"
                else unquote(urlparse(candidate).path)
            )
        if event == "sqlite3.connect" and Path(candidate).resolve() not in {
            root / "auth.sqlite",
            root / "planner.sqlite",
            root / "distribution-queue.sqlite",
        }:
            raise PermissionError("Only this run's synthetic SQLite files are allowed")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name.lower()
            if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
                raise PermissionError("Working environment files are forbidden")
        if event in {"socket.connect", "socket.bind"}:
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                raise PermissionError("Only loopback networking is allowed")
        if event == "socket.getaddrinfo" and args[0] not in (
            None,
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise PermissionError("External DNS is disabled")

    sys.addaudithook(guard)
    return origin


def prepare(source):
    source = source.resolve()
    if source != REPO.parent.resolve():
        raise ValueError("Use the Planner core in this same checkout")
    if not (source / "planner/store.py").is_file():
        raise ValueError("Existing Planner source checkout is required")
    HOME.mkdir(exist_ok=True)
    run_id = "lfweb_" + uuid.uuid4().hex
    root = HOME / run_id
    root.mkdir(mode=0o700)
    if os.name == "nt":
        principal = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(
            [
                "icacls",
                str(root),
                "/inheritance:r",
                "/grant:r",
                principal + ":(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    info = {
        "kind": "leadflow-planner-local-mvp",
        "run_id": run_id,
        "port": port,
        "planner_source": str(source),
        "store_sha256": hashlib.sha256(
            (source / "planner/store.py").read_bytes()
        ).hexdigest(),
    }
    write_private(root / "owner.json", info)
    accounts = [
        {
            "id": identifier,
            "email": name + "@local.example.com",
            "name": label,
            "role": role,
            "employee_id": employee,
            "password": secrets.token_urlsafe(20),
        }
        for identifier, name, label, role, employee in (
            (101, "manager", "Тестовый менеджер А", "manager", 1),
            (102, "other", "Тестовый менеджер Б", "manager", 2),
            (201, "supervisor", "Тестовый руководитель", "supervisor", 3),
            (301, "admin", "Тестовый администратор LeadFlow", "admin", None),
            (401, "unmapped", "Пользователь без привязки", "manager", None),
        )
    ]
    write_private(root / "credentials.json", accounts)
    write_private(
        root / "control.json",
        {"secret": secrets.token_urlsafe(40), "csrf": secrets.token_hex(32)},
    )
    origin = configure(root, info)
    from app.core.security import hash_password
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.models import CrmSource, Lead, User
    from sqlalchemy import text

    Base.metadata.create_all(
        engine
    )  # Explicit SYNTHETIC local mode, not a PostgreSQL migration.
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE local_lead_operations(id TEXT PRIMARY KEY,actor_id INTEGER NOT NULL,operation TEXT NOT NULL,lead_id INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE local_planner_links(user_id INTEGER PRIMARY KEY,employee_id INTEGER UNIQUE NOT NULL,role TEXT NOT NULL)"
            )
        )
    with SessionLocal() as db:
        for account in accounts:
            db.add(
                User(
                    id=account["id"],
                    email=account["email"],
                    full_name=account["name"],
                    role=account["role"],
                    hashed_password=hash_password(account["password"]),
                )
            )
        db.flush()
        db.add(CrmSource(external_id="local", name="Искусственный источник"))
        db.add_all(
            [
                Lead(
                    phone="+0 000 000 0001",
                    name="Тестовое обращение А",
                    manager_id=101,
                    source="local",
                ),
                Lead(
                    phone="+0 000 000 0002",
                    name="Тестовое обращение Б",
                    manager_id=102,
                    source="local",
                ),
            ]
        )
        for account in accounts:
            if account["employee_id"] is not None:
                db.execute(
                    text(
                        "INSERT INTO local_planner_links VALUES(:id,:employee_id,:role)"
                    ),
                    account,
                )
        db.commit()
    from unittest.mock import patch

    import planner.store as module
    from planner.daily import DailyStore, initialize_daily
    from planner.store import today

    bindings = (
        # Protocol fixture IDs from existing schema1 allowlist; these are NOT
        # real web accounts. All external networking and Telegram are disabled.
        (8306778724, 460, "Тестовый менеджер А", "manager"),
        (7939114214, 110, "Тестовый менеджер Б", "manager"),
        (1073597301, None, "Тестовый руководитель", "supervisor"),
    )
    store = DailyStore(root / "planner.sqlite")
    # Only local seed configuration; migration and business operations remain original.
    with patch.object(module, "EMPLOYEE_BINDINGS", bindings):
        store.initialize()
    initialize_daily(store)
    from planner.distribution_queue import DistributionQueue
    from planner.web_distribution import initialize_previews

    initialize_previews(store)
    DistributionQueue(root / "distribution-queue.sqlite").initialize()
    with store.connection() as connection:
        actor = dict(
            connection.execute("SELECT * FROM employees WHERE id=3").fetchone()
        )
    for employee in (1, 2):
        store.create_plan(actor, today(), employee_id=employee)
    print(
        json.dumps({"run_id": run_id, "url": origin + "/login", "scratch": str(root)})
    )
    return root, info


def build(root):
    node = shutil.which("node")
    if not node:
        raise ValueError("Existing Node runtime required; nothing will be installed")
    subprocess.run(
        [
            node,
            "node_modules/vite/bin/vite.js",
            "build",
            "--config",
            "vite.mvp.config.ts",
        ],
        cwd=REPO / "frontend",
        check=True,
    )
    shutil.copytree(REPO / "frontend/dist-mvp", root / "frontend", dirs_exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "start", "stop", "credentials"))
    parser.add_argument("--run")
    parser.add_argument("--planner-source", type=Path, default=REPO.parent)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.run:
        root, info = owned(args.run)
    else:
        if args.command not in {"prepare", "start"}:
            parser.error("Specify --run with the generated run ID")
        root, info = prepare(args.planner_source)
    if args.command == "credentials":
        print((root / "credentials.json").read_text(encoding="utf-8"))
        return
    if args.command == "stop":
        control = json.loads((root / "control.json").read_text())
        client = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=5)
        client.request(
            "POST",
            "/local-control/stop",
            headers={
                "Origin": f"http://127.0.0.1:{info['port']}",
                "Authorization": "LocalStop " + control["secret"],
            },
        )
        response = client.getresponse()
        if response.status != 200:
            raise ValueError(
                "Owned local process did not accept stop; no process was killed"
            )
        print("Остановка локального MVP запрошена.")
        return
    if args.command == "prepare":
        return
    if not args.no_build:
        build(root)
    if not (root / "frontend/index.html").is_file():
        raise ValueError("Build the local frontend before using --no-build")
    origin = configure(root, info) if args.run else f"http://127.0.0.1:{info['port']}"
    control = json.loads((root / "control.json").read_text())
    import uvicorn
    from local_web.application import create_local_app

    app = create_local_app(
        root, origin, bytes.fromhex(control["csrf"]), control["secret"]
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=info["port"],
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
    )
    app.state.on_stop = lambda: setattr(server, "should_exit", True)
    print(
        json.dumps(
            {"run_id": info["run_id"], "url": origin + "/login", "pid": os.getpid()}
        ),
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
