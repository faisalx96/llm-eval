"""Tests for MetricResult dataclass — from_raw, to_legacy_dict, backward compat."""

import pytest
from qym.metrics.result import MetricResult


class TestFromRaw:
    def test_passthrough_metric_result(self):
        mr = MetricResult(score=0.8, label="good")
        assert MetricResult.from_raw(mr) is mr

    def test_float(self):
        mr = MetricResult.from_raw(0.75)
        assert mr.score == 0.75
        assert mr.label is None
        assert mr.explanation is None
        assert mr.kind == "code"

    def test_int(self):
        mr = MetricResult.from_raw(1)
        assert mr.score == 1.0

    def test_bool_true(self):
        mr = MetricResult.from_raw(True)
        assert mr.score == 1.0

    def test_bool_false(self):
        mr = MetricResult.from_raw(False)
        assert mr.score == 0.0

    def test_dict_with_score(self):
        raw = {"score": 0.9, "metadata": {"reason": "looks good"}}
        mr = MetricResult.from_raw(raw)
        assert mr.score == 0.9
        assert mr.metadata == {"reason": "looks good"}

    def test_dict_with_score_and_label(self):
        raw = {"score": 1.0, "label": "faithful", "explanation": "grounded in context"}
        mr = MetricResult.from_raw(raw)
        assert mr.score == 1.0
        assert mr.label == "faithful"
        assert mr.explanation == "grounded in context"

    def test_dict_with_error(self):
        raw = {"error": "timeout", "score": 0}
        mr = MetricResult.from_raw(raw)
        assert mr.score == 0.0
        assert mr.metadata == {"error": "timeout"}

    def test_dict_error_only(self):
        raw = {"error": "crash"}
        mr = MetricResult.from_raw(raw)
        assert mr.score == 0.0
        assert "error" in mr.metadata

    def test_dict_bool_score(self):
        mr = MetricResult.from_raw({"score": True})
        assert mr.score == 1.0

    def test_dict_no_score(self):
        mr = MetricResult.from_raw({"metadata": {"x": 1}})
        assert mr.score == 0.0
        assert mr.metadata == {"x": 1}

    def test_unknown_type(self):
        mr = MetricResult.from_raw("some string")
        assert mr.score == 0.0
        assert mr.metadata == {"raw": "some string"}

    def test_none_metadata_in_dict(self):
        mr = MetricResult.from_raw({"score": 0.5, "metadata": "not a dict"})
        assert mr.score == 0.5
        assert mr.metadata == {}


class TestToLegacyDict:
    def test_basic(self):
        mr = MetricResult(score=0.8)
        d = mr.to_legacy_dict()
        assert d == {"score": 0.8, "metadata": {}}

    def test_with_label_and_explanation(self):
        mr = MetricResult(score=1.0, label="faithful", explanation="grounded")
        d = mr.to_legacy_dict()
        assert d["score"] == 1.0
        assert d["metadata"]["label"] == "faithful"
        assert d["metadata"]["explanation"] == "grounded"

    def test_with_kind(self):
        mr = MetricResult(score=0.5, kind="llm")
        d = mr.to_legacy_dict()
        assert d["metadata"]["kind"] == "llm"

    def test_code_kind_omitted(self):
        mr = MetricResult(score=0.5, kind="code")
        d = mr.to_legacy_dict()
        assert "kind" not in d["metadata"]

    def test_preserves_metadata(self):
        mr = MetricResult(score=0.5, metadata={"foo": "bar"})
        d = mr.to_legacy_dict()
        assert d["metadata"]["foo"] == "bar"


class TestBackwardCompat:
    """Verify that from_raw -> to_legacy_dict round-trips produce
    dicts that existing code (isinstance checks) can handle."""

    def test_float_roundtrip(self):
        d = MetricResult.from_raw(0.9).to_legacy_dict()
        assert isinstance(d, dict)
        assert d["score"] == 0.9
        assert isinstance(d["metadata"], dict)

    def test_dict_roundtrip(self):
        original = {"score": 0.7, "metadata": {"x": 1}}
        d = MetricResult.from_raw(original).to_legacy_dict()
        assert d["score"] == 0.7
        assert d["metadata"]["x"] == 1
