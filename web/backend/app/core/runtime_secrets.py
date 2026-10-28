"""Explicit file-only production DSN. Never logs path contents or environment."""

import os
import stat
from pathlib import Path


def private_text(path):
    try:
        path = Path(path)
        info = path.lstat()
        if (
            not path.is_absolute()
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= 8192
        ):
            raise ValueError()
        if os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()):
            raise ValueError()
        # O_NOFOLLOW + fstat also guard replacement of the leaf after lstat.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            current = os.fstat(stream.fileno())
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError()
            value = stream.read(8193).decode("utf-8").strip()
        if not value or len(value) > 8192 or "\n" in value or "\r" in value:
            raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError, TypeError):
        raise ValueError("Runtime secret file is missing or unsafe") from None


def settings_arguments():
    if os.environ.get("WORKSPACE_RUNTIME") != "1":
        return {}
    if os.environ.get("SESSION_ENVIRONMENT", "production") == "local":
        return {}  # Only isolated test factories; server_policy refuses local mode.
    if any(os.environ.get(x) for x in ("DATABASE_URL", "FIRST_ADMIN_PASSWORD", "JWT_SECRET")):
        raise ValueError("Workspace production requires file credentials, not inline secrets")
    value = private_text(os.environ.get("DATABASE_URL_FILE", ""))
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Canonical PostgreSQL DSN required")
    return {"database_url": value}
