from qym.metrics.builtin import exact_match


def test_exact_match_returns_numeric_score_for_match():
    result = exact_match("Paris", "Paris")
    assert isinstance(result, dict)
    assert result["score"] == 1.0


def test_exact_match_returns_numeric_score_for_mismatch():
    result = exact_match("Paris", "London")
    assert isinstance(result, dict)
    assert result["score"] == 0.0
