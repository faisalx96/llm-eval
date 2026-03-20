"""Tests for MetricScoredPayload label/explanation fields — ingest, API response, backward compat."""

import pytest
import sys
from unittest.mock import MagicMock
from datetime import datetime

# Skip entire module if pydantic_settings is not available
pydantic_settings = pytest.importorskip("pydantic_settings", reason="pydantic_settings required for platform tests")
sqlalchemy = pytest.importorskip("sqlalchemy", reason="sqlalchemy required for platform tests")


@pytest.fixture(scope="module", autouse=True)
def setup_test_database_url():
    """Set up a test database URL before any platform module imports."""
    import os
    os.environ["QYM_DATABASE_URL"] = "sqlite:///:memory:"
    yield


class TestMetricScoredPayload:
    """Test that MetricScoredPayload accepts label and explanation."""

    def test_payload_with_label_explanation(self):
        from qym_platform.events import MetricScoredPayload

        payload = MetricScoredPayload(
            item_id="item_1",
            metric_name="faithfulness_llm",
            score_numeric=1.0,
            score_raw={"score": 1.0, "metadata": {"label": "faithful"}},
            meta={},
            label="faithful",
            explanation="The response is grounded in context.",
        )
        assert payload.label == "faithful"
        assert payload.explanation == "The response is grounded in context."

    def test_payload_without_label_explanation(self):
        from qym_platform.events import MetricScoredPayload

        payload = MetricScoredPayload(
            item_id="item_1",
            metric_name="exact_match",
            score_numeric=1.0,
        )
        assert payload.label is None
        assert payload.explanation is None

    def test_payload_backward_compat(self):
        """Old SDK payloads without label/explanation should still parse."""
        from qym_platform.events import MetricScoredPayload

        # Simulate old payload dict (no label/explanation)
        old_data = {
            "item_id": "item_1",
            "metric_name": "exact_match",
            "score_numeric": 0.5,
            "score_raw": 0.5,
            "meta": {},
        }
        payload = MetricScoredPayload(**old_data)
        assert payload.label is None
        assert payload.explanation is None
        assert payload.score_numeric == 0.5


class TestRunItemScoreModel:
    """Test that RunItemScore model has label and explanation columns."""

    def test_model_has_label_explanation(self):
        from qym_platform.db.models import RunItemScore

        # Verify columns exist on the model
        columns = {c.name for c in RunItemScore.__table__.columns}
        assert "label" in columns
        assert "explanation" in columns

    def test_model_label_nullable(self):
        from qym_platform.db.models import RunItemScore

        label_col = RunItemScore.__table__.columns["label"]
        assert label_col.nullable is True

    def test_model_explanation_nullable(self):
        from qym_platform.db.models import RunItemScore

        expl_col = RunItemScore.__table__.columns["explanation"]
        assert expl_col.nullable is True
