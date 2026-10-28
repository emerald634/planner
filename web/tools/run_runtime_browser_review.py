"""TEST HARNESS only: ordinary frontend/shared server routers, owned synthetic data.

Does NOT weaken create_app/server_policy. PostgreSQL/HTTPS gates remain separate.
"""

import argparse
import asyncio
import json
import os
import secrets
import shutil
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from run_working_web import configure, owned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root, info = owned(args.run)
    os.environ["WORKSPACE_RUNTIME"] = "1"
    origin = configure(root, info)
    from types import SimpleNamespace

    import httpx
    import uvicorn
    from app.api.router import api_router
    from app.db.session import SessionLocal
    from app.models.workspace import WorkspaceLink
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from local_web.fixtures import (
        SyntheticLeads,
    )  # Test-only injection, never in server runtime.
    from planner.daily import DailyStore
    from planner.server_migration import migrate_server
    from planner.sync import sync_loop
    from sqlalchemy import text
    from workspace.application import register_workspace
    from workspace.security import install_security
    from workspace.writer import writer_app

    store = DailyStore(root / "planner.sqlite")
    migrate_server(store)
    with SessionLocal() as db:
        for row in db.execute(text("SELECT * FROM local_planner_links")).mappings():
            if db.get(WorkspaceLink, row["user_id"]) is None:
                db.add(
                    WorkspaceLink(
                        user_id=row["user_id"],
                        employee_id=row["employee_id"],
                        can_confirm=row["user_id"] == 101,
                    )
                )
        db.commit()
    for name in ("web", "bot"):
        p = root / (name + ".key")
        if not p.exists():
            p.write_text(secrets.token_urlsafe(32), encoding="ascii")
            p.chmod(0o600)
    config = SimpleNamespace(
        planner_path=store.path,
        queue_path=root / "distribution-queue.sqlite",
        web_service_secret_file=root / "web.key",
        bot_service_secret_file=root / "bot.key",
        confirmer_ids={8306778724},
        verified_contracts=set(),
    )
    writer = writer_app(config, SyntheticLeads())
    app = FastAPI()
    install_security(app, origin, secrets.token_bytes(32), secure=False)
    app.include_router(api_router, prefix="/api/v1")

    async def relay(request, identifier, index):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=writer), base_url="http://writer"
        ) as c:
            r = await c.post(
                "/web/confirm",
                json={"identifier": identifier, "variant_index": index},
                headers={
                    "Authorization": "Bearer "
                    + config.web_service_secret_file.read_text(),
                    "Cookie": request.headers.get("cookie", ""),
                },
            )
            if r.status_code != 200:
                raise HTTPException(r.status_code, "Writer rejected")
            return r.json()

    register_workspace(app, config, SyntheticLeads(), relay)

    @asynccontextmanager
    async def life(app):
        worker = asyncio.create_task(
            sync_loop(store, config.queue_path, config.confirmer_ids, interval=2)
        )
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            app.state.crm_pool.shutdown(wait=False, cancel_futures=True)

    app.router.lifespan_context = life
    frontend = root / "ordinary-frontend"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "frontend/dist",
        frontend,
        dirs_exist_ok=True,
    )
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
    control = json.loads((root / "control.json").read_text())["secret"]

    @app.post("/local-control/stop")
    def stop(request: Request):
        # Generic CSRF still required by the shared middleware; tests use Ctrl/own PID after proof.
        if request.headers.get("authorization") != "LocalStop " + control:
            raise HTTPException(403)
        server.should_exit = True
        return {"stopping": True}

    @app.get("/{path:path}")
    def index(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(frontend / "index.html")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=info["port"],
            access_log=False,
            log_level="warning",
        )
    )
    print(
        json.dumps(
            {
                "run": args.run,
                "url": origin,
                "mode": "ordinary frontend + shared runtime routers; synthetic harness only",
            }
        ),
        flush=True,
    )
    server.run()


if __name__ == "__main__":
    main()
