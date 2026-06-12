"""Static packaging checks for the SPA build (no wheel build in unit tests).

The platform package switched from non-recursive [tool.setuptools.package-data]
globs (which silently dropped nested build output like _static/app/assets/*)
to include-package-data + MANIFEST.in grafts. These tests pin that contract.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_DIR = ROOT / "packages" / "platform"
MANIFEST = PLATFORM_DIR / "MANIFEST.in"
PYPROJECT = PLATFORM_DIR / "pyproject.toml"


def _manifest_directives() -> list[str]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return [" ".join(line.split()) for line in lines if line.strip() and not line.strip().startswith("#")]


def test_manifest_grafts_static_tree() -> None:
    assert "graft qym_platform/_static" in _manifest_directives()


def test_manifest_grafts_migrations() -> None:
    assert "graft qym_platform/migrations" in _manifest_directives()


def test_manifest_excludes_pycache() -> None:
    directives = _manifest_directives()
    assert "global-exclude __pycache__" in directives
    assert "global-exclude *.py[cod]" in directives


def test_pyproject_enables_include_package_data() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    setuptools_cfg = data["tool"]["setuptools"]
    assert setuptools_cfg["include-package-data"] is True


def test_pyproject_dropped_non_recursive_package_data_globs() -> None:
    # The old `[tool.setuptools.package-data]` table used flat `_static/x/*`
    # globs that cannot pick up `_static/app/assets/*`; MANIFEST.in grafts
    # replaced it entirely. Its return would mean a packaging regression.
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "package-data" not in data["tool"]["setuptools"]
