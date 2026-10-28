"""Local adapter must remain absent from standard app and reject wrong ownership."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.main import app
from local_web import application


def test_standard_app_has_no_local_planner_or_control_routes():
    assert not any(
        "/planner" in getattr(route, "path", "")
        or "local-control" in getattr(route, "path", "")
        or "/local/csrf" in getattr(route, "path", "")
        for route in app.routes
    )
    assert not getattr(app.state, "local_planner", False)


def test_factory_rejects_unowned_directory_before_importing_planner(tmp_path):
    with pytest.raises(ValueError, match="Owned synthetic"):
        application.create_local_app(tmp_path, "http://127.0.0.1:7777", b"a" * 32, "b" * 40)


@pytest.mark.parametrize("mode", ["production", "wrong_database", "missing_secret"])
def test_factory_rejects_nonlocal_auth_context(tmp_path, monkeypatch, mode):
    fake_file = tmp_path / "repo/web/backend/local_web/application.py"
    monkeypatch.setattr(application, "__file__", str(fake_file))
    root = tmp_path / "repo/.workbench/browser" / ("lfweb_" + "a" * 32)
    root.mkdir(parents=True)
    (root / "owner.json").write_text(
        json.dumps({"kind": "leadflow-planner-local-mvp", "run_id": root.name, "port": 7777})
    )
    monkeypatch.setattr(settings, "public_app_url", "http://127.0.0.1:7777")
    monkeypatch.setattr(settings, "frontend_url", "http://127.0.0.1:7777")
    monkeypatch.setattr(
        settings, "session_environment", "production" if mode == "production" else "local"
    )
    monkeypatch.setattr(
        settings,
        "database_url",
        "sqlite:///"
        + (root / ("foreign.sqlite" if mode == "wrong_database" else "auth.sqlite")).as_posix(),
    )
    with pytest.raises(ValueError, match="production auth"):
        application.create_local_app(
            root, "http://127.0.0.1:7777", b"" if mode == "missing_secret" else b"a" * 32, "b" * 40
        )


@pytest.mark.parametrize(
    "value", ["../planner.db", "lfweb_" + "../" * 10 + "aa", "", "lfweb_" + "g" * 32]
)
def test_launcher_refuses_arbitrary_scratch_path(value):
    source = Path(__file__).resolve().parents[2] / "tools/run_working_web.py"
    spec = importlib.util.spec_from_file_location("synthetic_local_launcher", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.owned(value)
