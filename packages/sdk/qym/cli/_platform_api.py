"""Read-only REST client for the qym platform API.

Uses stdlib urllib to keep SDK dependency-free.
Auth via QYM_API_KEY env var or explicit api_key parameter.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from ..platform.defaults import DEFAULT_PLATFORM_URL
from ..platform.tls import urlopen
from ..utils.env import get_platform_url_env
from ._exit_codes import ExitCode


class PlatformAPIError(Exception):
    """Error from the platform API with HTTP status code."""

    def __init__(self, status_code: int, detail: str, suggestion: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.suggestion = suggestion
        super().__init__(f"HTTP {status_code}: {detail}")

    @property
    def exit_code(self) -> int:
        if self.status_code == 404:
            return ExitCode.NOT_FOUND
        if self.status_code in (401, 403):
            return ExitCode.AUTH_DENIED
        if self.status_code == 409:
            return ExitCode.CONFLICT
        return ExitCode.FAILURE


class PlatformAPIClient:
    """Read-only REST client for querying the qym platform."""

    def __init__(
        self,
        platform_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.platform_url = (platform_url or get_platform_url_env(DEFAULT_PLATFORM_URL)).rstrip("/")
        self.api_key = api_key or os.getenv("QYM_API_KEY")

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, path: str, timeout: int = 30) -> Any:
        """HTTP GET, returns parsed JSON."""
        url = f"{self.platform_url}{path}"
        req = urlrequest.Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise PlatformAPIError(
                status_code=exc.code,
                detail=detail or str(exc),
                suggestion=self._suggestion_for(exc.code, path),
            ) from exc
        except URLError as exc:
            raise PlatformAPIError(
                status_code=0,
                detail=f"Cannot connect to {self.platform_url}: {exc.reason}",
                suggestion="Check QYM_BASE_URL and ensure the platform is running.",
            ) from exc

    def _post(self, path: str, body: dict | None = None, timeout: int = 60) -> Any:
        """HTTP POST with JSON body, returns parsed JSON."""
        url = f"{self.platform_url}{path}"
        data = json.dumps(body or {}).encode("utf-8")
        headers = {**self._headers(), "Content-Type": "application/json"}
        req = urlrequest.Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body.strip() else {}
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise PlatformAPIError(
                status_code=exc.code,
                detail=detail or str(exc),
                suggestion=self._suggestion_for(exc.code, path),
            ) from exc
        except URLError as exc:
            raise PlatformAPIError(
                status_code=0,
                detail=f"Cannot connect to {self.platform_url}: {exc.reason}",
                suggestion="Check QYM_BASE_URL and ensure the platform is running.",
            ) from exc

    @staticmethod
    def _suggestion_for(status_code: int, path: str) -> str | None:
        if status_code == 404:
            return f"Resource at {path} not found. Use 'qym run list' to see available runs."
        if status_code in (401, 403):
            return "Check QYM_API_KEY or use 'qym config check' to validate auth."
        return None

    # ── Run operations ──────────────────────────────────────────

    def list_runs(self) -> dict:
        """GET /api/runs -> tasks grouped by task name and model."""
        return self._get("/api/runs")

    def get_run(self, run_id: str) -> dict:
        """GET /api/runs/{run_id} -> full run data with snapshot."""
        return self._get(f"/api/runs/{run_id}")

    # ── Analysis operations ─────────────────────────────────────

    def analyze_run(self, run_id: str, body: dict | None = None) -> dict:
        """POST /v1/runs/{run_id}/analyze -> trigger AI analysis."""
        return self._post(f"/v1/runs/{run_id}/analyze", body=body)

    # ── Connectivity ────────────────────────────────────────────

    def check_connectivity(self) -> dict:
        """Lightweight check that the platform is reachable and auth works."""
        data = self._get("/api/runs")
        return {
            "status": "ok",
            "platform_url": self.platform_url,
            "api_key_set": bool(self.api_key),
        }
