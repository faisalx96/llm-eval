from __future__ import annotations

from unittest.mock import MagicMock

import qym.cli.analyze as analyze_module
from qym.cli._platform_api import PlatformAPIClient


def test_platform_client_uses_implemented_analysis_route() -> None:
    client = PlatformAPIClient(platform_url="https://platform.example")
    client._post = MagicMock(return_value={"total_analyzed": 1})  # type: ignore[method-assign]

    result = client.analyze_run("run/with slash", {"concurrency": 4})

    assert result == {"total_analyzed": 1}
    client._post.assert_called_once_with(
        "/api/runs/run%2Fwith%20slash/analyze", body={"concurrency": 4}
    )


def test_analyze_summary_reads_snapshot_rows_and_metric_analyses(monkeypatch) -> None:
    payloads: list[dict] = []
    run_data = {
        "snapshot": {
            "rows": [
                {
                    "item_metadata": {
                        "root_cause": "legacy summary should not be double counted",
                        "metric_analyses": {
                            "accuracy": {"root_cause": "Reasoning Error"},
                            "format": {"root_cause": "Wrong Format"},
                        },
                    }
                },
                {"item_metadata": {"root_cause": "Dataset Issue"}},
            ]
        }
    }
    monkeypatch.setattr(
        analyze_module.PlatformAPIClient,
        "get_run",
        lambda self, run_id: run_data,
    )
    monkeypatch.setattr(analyze_module, "is_json_mode", lambda: True)
    monkeypatch.setattr(analyze_module, "output", payloads.append)

    analyze_module.analyze_summary("run-1")

    assert payloads == [
        {
            "run_id": "run-1",
            "total_items": 2,
            "total_item_metrics_analyzed": 3,
            "total_analyzed": 3,
            "categories": {
                "Reasoning Error": 1,
                "Wrong Format": 1,
                "Dataset Issue": 1,
            },
        }
    ]
