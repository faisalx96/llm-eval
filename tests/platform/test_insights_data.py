from dataclasses import asdict

from qym_platform.services.insights_data import InsightData, RootCauseData


def test_insight_data_uses_independent_dictionary_defaults() -> None:
    first = InsightData(category="Accuracy")
    second = InsightData(category="Safety")

    first.models["model-a"] = 2
    first.root_causes["ambiguous prompt"] = RootCauseData()

    assert second.models == {}
    assert second.root_causes == {}


def test_insight_data_serializes_to_the_expected_nested_dictionary() -> None:
    insight = InsightData(
        category="Accuracy",
        models={"model-a": 3},
        metrics={"exact_match": {"success": 2, "fail": 1}},
        root_causes={
            "ambiguous prompt": RootCauseData(
                datasets={"support": 1},
                tools={"web_search": 2},
            )
        },
    )

    assert asdict(insight) == {
        "category": "Accuracy",
        "models": {"model-a": 3},
        "datasets": {},
        "tasks": {},
        "metrics": {"exact_match": {"success": 2, "fail": 1}},
        "tools": {},
        "extra_data": {},
        "root_causes": {
            "ambiguous prompt": {
                "models": {},
                "datasets": {"support": 1},
                "tasks": {},
                "metrics": {},
                "tools": {"web_search": 2},
                "extra_data": {},
            }
        },
    }


def test_add_extra_data_and_get_work_at_both_levels() -> None:
    root_cause = RootCauseData()
    root_cause.add_extra_data("example_ids", ["item-1", "item-2"])
    insight = InsightData(
        category="Accuracy",
        root_causes={"ambiguous prompt": root_cause},
    )
    insight.add_extra_data("severity", "high")

    assert insight.get("category") == "Accuracy"
    assert insight.get("severity") == "high"
    assert insight.get("ambiguous prompt") is root_cause
    assert root_cause.get("example_ids") == ["item-1", "item-2"]
    assert insight.get("missing", "fallback") == "fallback"


def test_drop_resets_declared_fields_and_removes_dynamic_data() -> None:
    root_cause = RootCauseData(models={"model-a": 1})
    insight = InsightData(
        category="Accuracy",
        models={"model-a": 2},
        root_causes={"ambiguous prompt": root_cause},
    )
    insight.add_extra_data("severity", "high")

    assert insight.drop("models") == {"model-a": 2}
    assert insight.models == {}
    assert insight.drop("severity") == "high"
    assert "severity" not in insight.extra_data
    assert insight.drop("ambiguous prompt") is root_cause
    assert insight.root_causes == {}
    assert insight.drop("missing") is None


def test_drop_category_preserves_the_declared_schema() -> None:
    insight = InsightData(category="Accuracy")

    assert insight.drop("category") == "Accuracy"
    assert insight.category == ""
