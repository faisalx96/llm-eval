"""Tests for `qym analyze run` and the platform analyze helper (HP-2).

The CLI must POST to /api/runs/{run_id}/analyze (the route the platform
actually mounts in qym_platform/api/analysis.py) and parse the real response
shape: {"total_analyzed": int, "errors": int, "results": [...]}.

HTTP is mocked at the urlopen seam, so no platform is needed.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import qym.cli._platform_api as platform_api
from qym.cli._platform_api import PlatformAPIClient

ANALYZE_RESPONSE = {
    "total_analyzed": 3,
    "errors": 1,
    "results": [
        {"item_id": "a", "root_cause": "wrong_format", "confidence": 0.9, "error": None},
        {"item_id": "b", "root_cause": "wrong_format", "confidence": 0.8, "error": None},
        {"item_id": "c", "root_cause": None, "confidence": None, "error": "LLM call failed"},
    ],
}


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def fake_urlopen(monkeypatch):
    """Capture urllib requests made by PlatformAPIClient and serve a canned response."""
    calls: list = []

    def _urlopen(req, timeout=None, **kwargs):
        calls.append(req)
        return _FakeResponse(ANALYZE_RESPONSE)

    monkeypatch.setattr(platform_api, "urlopen", _urlopen)
    return calls


def _all_output(result) -> str:
    out = result.output
    try:
        out += result.stderr
    except (ValueError, AttributeError):
        pass  # older click mixes stderr into output already
    return out


def test_analyze_run_posts_to_api_runs_analyze(fake_urlopen):
    client = PlatformAPIClient(platform_url="http://platform.test", api_key="qym-key")
    result = client.analyze_run("run-123", body={"concurrency": 5})

    assert result == ANALYZE_RESPONSE
    (req,) = fake_urlopen
    assert req.full_url == "http://platform.test/api/runs/run-123/analyze"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer qym-key"
    assert json.loads(req.data.decode("utf-8")) == {"concurrency": 5}


def test_cli_analyze_run_json_mode_returns_real_response_keys(fake_urlopen, monkeypatch):
    monkeypatch.setenv("QYM_API_KEY", "qym-key")
    from qym.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["--json", "analyze", "run", "run-123"])

    assert result.exit_code == 0, _all_output(result)
    payload = json.loads(result.stdout)
    assert payload["total_analyzed"] == 3
    assert payload["errors"] == 1
    assert len(payload["results"]) == 3

    (req,) = fake_urlopen
    assert req.full_url.endswith("/api/runs/run-123/analyze")
    # The CLI clamps concurrency to the platform's AnalyzeRequest cap (<= 20).
    body = json.loads(req.data.decode("utf-8"))
    assert 1 <= body["concurrency"] <= 20


def test_cli_analyze_run_human_mode_summarizes_results(fake_urlopen, monkeypatch):
    monkeypatch.setenv("QYM_API_KEY", "qym-key")
    from qym.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["analyze", "run", "run-123", "--concurrency", "50"])

    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "3 items analyzed" in out
    assert "wrong_format" in out  # category table derived from per-item results

    (req,) = fake_urlopen
    body = json.loads(req.data.decode("utf-8"))
    assert body["concurrency"] == 20  # clamped from 50
