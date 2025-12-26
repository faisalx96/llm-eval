from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from llm_eval_platform.settings import PlatformSettings
from llm_eval_platform.web import router as web_router
from llm_eval_platform.runs_api import router as runs_router
from llm_eval_platform.ingest_api import router as ingest_router


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    settings = settings or PlatformSettings()

    app = FastAPI(title="llm-eval platform", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "llm-eval-platform", "env": settings.environment})

    # Serve the existing UI assets from the SDK package directory.
    # These are currently vanilla HTML/JS and can be reused without a Node build.
    repo_root = Path(__file__).resolve().parents[1]
    sdk_static = repo_root / "llm_eval" / "_static"

    dashboard_dir = sdk_static / "dashboard"
    ui_dir = sdk_static / "ui"

    # Dashboard (historical + approvals + profile later)
    if dashboard_dir.exists():
        app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="dashboard_static")

    # Per-run UI (live/historical run detail)
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dir)), name="run_ui_static")

    app.include_router(web_router)
    app.include_router(runs_router)
    app.include_router(ingest_router)

    return app


