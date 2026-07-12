from unittest.mock import MagicMock

import pytest

from qym.adapters.base import FunctionAdapter
from qym.core.evaluator import Evaluator
from qym.core.multi_runner import MultiModelRunner


@pytest.mark.asyncio
async def test_function_adapter_maps_input_columns_to_task_parameters():
    def text2sql_task(question, schema):
        return f"{question} :: {schema}"

    adapter = FunctionAdapter(text2sql_task, client=None)
    adapter.input_mapping = {
        "sql_prompt": "question",
        "sql_context": "schema",
    }

    output = await adapter.arun(
        {
            "sql_prompt": "List users",
            "sql_context": "CREATE TABLE users(id INT)",
        },
        MagicMock(),
    )

    assert output == "List users :: CREATE TABLE users(id INT)"


@pytest.mark.asyncio
async def test_function_adapter_reports_missing_mapped_parameters():
    def text2sql_task(question, schema):
        return f"{question} :: {schema}"

    adapter = FunctionAdapter(text2sql_task, client=None)
    adapter.input_mapping = {"sql_prompt": "question"}

    with pytest.raises(TypeError, match="Missing required task parameters: schema"):
        await adapter.arun({"sql_prompt": "List users"}, MagicMock())


def test_evaluator_metric_arguments_include_original_and_mapped_inputs(mock_dataset):
    def task(question, schema):
        return f"{question} :: {schema}"

    def metric(output, expected, question, schema, sql_prompt):
        return 1.0

    evaluator = Evaluator(
        task=task,
        dataset=mock_dataset,
        metrics=[metric],
        input_mapping={
            "sql_prompt": "question",
            "sql_context": "schema",
        },
        config={"otel_enabled": False},
    )

    args, kwargs = evaluator._resolve_metric_arguments(
        metric,
        output="SELECT 1",
        expected="SELECT 1",
        input_data={
            "sql_prompt": "List users",
            "sql_context": "CREATE TABLE users(id INT)",
        },
    )

    assert args == ()
    assert kwargs == {
        "output": "SELECT 1",
        "expected": "SELECT 1",
        "question": "List users",
        "schema": "CREATE TABLE users(id INT)",
        "sql_prompt": "List users",
    }


def test_evaluator_validates_input_mapping(mock_task, mock_dataset):
    with pytest.raises(TypeError, match="input_mapping must be a dict"):
        Evaluator(
            task=mock_task,
            dataset=mock_dataset,
            metrics=[],
            input_mapping=[("column", "parameter")],
            config={"otel_enabled": False},
        )

    with pytest.raises(ValueError, match="input_mapping values"):
        Evaluator(
            task=mock_task,
            dataset=mock_dataset,
            metrics=[],
            input_mapping={"column": ""},
            config={"otel_enabled": False},
        )


def test_multi_model_run_preserves_input_mapping(monkeypatch, mock_dataset):
    def task(question):
        return question

    captured = {}

    def fake_run_parallel(runs, **kwargs):
        captured["runs"] = runs
        return []

    monkeypatch.setattr(Evaluator, "run_parallel", staticmethod(fake_run_parallel))

    evaluator = Evaluator(
        task=task,
        dataset=mock_dataset,
        metrics=[],
        model=["model-a", "model-b"],
        input_mapping={"question_text": "question"},
        config={"otel_enabled": False},
    )

    evaluator.run(show_tui=False, auto_save=False)

    assert [run["input_mapping"] for run in captured["runs"]] == [
        {"question_text": "question"},
        {"question_text": "question"},
    ]


def test_run_specs_preserve_input_mapping(mock_dataset):
    def task(question):
        return question

    runner = MultiModelRunner.from_runs(
        [
            {
                "name": "mapped",
                "task": task,
                "dataset": mock_dataset,
                "metrics": [],
                "input_mapping": {"question_text": "question"},
                "config": {"otel_enabled": False},
            }
        ]
    )

    assert runner.specs[0].input_mapping == {"question_text": "question"}
