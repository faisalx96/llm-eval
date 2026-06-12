"""DOC-4: qym.__version__ must track the installed distribution metadata.

Regression tests for version drift: ``qym/__init__.py`` previously hardcoded
``__version__ = "0.9.0"`` while ``packages/sdk/pyproject.toml`` declared
1.1.0, so runs reported the wrong SDK version.
"""

import importlib.metadata
import re
from pathlib import Path

import pytest

import qym


def test_version_matches_distribution_metadata():
    assert qym.__version__ == importlib.metadata.version("qym")


def test_version_matches_sdk_pyproject():
    """When running from a source checkout, __version__ must match pyproject.

    Catches both a re-hardcoded ``__version__`` and a stale editable install
    whose dist metadata lags behind ``pyproject.toml`` (fix: re-run
    ``pip install -e packages/sdk --no-deps``).
    """
    pyproject = Path(qym.__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("qym not running from a source checkout")

    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "could not find a version field in packages/sdk/pyproject.toml"
    assert qym.__version__ == match.group(1)


def test_version_is_a_plausible_version_string():
    assert re.fullmatch(r"\d+(\.\d+)*([abc.]\S*)?", qym.__version__), (
        f"__version__ does not look like a version: {qym.__version__!r}"
    )


def test_version_is_not_the_old_hardcoded_value():
    assert qym.__version__ != "0.9.0"
