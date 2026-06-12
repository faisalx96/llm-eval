"""Repo hygiene regression tests.

Guards the cleanup done per AUDIT_REPORT.md (repo hygiene quick wins):
- mock/dev pages no longer ship in the publicly served dashboard static dir
- the dead, unmounted ``qym_platform/api/org.py`` module stays deleted
- generated artifacts (``outputs/``, ``tmp/``, ``node_modules/``) are ignored
  by git and excluded from the Docker build context
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASHBOARD_STATIC = (
    REPO / "packages" / "platform" / "qym_platform" / "_static" / "dashboard"
)


class TestNoMockPagesInStatic:
    """Mock/dev pages must not ship in the production static directory."""

    def test_mock_navigation_removed(self):
        assert not (DASHBOARD_STATIC / "mock_navigation.html").exists()

    def test_mock_navigation_copy_removed(self):
        assert not (DASHBOARD_STATIC / "mock_navigation copy.html").exists()

    def test_mocks_directory_removed(self):
        assert not (DASHBOARD_STATIC / "mocks").exists()

    def test_dashboard_static_still_present(self):
        # Sanity check: the cleanup must not have removed real assets.
        assert (DASHBOARD_STATIC / "index.html").exists()
        assert (DASHBOARD_STATIC / "dashboard.js").exists()


class TestDeadOrgModuleRemoved:
    """The unmounted org admin API module stays deleted."""

    def test_org_module_removed(self):
        api = REPO / "packages" / "platform" / "qym_platform" / "api"
        assert api.exists()
        assert not (api / "org.py").exists()


class TestIgnoreFiles:
    """Generated artifacts are ignored by git and the Docker build context."""

    def test_gitignore_covers_artifacts(self):
        entries = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        for required in ("outputs/", "tmp/", "node_modules/"):
            assert required in entries, f"Missing .gitignore entry: {required}"

    def test_dockerignore_covers_artifacts(self):
        entries = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
        for required in (
            ".git/",
            "outputs/",
            "tmp/",
            "node_modules/",
            "docs_portal/node_modules/",
        ):
            assert required in entries, f"Missing .dockerignore entry: {required}"
