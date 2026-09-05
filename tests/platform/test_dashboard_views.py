"""Server summary views match the original browser's numerical definitions."""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qym_platform.services.dashboard_views import build_overview_data

ROOT = Path(__file__).resolve().parents[2]


def close(actual, expected, path="root"):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)), path
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
            path,
            actual,
            expected,
        )
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys(), (path, actual.keys(), expected.keys())
        for key in expected:
            close(actual[key], expected[key], path + "." + key)
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (left, right) in enumerate(zip(actual, expected)):
            close(left, right, f"{path}[{index}]")
    else:
        assert actual == expected, (path, actual, expected)


def test_streamed_overview_matches_browser_reducers_randomized():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the independent browser reducer oracle")
    rng = random.Random(94117)
    now = datetime(2026, 9, 5, 10, 25, tzinfo=timezone.utc)
    cases = []
    for size in [0, 1, 2, 3, 8, 25, 100, 251]:
        rows = []
        for i in range(size):
            row = {
                "run_id": str(i),
                "file_path": str(i),
                "task_name": rng.choice(["task", "مهمة", "another"]),
                "model_name": rng.choice(
                    ["model-2", "model-11", "Alpha", "alpha", "éclair", "نموذج"]
                ),
                "dataset_name": rng.choice(["dataset", "other"]),
                "timestamp": (now - timedelta(hours=rng.randrange(300))).isoformat(),
                "metrics": ["accuracy", "numeric", "count", "flag"],
                "metric_averages": {
                    metric: rng.choice([0, 0, 0, 0.1, 0.8, 1, 2, -1, None])
                    for metric in ["accuracy", "numeric", "count", "flag"]
                },
                "metric_specs": {
                    metric: {
                        "score_type": rng.choice(
                            ["percentage", "count", "number", "boolean", "legacy"]
                        )
                    }
                    for metric in ["accuracy", "numeric", "count", "flag"]
                },
                "total_items": rng.randrange(100),
                "success_rate": rng.random(),
                "avg_latency_ms": rng.choice([0, None, 1, 19, 900.5]),
                "median_latency_ms": rng.choice([0, None, 1, 20.5, 2000]),
                "trace_stats": rng.choice(
                    [
                        None,
                        {},
                        {"has_reasoning_tokens": True},
                        {"avg_reasoning_tokens": 12},
                    ]
                ),
            }
            rows.append(row)
        # The API supplies the same task/model group order as legacy flattenRuns.
        grouped = {}
        for row in rows:
            grouped.setdefault(row["task_name"], {}).setdefault(
                row["model_name"], []
            ).append(row)
        rows = [
            r for models in grouped.values() for group in models.values() for r in group
        ]
        filtered = [r for i, r in enumerate(rows) if i % 3]
        computed = build_overview_data(iter(rows), iter(filtered), now=now)
        cases.append(
            {
                "unfiltered": rows,
                "filtered": filtered,
                "now": now.isoformat(),
                "computed": computed,
            }
        )
    response = subprocess.run(
        [
            node,
            str(ROOT / "tests/platform/fixtures/dashboard_views_oracle.cjs"),
            str(ROOT),
        ],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
    )
    results = json.loads(response.stdout)
    for case, result in zip(cases, results):
        close(case["computed"]["aggregations"], result["aggregations"])
        close(case["computed"]["metric_types"], result["metric_types"])
        close(result["normalized"], result["chart_data"])
        assert case["computed"]["total_count"] == len(case["unfiltered"])
        assert case["computed"]["total_runs"] == len(case["filtered"])


def test_scope_metrics_missing_values_and_zero_median():
    rows = [
        {
            "task_name": "task",
            "model_name": "m",
            "dataset_name": "d",
            "timestamp": "2026-09-05T10:00:00Z",
            "metrics": ["rare"],
            "metric_averages": {"rare": 0.9},
            "trace_stats": {},
        }
    ]
    result = build_overview_data(iter(rows), iter([]))
    assert result["all_metrics"] == ["rare"]
    assert result["metrics"] == []
    assert result["total_count"] == 1 and result["total_runs"] == 0
    assert not result["has_trace_stats"]
