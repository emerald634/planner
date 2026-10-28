"""Synthetic pytest, or --ddl for OFFLINE PostgreSQL SQL; no real config/DBs."""

import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    backend = Path(__file__).resolve().parents[1] / "backend"
    scratch = backend.parents[1] / "test-artifacts/web"
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(scratch)
    tempfile.tempdir = str(scratch)
    for name in tuple(os.environ):
        if any(
            part in name.upper()
            for part in ("TOKEN", "PASSWORD", "SECRET", "WEBHOOK", "DATABASE_URL")
        ):
            os.environ.pop(name, None)
    os.environ.update(
        WORKSPACE_RUNTIME="1",
        DATABASE_URL="sqlite://",
        JWT_SECRET=secrets.token_urlsafe(48),
        FIRST_ADMIN_PASSWORD="synthetic-bootstrap-not-used",
        COOKIE_SECURE="false",
        SESSION_ENVIRONMENT="local",
        TELEGRAM_BOT_TOKEN="",
        BITRIX24_WEBHOOK_URL="",
        PYTHONDONTWRITEBYTECODE="1",
    )
    sys.path[:0] = [str(backend), str(backend.parents[1])]
    os.chdir(backend)

    def guard(event, args):
        if event == "sqlite3.connect" and args[0] != ":memory:":
            from urllib.parse import urlsplit
            from urllib.request import url2pathname

            value = args[0]
            if str(value).startswith("file:"):
                value = url2pathname(urlsplit(value).path)
            try:
                Path(value).resolve().relative_to(scratch.resolve())
            except (ValueError, TypeError):
                raise PermissionError(
                    "Only owned synthetic SQLite is allowed"
                ) from None
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name
            if name == ".env" or name.endswith(".env"):
                raise PermissionError("Do not read environment files in tests")
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                raise PermissionError("External networking is disabled")
        if event == "socket.getaddrinfo" and args[0] not in (
            None,
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise PermissionError("External DNS is disabled")

    sys.addaudithook(guard)
    if "--ddl" in sys.argv:
        from io import StringIO

        from alembic import command
        from alembic.config import Config
        from app.core.config import settings

        settings.database_url = "postgresql+psycopg://synthetic@127.0.0.1/synthetic"
        output = StringIO()
        config = Config(str(backend / "alembic.ini"), output_buffer=output)
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head", sql=True)
        (scratch / "sessions-postgresql-ddl.sql").write_text(
            output.getvalue(), encoding="utf-8"
        )
        return 0
    import pytest

    class Results:
        def __init__(self):
            self.tests = []

        def pytest_runtest_logreport(self, report):
            if report.when == "call" or report.failed:
                self.tests.append(
                    {
                        "id": report.nodeid,
                        "phase": report.when,
                        "outcome": report.outcome,
                    }
                )

    plugin = Results()
    started = time.monotonic()
    code = pytest.main(
        ["-q", "-p", "no:cacheprovider", *sys.argv[1:]], plugins=[plugin]
    )
    report = {
        "exit_code": int(code),
        "seconds": round(time.monotonic() - started, 3),
        "tests": plugin.tests,
        "sqlite_only": True,
        "postgresql_tested": False,
    }
    (scratch / "sessions-pytest-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    label = "full" if len(sys.argv) == 1 else "targeted"
    (scratch / f"workspace-backend-{label}-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
