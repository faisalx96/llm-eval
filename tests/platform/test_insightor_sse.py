import importlib.util
import ast
import json
import sys
import types
from pathlib import Path

import pytest
import requests


@pytest.fixture
def insightor_eval(monkeypatch):
    pandas = types.ModuleType("pandas")
    pandas.Timestamp = type("Timestamp", (), {})
    pandas.DataFrame = type("DataFrame", (), {})
    monkeypatch.setitem(sys.modules, "pandas", pandas)

    dataikuapi = types.ModuleType("dataikuapi")
    dataikuapi.DSSClient = object
    monkeypatch.setitem(sys.modules, "dataikuapi", dataikuapi)

    qym = types.ModuleType("qym")
    qym.Evaluator = object
    monkeypatch.setitem(sys.modules, "qym", qym)

    module_path = Path(__file__).resolve().parents[2] / "insightor_eval.py"
    module_name = "test_insightor_eval_sse"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_log_timing", lambda entry: None)
    return module


class _TokenResponse:
    status_code = 200

    def json(self):
        return {"access_token": "test-token"}


class _AuthErrorResponse:
    status_code = 401
    text = '{"detail":"refresh token expired"}'

    def json(self):
        return {"detail": "refresh token expired"}


class _StreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield from self._lines


class _Session:
    def __init__(self, response):
        self.headers = {}
        self._response = response

    def request(self, method, url, **kwargs):
        return self._response


def _data(payload, *, space=True):
    separator = " " if space else ""
    return f"data:{separator}{json.dumps(payload)}".encode()


def _run_stream(module, monkeypatch, lines, *, unwrap=True):
    stream_response = _StreamResponse(lines)
    monkeypatch.setattr(
        module.requests, "post", lambda *args, **kwargs: _TokenResponse()
    )
    monkeypatch.setattr(module.requests, "Session", lambda: _Session(stream_response))
    module.configure_runtime(
        INSIGHTOR_URL="https://insightor.test",
        REFRESH_TOKEN="refresh-token",
    )
    result = module.insightor_api("question")
    return module._unwrap_insightor_output(result) if unwrap else result


def test_missing_context_is_a_warning_and_later_events_continue(
    insightor_eval, monkeypatch
):
    task_event = {
        "rich": {
            "type": "task_tracker_update",
            "data": {
                "task": {
                    "id": "rag_context_inject",
                    "status": "completed",
                    "metadata": {"langfuse_url": "https://langfuse.test/trace"},
                }
            },
        }
    }
    sql_event = {
        "rich": {
            "type": "status_card",
            "data": {"metadata": {"sql": "SELECT 1", "result": []}},
        }
    }

    result = _run_stream(
        insightor_eval,
        monkeypatch,
        [_data(task_event), _data(sql_event, space=False), b"data: [DONE]"],
    )

    assert result["sql"] == "SELECT 1"
    assert result["context"] == ""
    assert result["langfuse_url"] == "https://langfuse.test/trace"
    assert result["sse_warnings"] == [
        "Completed rag_context_inject task did not include context"
    ]


def test_schema_drift_does_not_erase_previously_extracted_sql(
    insightor_eval, monkeypatch
):
    valid_sql = {
        "rich": {
            "type": "tool_call",
            "data": {"name": "run_sql", "args": {"sql": "SELECT 42"}},
        }
    }
    invalid_sql = {
        "rich": {
            "type": "status_card",
            "data": {"metadata": {"sql": {"unexpected": "shape"}}},
        }
    }
    wrong_task_shape = {
        "rich": {"type": "task_tracker_update", "data": {"task": ["changed"]}}
    }
    wrong_text_shape = {
        "rich": {"type": "text", "data": {"content": {"delta": "answer"}}}
    }

    result = _run_stream(
        insightor_eval,
        monkeypatch,
        [
            b"\xff",
            b"data: not-json",
            b"data: []",
            _data({"rich": "changed"}),
            _data(wrong_task_shape),
            _data(valid_sql),
            _data(invalid_sql),
            _data(wrong_text_shape),
        ],
    )

    assert result["sql"] == "SELECT 42"
    assert len(result["sse_warnings"]) == 7
    assert any("task" in warning for warning in result["sse_warnings"])
    assert any(
        "status_card.metadata.sql" in warning for warning in result["sse_warnings"]
    )


def test_structured_context_is_preserved_as_json(insightor_eval, monkeypatch):
    task_event = {
        "rich": {
            "type": "task_tracker_update",
            "data": {
                "task": {
                    "id": "rag_context_inject",
                    "status": "completed",
                    "metadata": {"context": {"tables": ["users"]}},
                }
            },
        }
    }
    sql_event = {
        "rich": {
            "type": "tool_result",
            "data": {"result": {"sql": "SELECT * FROM users"}},
        }
    }

    result = _run_stream(
        insightor_eval, monkeypatch, [_data(task_event), _data(sql_event)]
    )

    assert json.loads(result["context"]) == {"tables": ["users"]}
    assert result["sql"] == "SELECT * FROM users"
    assert "sse_warnings" not in result


def test_task_returns_current_qym_envelope(insightor_eval, monkeypatch):
    task_event = {
        "rich": {
            "type": "task_tracker_update",
            "data": {
                "task": {
                    "id": "rag_context_inject",
                    "status": "completed",
                    "metadata": {
                        "context": "# Tables Context\n### users:",
                        "langfuse_url": "https://trace.example.test/1",
                    },
                }
            },
        }
    }
    sql_event = {
        "rich": {
            "type": "tool_result",
            "data": {"result": {"sql": "SELECT * FROM users"}},
        }
    }

    result = _run_stream(
        insightor_eval,
        monkeypatch,
        [_data(task_event), _data(sql_event)],
        unwrap=False,
    )

    assert set(result) == {"output", "metadata"}
    assert result["output"]["sql"] == "SELECT * FROM users"
    assert result["metadata"] == {
        "context": "# Tables Context\n### users:",
        "external_trace_url": "https://trace.example.test/1",
    }


def test_accuracy_unwraps_current_qym_envelope(insightor_eval, monkeypatch):
    executed_queries = []

    def fake_get_results(query):
        executed_queries.append(query)
        return {"columns": ["value"], "rows": [(1,)]}

    monkeypatch.setattr(insightor_eval, "get_results", fake_get_results)
    monkeypatch.setattr(
        insightor_eval,
        "exact_match",
        lambda output, expected: {
            "score": True,
            "metadata": {"cell_f1": 1.0, "error": ""},
        },
    )
    monkeypatch.setattr(
        insightor_eval,
        "llm_judge_metric",
        lambda output, expected, input_data: {
            "score": False,
            "metadata": {"reasoning": "not needed"},
        },
    )

    result = insightor_eval.accuracy(
        {
            "output": {"sql": "SELECT 1", "context": ""},
            "metadata": {},
        },
        "SELECT 1",
        "question",
    )

    assert result["score"] is True
    assert executed_queries == ["SELECT 1", "SELECT 1"]


def test_transport_errors_are_not_hidden(insightor_eval, monkeypatch):
    class BrokenStreamResponse(_StreamResponse):
        def iter_lines(self):
            raise requests.ConnectionError("stream disconnected")
            yield  # pragma: no cover

    response = BrokenStreamResponse([])
    monkeypatch.setattr(
        insightor_eval.requests, "post", lambda *args, **kwargs: _TokenResponse()
    )
    monkeypatch.setattr(insightor_eval.requests, "Session", lambda: _Session(response))
    insightor_eval.configure_runtime(
        INSIGHTOR_URL="https://insightor.test",
        REFRESH_TOKEN="refresh-token",
    )

    with pytest.raises(requests.ConnectionError, match="stream disconnected"):
        insightor_eval.insightor_api("question")


def test_missing_sql_is_reported_without_raising(insightor_eval, monkeypatch):
    result = _run_stream(
        insightor_eval,
        monkeypatch,
        [_data({"rich": {"type": "heartbeat", "data": {}}})],
    )

    assert result["sql"] == ""
    assert result["sse_warnings"] == ["SSE stream ended without a SQL result"]


def test_auth_failure_includes_server_status_and_detail(insightor_eval, monkeypatch):
    monkeypatch.setattr(
        insightor_eval.requests,
        "post",
        lambda *args, **kwargs: _AuthErrorResponse(),
    )
    monkeypatch.setattr(
        insightor_eval.requests,
        "Session",
        lambda: _Session(_StreamResponse([])),
    )
    insightor_eval.configure_runtime(
        INSIGHTOR_URL="https://insightor.test",
        REFRESH_TOKEN="expired-token",
    )

    with pytest.raises(
        ValueError,
        match="Failed to obtain access token: HTTP 401: refresh token expired",
    ):
        insightor_eval.insightor_api("question")


def test_auth_success_without_access_token_reports_response_problem(
    insightor_eval, monkeypatch
):
    class MissingTokenResponse:
        status_code = 200

        def json(self):
            return {"message": "ok"}

    monkeypatch.setattr(
        insightor_eval.requests,
        "post",
        lambda *args, **kwargs: MissingTokenResponse(),
    )
    monkeypatch.setattr(
        insightor_eval.requests,
        "Session",
        lambda: _Session(_StreamResponse([])),
    )
    insightor_eval.configure_runtime(
        INSIGHTOR_URL="https://insightor.test",
        REFRESH_TOKEN="refresh-token",
    )

    with pytest.raises(
        ValueError,
        match="Failed to obtain access token: HTTP 200 response did not include access_token",
    ):
        insightor_eval.insightor_api("question")


def test_standalone_insightor_eval_disables_auto_save():
    module_path = Path(__file__).resolve().parents[2] / "insightor_eval.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    run_parallel_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_parallel"
    ]
    assert len(run_parallel_calls) == 1
    auto_save = next(
        keyword.value
        for keyword in run_parallel_calls[0].keywords
        if keyword.arg == "auto_save"
    )
    assert isinstance(auto_save, ast.Constant)
    assert auto_save.value is False

    retry_values = [
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == "max_retries"
    ]
    assert any(
        isinstance(value, ast.Constant) and value.value == 1 for value in retry_values
    )

    checkpoint_values = [
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == "checkpoint_enabled"
    ]
    assert any(
        isinstance(value, ast.Constant) and value.value is False
        for value in checkpoint_values
    )

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "langfuse" not in imported_modules
