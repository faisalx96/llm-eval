from pathlib import Path

from qym.core.results import EvaluationResult


def test_default_save_path_preserves_user_provided_run_name():
    result = EvaluationResult(
        dataset_name="saudi-qa-verification-v1",
        run_name="blablabla-gpt-4o-mini-260208-1613",
        metrics=["exact_match"],
        run_metadata={"task_name": "ai_assistant", "model": "gpt-4o-mini"},
        run_config={"user_provided_run_name": True},
    )

    out_path = Path(result._default_save_path("csv", "qym_results"))
    assert out_path.name == "blablabla-gpt-4o-mini-260208-1613.csv"


def test_default_save_path_auto_run_name_has_no_duplicate_model_timestamp():
    result = EvaluationResult(
        dataset_name="saudi-qa-verification-v1",
        run_name="ai_assistant-gpt-4o-mini-260208-1613-1",
        metrics=["exact_match"],
        run_metadata={"task_name": "ai_assistant", "model": "gpt-4o-mini"},
        run_config={"user_provided_run_name": False},
    )

    out_path = Path(result._default_save_path("csv", "qym_results"))
    assert out_path.name == (
        "ai_assistant-saudi-qa-verification-v1-gpt-4o-mini-260208-1613-1.csv"
    )
