from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from qym_platform.settings import PlatformSettings
from qym_platform.api.web import router as web_router
from qym_platform.api.runs import router as runs_router
from qym_platform.api.ingest import router as ingest_router
from qym_platform.api.org import router as org_router
from qym_platform.api.analysis import router as analysis_router


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    settings = settings or PlatformSettings()

    app = FastAPI(title="qym-platform", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "qym-platform", "env": settings.environment})

    # Serve UI assets from the platform package (no longer from SDK)
    platform_static = Path(__file__).resolve().parent / "_static"

    dashboard_dir = platform_static / "dashboard"
    ui_dir = platform_static / "ui"

    # Dashboard (historical + approvals + profile + admin)
    if dashboard_dir.exists():
        app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="dashboard_static")

    # Per-run UI (live/historical run detail)
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dir)), name="run_ui_static")

    app.include_router(web_router)
    app.include_router(analysis_router)  # before runs_router (its {run_id:path} is a catch-all)
    app.include_router(runs_router)
    app.include_router(ingest_router)
    app.include_router(org_router)

    return app


