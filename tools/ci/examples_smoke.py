#!/usr/bin/env python
"""Smoke-check the example scripts without executing them.

For every ``examples/**/*.py`` file this script:

1. Byte-compiles the file (``py_compile``) to catch syntax errors.
2. Parses the AST and checks that every *top-level, unguarded* absolute import
   resolves against the installed environment (``importlib.util.find_spec`` on
   the root module name only — nothing is executed). Imports of sibling
   modules/packages inside the example's own directory count as resolvable.
3. Flags any top-level import of ``langfuse`` that is not guarded by a
   ``try``/``except`` (or ``if TYPE_CHECKING``) block — examples must not hard
   depend on langfuse at import time.
4. Flags any import of ``llm_eval`` anywhere in the file (legacy package name).

Exit codes: 0 = clean, 1 = findings. The CI job ``examples-smoke`` is a
blocking gate (continue-on-error: false in .github/workflows/ci.yml).
"""

from __future__ import annotations

import ast
import importlib.util
import py_compile
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"

#: Modules that must never be imported by examples, anywhere in the file.
FORBIDDEN_ANYWHERE = {"llm_eval"}

#: Modules that may only be imported at top level inside a guard.
GUARD_REQUIRED_TOP_LEVEL = {"langfuse"}


def _is_type_checking_test(test: ast.expr) -> bool:
    """Return True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _iter_module_imports(
    body: List[ast.stmt], guarded: bool
) -> Iterator[Tuple[ast.stmt, bool]]:
    """Yield (import_node, guarded) for imports at module level.

    "Module level" includes imports nested in ``try`` and ``if`` blocks (they
    still run at import time) but not imports inside functions or classes.
    Anything inside a ``try`` body or an ``if TYPE_CHECKING:`` body counts as
    guarded.
    """
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node, guarded
        elif isinstance(node, ast.Try):
            yield from _iter_module_imports(node.body, True)
            for handler in node.handlers:
                yield from _iter_module_imports(handler.body, guarded)
            yield from _iter_module_imports(node.orelse, guarded)
            yield from _iter_module_imports(node.finalbody, guarded)
        elif isinstance(node, ast.If):
            branch_guarded = guarded or _is_type_checking_test(node.test)
            yield from _iter_module_imports(node.body, branch_guarded)
            yield from _iter_module_imports(node.orelse, guarded)
        # Do not descend into FunctionDef / AsyncFunctionDef / ClassDef:
        # those imports do not run at import time.


def _root_names(node: ast.stmt) -> List[str]:
    """Root module names imported by an Import/ImportFrom node ('' skipped)."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return []  # relative import — resolved within the example package
        return [node.module.split(".")[0]] if node.module else []
    return []


def _resolves(root: str, example_file: Path) -> bool:
    """True if ``root`` is importable or is a sibling module of the example."""
    sibling_dir = example_file.parent
    if (sibling_dir / f"{root}.py").exists() or (sibling_dir / root).is_dir():
        return True
    try:
        return importlib.util.find_spec(root) is not None
    except (ImportError, ValueError):
        return False


def check_file(path: Path) -> List[str]:
    findings: List[str] = []
    rel = path.relative_to(REPO_ROOT).as_posix()

    # 1. Syntax: byte-compile without executing.
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        findings.append(f"{rel}: does not compile: {exc.msg.strip()}")
        return findings  # AST checks would fail on the same syntax error.

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    # 2 + 3. Top-level imports: resolution and langfuse guard policy.
    for node, guarded in _iter_module_imports(tree.body, guarded=False):
        for root in _root_names(node):
            if root in GUARD_REQUIRED_TOP_LEVEL and not guarded:
                findings.append(
                    f"{rel}:{node.lineno}: top-level import of '{root}' "
                    "without a try/except guard"
                )
            if not guarded and not _resolves(root, path):
                findings.append(
                    f"{rel}:{node.lineno}: top-level import '{root}' does not "
                    "resolve against the installed packages"
                )

    # 4. llm_eval is forbidden anywhere, including inside functions.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _root_names(node):
                if root in FORBIDDEN_ANYWHERE:
                    findings.append(
                        f"{rel}:{node.lineno}: import of legacy module '{root}'"
                    )

    return findings


def main() -> int:
    if not EXAMPLES_DIR.is_dir():
        print(f"examples directory not found at {EXAMPLES_DIR}", file=sys.stderr)
        return 2

    files = sorted(
        p
        for p in EXAMPLES_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    if not files:
        print("no example .py files found", file=sys.stderr)
        return 2

    all_findings: List[str] = []
    for path in files:
        all_findings.extend(check_file(path))

    print(f"checked {len(files)} example file(s)")
    if all_findings:
        print(f"\n{len(all_findings)} finding(s):")
        for finding in all_findings:
            print(f"  - {finding}")
        return 1
    print("all examples passed smoke checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
