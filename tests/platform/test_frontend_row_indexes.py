"""Differential and operation-count contracts for browser row indexes."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize(
    "fixture", ["row_indexes_contract.cjs", "run_details_contract.cjs"]
)
def test_frontend_contract(fixture: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the frontend estimator contracts")
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(repo / "tests/platform/fixtures" / fixture), str(repo)],
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
