"""Explicit server config, no dotenv and no synthetic defaults."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RuntimeConfig:
    origin: str
    planner_path: Path
    queue_path: Path
    frontend_path: Path
    writer_socket: Path
    csrf_secret_file: Path
    web_service_secret_file: Path
    bot_service_secret_file: Path
    confirmer_ids: frozenset[int]
    crm_secret_file: Path | None = None
    verified_contracts: frozenset[str] = frozenset()

    def validate(self):
        url = urlsplit(self.origin)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
        ):
            raise ValueError("Exact HTTPS origin required")
        for p in (
            self.planner_path,
            self.queue_path,
            self.frontend_path,
            self.writer_socket,
            self.csrf_secret_file,
            self.web_service_secret_file,
            self.bot_service_secret_file,
        ):
            if not p.is_absolute() or p.is_symlink():
                raise ValueError("Explicit absolute regular paths required")
        if self.planner_path.resolve() == self.queue_path.resolve():
            raise ValueError("Separate planner and queue required")
        if any(type(x) is not int or x <= 0 for x in self.confirmer_ids):
            raise ValueError("Explicit confirmer IDs required")
        if not self.verified_contracts <= {"calls", "leads", "deals"}:
            raise ValueError("Unsupported auto-fill contracts")
        return self


def load_config():
    if os.environ.get("WORKSPACE_RUNTIME") != "1":
        raise ValueError("Explicit WORKSPACE_RUNTIME=1 required; dotenv forbidden")
    path = Path(os.environ["WORKSPACE_CONFIG_FILE"])
    if not path.is_absolute():
        raise ValueError("Absolute config file required")
    raw = json.loads(path.read_text(encoding="utf-8"))
    for field in (
        "planner_path",
        "queue_path",
        "frontend_path",
        "writer_socket",
        "csrf_secret_file",
        "web_service_secret_file",
        "bot_service_secret_file",
        "crm_secret_file",
    ):
        if raw.get(field) is not None:
            raw[field] = Path(raw[field])
    raw["confirmer_ids"] = frozenset(raw["confirmer_ids"])
    raw["verified_contracts"] = frozenset(raw.get("verified_contracts", []))
    return RuntimeConfig(**raw).validate()


def crm_url(path):
    # Webhook contains URL punctuation; never use generic service-key parser.
    if path is None:
        return None
    import stat

    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 2048
    ):
        raise ValueError("Invalid CRM secret file")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("CRM secret must be private")
    value = path.read_text(encoding="ascii").strip()
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Invalid CRM secret configuration")
    return value
