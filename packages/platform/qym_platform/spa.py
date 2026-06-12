"""Serve the built single-page app (SPA) from the platform package.

The React build lands in ``qym_platform/_static/app`` (``index.html`` plus
hashed files under ``assets/``; gitignored build output produced by
``npm run build`` in ``packages/platform/frontend``).

Responsibilities:

- Mount ``/app-assets`` at the build root; hashed files under ``assets/``
  get an immutable cache-control header (filenames are content-hashed, so a
  year is safe). The mount must sit at the build root because vite's
  ``renderBuiltUrl`` runtime expression in the frontend emits chunk URLs as
  ``__QYM_ROOT_PATH__ + '/app-assets/assets/<file>'``.
- ``spa_shell_response``: serve ``index.html`` with ``window.__QYM_ROOT_PATH__``
  and ``window.__QYM_BOOT__`` injected, and relative ``./assets/`` references
  rewritten to ``{root_path}/app-assets/`` (mirrors the legacy root-path
  injection in ``api/runs.py::_dashboard_html_response``).
- A catch-all GET route registered after every other route so SPA-only
  client-side paths (e.g. ``/projects/x/analysis``) render the shell on
  refresh, while backend namespaces still 404 normally.

Mixed mode (until Phase 5): the SPA owns ``/``, ``/projects/{slug}``,
``/projects/{slug}/runs/{run_id}``, ``/profile`` and ``/admin`` — those legacy
handlers in ``api/runs.py`` delegate to :func:`spa_shell_response`. The other
legacy pages (compare/charts/models/overview/reviews/datasets/settings/trash)
keep serving the old ``/static`` HTML; they link back to ``/`` and
``/projects/{slug}``, which now serve the SPA. That cross-linking is expected
and acceptable during the migration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from qym_platform.auth_oidc import request_root_path
from qym_platform.settings import PlatformSettings

SPA_DIR = Path(__file__).resolve().parent / "_static" / "app"
SPA_INDEX = SPA_DIR / "index.html"
SPA_ASSETS_DIR = SPA_DIR / "assets"

MISSING_BUILD_MESSAGE = (
    "SPA assets not built — run npm run build in packages/platform/frontend"
)

# Backend-owned namespaces the SPA catch-all must never swallow: an unknown
# path under these prefixes is a real 404, not a client-side route.
_PASSTHROUGH_PREFIXES = (
    "api/",
    "v1/",
    "static/",
    "ui/",
    "docs/",
    "app-assets/",
    "auth/",
    "healthz",
    "openapi.json",
    "login",
)
_PASSTHROUGH_BARE = {"api", "v1", "static", "ui", "docs", "app-assets", "auth"}

# Settings captured at app composition time (register_spa); fall back to a
# fresh PlatformSettings so spa_shell_response also works when called from
# legacy handlers before/without registration (e.g. in unit tests).
_settings: Optional[PlatformSettings] = None

# (mtime, html) cache of the built index.html; re-read when the build changes.
_shell_cache: Optional[Tuple[float, str]] = None


class ImmutableStaticFiles(StaticFiles):
    """StaticFiles that marks hashed build assets as immutable for a year.

    Only files under ``assets/`` carry a content hash in their filename (vite
    ``[name]-[hash]`` output), so only those get the immutable header; the few
    unhashed files in the mount (index.html, export/export.html) keep default
    caching.
    """

    def file_response(
        self,
        full_path: "os.PathLike[str]",
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # get_path strips the mount prefix and normalises to os.sep.
        subpath = self.get_path(scope).replace(os.sep, "/")
        if subpath.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _read_shell_template() -> Optional[str]:
    """Return the built index.html, cached and invalidated by mtime."""
    global _shell_cache
    try:
        mtime = SPA_INDEX.stat().st_mtime
    except OSError:
        _shell_cache = None
        return None
    if _shell_cache is None or _shell_cache[0] != mtime:
        _shell_cache = (mtime, SPA_INDEX.read_text(encoding="utf-8"))
    return _shell_cache[1]


def _boot_payload(settings: PlatformSettings) -> dict:
    return {"auth_mode": str(settings.auth_mode).strip().lower()}


def spa_shell_response(request: Request) -> Response:
    """Serve the SPA shell with root-path + boot data injected.

    The build emits relative ``./assets/...`` URLs in index.html (vite
    ``base: ''`` + ``renderBuiltUrl`` returning ``{ relative: true }`` for
    HTML hosts); rewrite them to the ``{root_path}/app-assets/`` mount so the
    shell works for nested client-side routes like ``/projects/x/analysis``
    where a relative URL would resolve against the wrong directory.
    """
    template = _read_shell_template()
    if template is None:
        return PlainTextResponse(MISSING_BUILD_MESSAGE, status_code=503)

    root = request_root_path(request)
    settings = _settings or PlatformSettings()
    # '/app-assets' is mounted at the build ROOT (_static/app), not at the
    # assets/ subdir: vite's renderBuiltUrl runtime expression builds chunk
    # URLs as __QYM_ROOT_PATH__ + '/app-assets/assets/<file>' (vite filenames
    # keep their 'assets/' prefix), so index.html's './assets/x' must map to
    # '{root}/app-assets/assets/x' to hit the same tree.
    html = template.replace('"./assets/', f'"{root}/app-assets/assets/')

    injection = (
        "<script>"
        f"window.__QYM_ROOT_PATH__={json.dumps(root)};"
        f"window.__QYM_BOOT__={json.dumps(_boot_payload(settings))};"
        "</script>"
    )
    # Inject before the first <script> (the module entry) so both globals are
    # defined before any app code runs. index.html also has a trailing
    # `window.__QYM_ROOT_PATH__ = window.__QYM_ROOT_PATH__ || ''` fallback,
    # which keeps the injected value.
    first_script = html.find("<script")
    if first_script >= 0:
        html = html[:first_script] + injection + "\n    " + html[first_script:]
    elif "</head>" in html:
        html = html.replace("</head>", injection + "</head>", 1)
    else:
        html = injection + html
    return HTMLResponse(html, media_type="text/html; charset=utf-8")


def register_spa(app: FastAPI, settings: PlatformSettings) -> None:
    """Mount SPA assets and the catch-all shell route.

    Must be called from ``create_app`` AFTER every router/mount: Starlette
    matches routes in registration order, so the ``/{full_path:path}``
    catch-all only sees requests nothing else claimed.

    The SPA takeover of the legacy page routes ('/', '/projects/{slug}', ...)
    intentionally does NOT happen here: those paths are registered first by
    the legacy router in ``api/runs.py``, so a same-path route added after it
    would never match. Instead the specific legacy handlers delegate to
    :func:`spa_shell_response` — the least invasive option given app.py's
    router composition (no app.routes surgery, login redirects preserved).
    """
    global _settings
    _settings = settings

    if SPA_DIR.is_dir():
        app.mount(
            "/app-assets",
            ImmutableStaticFiles(directory=str(SPA_DIR)),
            name="spa_assets",
        )

    @app.get("/{full_path:path}", response_model=None, include_in_schema=False)
    def spa_catch_all(full_path: str, request: Request) -> Response:
        path = full_path.lstrip("/")
        if path.startswith(_PASSTHROUGH_PREFIXES) or path.rstrip("/") in _PASSTHROUGH_BARE:
            raise HTTPException(status_code=404, detail="Not found")
        # File-like paths (a dot in the final segment, e.g. /secret.env or
        # /favicon.ico) are never client-side routes — 404 instead of shell.
        # Matches connect-history-api-fallback's default behaviour and keeps
        # traversal probes from receiving a 200.
        final_segment = path.rstrip("/").rsplit("/", 1)[-1]
        if "." in final_segment:
            raise HTTPException(status_code=404, detail="Not found")
        return spa_shell_response(request)
