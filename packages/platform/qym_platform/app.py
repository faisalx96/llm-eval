from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from qym_platform.auth_oidc import origin_matches_base, session_auth_enabled
from qym_platform.api.auth import router as auth_router
from qym_platform.settings import PlatformSettings
from qym_platform.api.web import router as web_router
from qym_platform.api.projects import router as projects_router
from qym_platform.api.runs import router as runs_router
from qym_platform.api.ingest import router as ingest_router
from qym_platform.api.analysis import router as analysis_router
from qym_platform.api.product_evals import router as product_evals_router
from qym_platform.api.datasets import router as datasets_router


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    settings = settings or PlatformSettings()

    app = FastAPI(
        title="qym-platform",
        version="0.2.2",
        docs_url="/api-docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    if session_auth_enabled(settings):
        if not settings.auth_session_secret:
            raise RuntimeError("QYM_AUTH_SESSION_SECRET is required when session-based auth is enabled")
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.auth_session_secret,
            same_site="lax",
            https_only=str(settings.environment).lower() not in {"dev", "test", "local"},
            session_cookie="qym_session",
        )

        @app.middleware("http")
        async def same_origin_write_guard(request: Request, call_next):
            if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                authz = (request.headers.get("authorization") or "").strip().lower()
                if not authz.startswith("bearer "):
                    origin = request.headers.get("origin")
                    referer = request.headers.get("referer")
                    if origin:
                        if not origin_matches_base(origin, settings.base_url):
                            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
                    elif referer:
                        if not referer.startswith(settings.base_url.rstrip("/") + "/") and referer.rstrip("/") != settings.base_url.rstrip("/"):
                            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
                    else:
                        return JSONResponse({"detail": "Missing same-origin headers"}, status_code=403)
            return await call_next(request)

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

    app.include_router(auth_router)
    app.include_router(web_router)
    app.include_router(projects_router)
    app.include_router(analysis_router)  # before runs_router (its {run_id:path} is a catch-all)
    app.include_router(product_evals_router)
    app.include_router(datasets_router)
    app.include_router(runs_router)
    app.include_router(ingest_router)

    return app
