from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard" / "dashboard.js"


def test_dashboard_delete_action_binding_allows_non_deletable_runs() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "const deleteBtn = tr.querySelector('.delete-run');" in source
    assert "if (deleteBtn) deleteBtn.addEventListener('click'" in source
    assert "tr.querySelector('.delete-run').addEventListener" not in source
