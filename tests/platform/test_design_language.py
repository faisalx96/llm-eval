"""Enforce docs/DESIGN_LANGUAGE.md over the dashboard static assets.

These tests freeze the design-language rules established in July 2026:
tokens-only typography, the text-color ramp, and the mono-for-data policy.
If a test here fails, read docs/DESIGN_LANGUAGE.md before "fixing" the test —
the fix is almost always in your CSS, not in the frozen inventory.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO / "packages" / "platform" / "qym_platform" / "_static" / "dashboard"

# Vendored files exempt from all rules (see DESIGN_LANGUAGE.md §5).
# Design scratch mocks live in tmp/mockups/ (gitignored), outside this dir.
EXEMPT = {"docs-hljs.min.js"}
EXEMPT_PREFIXES = ()

FONT_SIZE_CSS = re.compile(r"font-size:\s*([\d.]+)px")
FONT_SIZE_JS = re.compile(r"fontSize:\s*['\"]([\d.]+)px['\"]")


def _asset_files() -> list[Path]:
    files = []
    for p in sorted(DASHBOARD_DIR.iterdir()):
        if p.suffix not in {".html", ".css", ".js"}:
            continue
        if p.name in EXEMPT or p.name.startswith(EXEMPT_PREFIXES):
            continue
        files.append(p)
    assert files, "dashboard asset dir not found or empty"
    return files


def _hardcoded_sizes(text: str) -> list[str]:
    return FONT_SIZE_CSS.findall(text) + FONT_SIZE_JS.findall(text)


# ---------------------------------------------------------------------------
# Frozen inventory of hardcoded pixel font sizes.
#
# Every entry is a decorative glyph (×, ▶, ●, ↕, chevrons, oversized
# empty-state icons) or the sanctioned docs prose scale — never readable UI
# text. Adding a hardcoded size anywhere else is a design-language violation:
# use a var(--font-*) token instead (see docs/DESIGN_LANGUAGE.md §1–2).
# If you genuinely added a new glyph, update this dict in the same commit and
# name the selector in your commit message.
# ---------------------------------------------------------------------------
FROZEN_HARDCODED_SIZES: dict[str, list[str]] = {
    "compare.html": ["7", "10", "10", "10", "10", "10", "10", "11", "11", "13", "14", "14", "20", "32", "48"],
    "dashboard.css": ["8", "9", "14", "16", "18", "18", "20", "20", "20", "24", "24", "32", "48", "48"],
    "datasets.html": ["10", "13", "13", "14", "32"],
    "docs.css": ["11", "11", "11", "11", "11", "11", "11", "12", "12", "12", "12", "12", "13", "13", "13", "13", "13", "13", "13", "13", "13", "14", "15", "15", "16", "16", "20", "28"],
    "reviews.html": ["14", "40"],
    "run.html": ["7", "10", "10", "10", "10", "10", "11", "11", "11", "13", "14", "14", "14", "16", "48", "48"],
    "shell.css": ["10", "10", "10", "11", "11", "11", "11", "11", "12", "12", "24"],
    "trace_viewer.js": ["11", "12"],
}


class TestTypographyTokens:
    def test_no_new_hardcoded_font_sizes(self):
        """Font sizes come from var(--font-*) tokens; hardcoded px is frozen."""
        problems = []
        for path in _asset_files():
            found = Counter(_hardcoded_sizes(path.read_text(encoding="utf-8")))
            allowed = Counter(FROZEN_HARDCODED_SIZES.get(path.name, []))
            extra = found - allowed
            if extra:
                problems.append(f"{path.name}: new hardcoded font-size(s) {dict(extra)}")
        assert not problems, (
            "Hardcoded font sizes outside the frozen glyph allowlist. "
            "Use var(--font-*) tokens (docs/DESIGN_LANGUAGE.md §1). "
            + "; ".join(problems)
        )

    def test_frozen_inventory_not_stale(self):
        """Ratchet down: if hardcoded sizes were removed, shrink the freeze."""
        stale = []
        for name, sizes in FROZEN_HARDCODED_SIZES.items():
            path = DASHBOARD_DIR / name
            if not path.exists():
                stale.append(f"{name}: file gone")
                continue
            found = Counter(_hardcoded_sizes(path.read_text(encoding="utf-8")))
            missing = Counter(sizes) - found
            if missing:
                stale.append(f"{name}: freeze lists removed size(s) {dict(missing)}")
        assert not stale, (
            "FROZEN_HARDCODED_SIZES is stale — update it to match reality "
            "(shrinking is good, keep the ratchet tight): " + "; ".join(stale)
        )

    def test_root_tokens_present(self):
        """The token vocabulary itself must not drift or get renamed."""
        css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
        for decl in (
            "--text-primary: #ededf0",
            "--text-secondary: #a8a8ba",
            "--text-muted: #9a9ab2",
            "--text-dim: #6b6b80",
            "--font-xs: 10px",
            "--font-sm: 11px",
            "--font-base: 12px",
            "--font-md: 13px",
            "--font-lg: 15px",
            "--font-xl: 18px",
            "--font-title: 22px",
            "--font-stat: 26px",
            "--accent-tertiary-soft: #c084fc",
        ):
            assert decl in css, f"dashboard.css :root lost token declaration '{decl}'"
        shell = (DASHBOARD_DIR / "shell.css").read_text(encoding="utf-8")
        for decl in ("--shell-font-sm: 13px", "--shell-font-md: 15px"):
            assert decl in shell, f"shell.css lost token declaration '{decl}'"

    def test_no_scoped_font_token_forks(self):
        """--font-* must mean one value everywhere; forks use --shell-font-*."""
        for path in _asset_files():
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"^\s*(--font-(?:xs|sm|base|md|lg|xl|title|stat)):", text, re.M):
                # Only dashboard.css :root may define the shared scale.
                assert path.name == "dashboard.css", (
                    f"{path.name} redefines {m.group(1)} — scoped forks of the "
                    "shared type scale are banned (docs/DESIGN_LANGUAGE.md §1)"
                )


class TestColorRamp:
    def test_banned_patterns(self):
        """Old sub-AA grays and removed font families must not reappear."""
        banned = {
            "#7a7a90": "old --text-muted (4.1:1, fails AA) — use var(--text-muted)",
            "#50505e": "old --text-dim (2:1) — use var(--text-dim) or var(--text-muted)",
            "DM Sans": "removed webfont — use var(--font-sans)",
            "Georgia": "removed serif — use var(--font-sans)",
            "fonts.googleapis.com": "no webfont imports",
        }
        problems = []
        for path in _asset_files():
            text = path.read_text(encoding="utf-8")
            for needle, why in banned.items():
                if needle.lower() in text.lower():
                    problems.append(f"{path.name}: '{needle}' ({why})")
        assert not problems, "Banned design patterns found: " + "; ".join(problems)

    def test_dim_not_on_table_headers(self):
        """Table header rules must not use --text-dim (the original bug)."""
        header_block = re.compile(
            r"(?:thead\s+th|th)\s*\{[^}]*color:\s*var\(--text-dim\)", re.S
        )
        for path in _asset_files():
            if path.suffix == ".js":
                continue
            text = path.read_text(encoding="utf-8")
            assert not header_block.search(text), (
                f"{path.name}: a table-header rule uses --text-dim; headers are "
                "var(--text-muted) minimum (docs/DESIGN_LANGUAGE.md §2 rule 2)"
            )


class TestSharedComponents:
    def test_qdt_table_reference_implementation(self):
        """.qdt-table is the blessed table recipe — keep it on-spec."""
        css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
        th = re.search(r"\.qdt-table thead th \{(.*?)\}", css, re.S)
        assert th, ".qdt-table thead th rule missing from dashboard.css"
        assert "font-size: var(--font-sm)" in th.group(1)
        assert "color: var(--text-muted)" in th.group(1)
        td = re.search(r"\.qdt-table tbody td \{(.*?)\}", css, re.S)
        assert td, ".qdt-table tbody td rule missing from dashboard.css"
        assert "font-size: var(--font-base)" in td.group(1)
        assert "color: var(--text-secondary)" in td.group(1)

    def test_design_language_doc_exists_and_wired(self):
        doc = REPO / "docs" / "DESIGN_LANGUAGE.md"
        assert doc.exists(), "docs/DESIGN_LANGUAGE.md is missing"
        text = doc.read_text(encoding="utf-8")
        assert "--font-title" in text and "--text-dim" in text
        agents = REPO / "AGENTS.md"
        assert agents.exists() and "DESIGN_LANGUAGE.md" in agents.read_text(
            encoding="utf-8"
        ), "AGENTS.md must point to docs/DESIGN_LANGUAGE.md"
        # CLAUDE.md is gitignored (local-only); enforce the pointer only where it exists.
        claude = REPO / "CLAUDE.md"
        if claude.exists():
            assert "DESIGN_LANGUAGE.md" in claude.read_text(
                encoding="utf-8"
            ), "CLAUDE.md exists but does not point to docs/DESIGN_LANGUAGE.md"
