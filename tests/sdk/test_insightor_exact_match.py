"""EI-5: insightor_eval exact_match must compute recall over gold rows.

Regression tests for the direction inversion where exact_match passed
``(output, expected)`` into ``ExecutionAccuracy.evaluate(reference_rows,
generated_rows)``, scoring precision over LLM rows — an answer returning
1 of 10 required gold rows scored 100%.

Also covers the infrastructure-failure error marker (score=None +
metadata.error instead of a fake "wrong answer" 0) and the
QYM_INSIGHTOR_SSL_VERIFY opt-in.
"""

import json

import pytest

insightor_eval = pytest.importorskip(
    "insightor_eval", reason="insightor_eval heavy deps not installed"
)


GOLD_ROWS = [(i * 100,) for i in range(1, 11)]  # 10 distinct gold rows


# ── Direction: recall over gold rows ──────────────────────────────────


def test_partial_answer_scores_recall_not_precision():
    """1 of 10 required gold rows must score 10%, not 100%."""
    output = [GOLD_ROWS[0]]  # LLM returned a single (correct) row

    result = insightor_eval.exact_match(output, GOLD_ROWS)

    assert result["metadata"]["cell_f1"] == 10
    assert result["score"] is False
    assert result["metadata"]["error"] is None


def test_full_match_scores_100():
    result = insightor_eval.exact_match(list(GOLD_ROWS), GOLD_ROWS)

    assert result["metadata"]["cell_f1"] == 100
    assert result["score"] is True


def test_extra_llm_rows_do_not_hurt_recall():
    """Extra rows in the LLM answer are allowed as long as every gold row is found."""
    output = list(GOLD_ROWS) + [(99999,), (88888,)]

    result = insightor_eval.exact_match(output, GOLD_ROWS)

    assert result["metadata"]["cell_f1"] == 100
    assert result["score"] is True


def test_empty_llm_output_scores_zero():
    result = insightor_eval.exact_match([], GOLD_ROWS)

    assert result["metadata"]["cell_f1"] == 0
    assert result["score"] is False
    assert result["metadata"]["error"] is None


def test_numeric_tolerance_within_two_percent():
    result = insightor_eval.exact_match([(101,)], [(100,)])

    assert result["metadata"]["cell_f1"] == 100
    assert result["score"] is True


# ── Infrastructure failures: error marker, not "wrong answer" ─────────


def test_infrastructure_error_returns_none_score_with_error_marker():
    # Non-iterable output triggers a scoring failure (e.g. upstream None).
    result = insightor_eval.exact_match(None, GOLD_ROWS)

    assert result["score"] is None  # excludable, NOT False/0
    assert result["metadata"]["cell_f1"] is None
    error = json.loads(result["metadata"]["error"])
    assert error["exc_type"]
    assert error["exc_traceback"]


def test_empty_gold_rows_is_an_error_not_a_wrong_answer():
    """An empty gold result (e.g. the gold query failed) is not scoreable."""
    result = insightor_eval.exact_match([(1,)], [])

    assert result["score"] is None
    assert result["metadata"]["error"] is not None


def test_accuracy_combines_none_scores_as_no_signal(monkeypatch):
    monkeypatch.setattr(insightor_eval, "_log_timing", lambda entry: None)
    monkeypatch.setattr(
        insightor_eval, "get_results", lambda q: {"columns": ["c"], "rows": [(1,)]}
    )
    monkeypatch.setattr(
        insightor_eval,
        "exact_match",
        lambda o, e: {"score": None, "metadata": {"cell_f1": None, "error": "boom"}},
    )

    # Judge has a real opinion -> its score wins despite exact_match erroring.
    monkeypatch.setattr(
        insightor_eval,
        "llm_judge_metric",
        lambda o, e, i: {"score": 1, "metadata": {"reasoning": "ok"}},
    )
    result = insightor_eval.accuracy({"sql": "SELECT 1", "request_id": "r1"}, "SELECT 1")
    assert result["score"] is True

    # Neither sub-metric has a score -> the item is excludable, not "wrong".
    monkeypatch.setattr(
        insightor_eval,
        "llm_judge_metric",
        lambda o, e, i: {"score": None, "metadata": {"reasoning": "judge down"}},
    )
    result = insightor_eval.accuracy({"sql": "SELECT 1", "request_id": "r2"}, "SELECT 1")
    assert result["score"] is None


# ── TLS verification opt-in ───────────────────────────────────────────


def test_ssl_verify_defaults_to_true(monkeypatch):
    monkeypatch.delenv("QYM_INSIGHTOR_SSL_VERIFY", raising=False)
    assert insightor_eval._insightor_ssl_verify() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_ssl_verify_explicit_opt_out(monkeypatch, value):
    monkeypatch.setenv("QYM_INSIGHTOR_SSL_VERIFY", value)
    assert insightor_eval._insightor_ssl_verify() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "anything-else"])
def test_ssl_verify_non_falsy_values_keep_verification(monkeypatch, value):
    monkeypatch.setenv("QYM_INSIGHTOR_SSL_VERIFY", value)
    assert insightor_eval._insightor_ssl_verify() is True
