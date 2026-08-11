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
UI_COMPONENTS = DASHBOARD_DIR / "ui_components.css"
UI_BEHAVIOR = DASHBOARD_DIR / "ui_components.js"

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


def _rule_body(text: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text, re.S)
    assert match, f"CSS rule missing: {selector}"
    return match.group(1)


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
    "codemirror-bundle.js": ["14"],
    "compare.html": ["7", "10", "10", "10", "10", "10", "10", "11", "11", "13", "14", "14", "20", "32", "48"],
    "dashboard.css": ["8", "9", "14", "16", "18", "18", "20", "20", "20", "24", "24", "32", "48", "48"],
    "datasets.html": ["10", "13", "13", "14", "32"],
    "docs.css": ["11", "11", "11", "11", "11", "11", "11", "12", "12", "12", "12", "13", "13", "13", "13", "13", "13", "13", "13", "13", "14", "15", "15", "16", "16", "20", "28"],
    "reviews.html": ["40"],
    "run.html": ["7", "10", "10", "10", "10", "10", "11", "11", "11", "13", "14", "14", "14", "16", "48", "48"],
    "shell.css": ["10", "10", "10", "11", "11", "11", "11", "11", "12", "12", "24"],
    "trace_viewer.js": ["11", "12", "12"],
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
    def test_shared_ui_primitives_are_on_spec(self):
        """The approved consistency decisions stay centralized and tokenized."""
        assert UI_COMPONENTS.exists(), "ui_components.css is the shared primitive layer"
        css = UI_COMPONENTS.read_text(encoding="utf-8")
        dashboard_css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
        assert "--control-height: 24px;" in dashboard_css
        assert ".field-input" not in css, "42px authentication fields are not compact controls"
        assert ".pg-connection-select" not in css, (
            "the connection select inherits its 42px composite shell"
        )

        for selector in (
            ".qym-control",
            ".qym-dropdown",
            ".qym-dropdown__search",
            ".qym-dropdown__actions",
            ".qym-dropdown__option",
            ".qym-dropdown__only",
            ".qym-tabs",
            ".qym-tabs__tab",
            ".qym-segmented",
            ".qym-segmented__option",
            ".qym-badge",
            ".qym-badge--success",
            ".qym-badge--info",
            ".qym-badge--danger",
            ".qym-badge--warning",
            ".qym-badge--neutral",
            ".qym-tag",
            ".qym-tag--role",
            ".qym-tag--accent",
            ".qym-tag--count",
            ".qym-tag--data",
            ".qym-tag--version",
            ".qym-tag--success",
            ".qym-tag--info",
            ".qym-tag--warning",
            ".qym-tag--danger",
            ".qym-chip",
            ".qym-icon-action",
            ".qym-stat-strip",
            ".qym-stat-strip__item",
            ".qym-stat-strip__label",
            ".qym-stat-strip__value",
            ".qym-help-marker",
            ".qym-help-tooltip",
        ):
            assert selector in css, f"{selector} missing from shared primitive layer"

        for contract in (
            "height: var(--control-height)",
            "border-radius: var(--control-radius)",
            "min-height: var(--dropdown-option-height)",
            "min-height: var(--tab-height)",
            "height: 100%",
            "background: var(--accent-primary)",
            "min-height: var(--badge-height)",
            "min-height: var(--chip-height)",
            "min-height: var(--stat-strip-min-height)",
            "align-items: flex-start",
            "width: var(--info-marker-size)",
            "font-family: var(--font-sans)",
            "font-family: var(--font-mono)",
            "--dsx-action-h: var(--control-height)",
            "padding-left: 26px",
            ".qym-inline-action",
            ".reviews-search input",
            ".pg-mapping-key-select",
        ):
            assert contract in css, f"shared component contract lost: {contract}"

        for canonical_contract in (
            ":is(.qym-dropdown, .multi-select-dropdown).open",
            "display: none",
            "position: absolute",
            ".qym-stat-strip__item:last-child",
            "left: 50%",
            "bottom: calc(100% + var(--space-sm))",
            "[aria-pressed=\"true\"]",
        ):
            assert canonical_contract in css, (
                f"canonical classes must work without a legacy alias: {canonical_contract}"
            )

    def test_badges_tags_and_icon_actions_keep_distinct_silhouettes(self):
        """Status pills stay outlined; metadata and icon actions stay flat."""
        css = UI_COMPONENTS.read_text(encoding="utf-8")

        icon_actions = css.split(
            "/* Compact icon actions — quiet surfaces; only the glyph changes on hover. */",
            1,
        )[1].split("/* Clearing active filters", 1)[0]
        for declaration in (
            "width: var(--control-height)",
            "height: var(--control-height)",
            "border: 0",
            "border-radius: var(--control-radius)",
            "background: transparent",
            "color: var(--accent-primary)",
        ):
            assert declaration in icon_actions
        hover_rule = icon_actions.split("):hover {", 1)[1].split("}", 1)[0]
        copied_rule = icon_actions.split(").qym-icon-action.copied {", 1)[1].split("}", 1)[0]
        focus_rule = icon_actions.split("):focus-visible {", 1)[1].split("}", 1)[0]
        for state_rule in (hover_rule, copied_rule, focus_rule):
            assert "background: transparent;" in state_rule
            assert "box-shadow: none;" in state_rule
            assert "color-mix(" not in state_rule
        assert "0 0 12px color-mix(in srgb, var(--accent-primary)" not in icon_actions

        statuses = css.split(
            "/* 5. Passive status/outcome state — tinted outline. */",
            1,
        )[1].split(
            "/* Passive role, provenance, metadata, and count tags",
            1,
        )[0]
        assert "border: 1px solid var(--border-default)" in statuses
        assert "border-radius: 999px" in statuses

        tags = css.split(
            "/* Passive role, provenance, metadata, and count tags — flat rounded squares. */",
            1,
        )[1].split("/* 6. Interactive filters", 1)[0]
        assert "min-height: var(--badge-height)" in tags
        assert "border: 0" in tags
        assert "border-radius: var(--control-radius)" in tags

    def test_compact_control_exceptions_and_alignment_are_preserved(self):
        ui_css = UI_COMPONENTS.read_text(encoding="utf-8")
        dashboard_css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
        login = (DASHBOARD_DIR / "login.html").read_text(encoding="utf-8")

        auth_input = _rule_body(login, ".field-input")
        assert "min-height: 42px" in auth_input
        assert "font-size: var(--font-md)" in auth_input

        connection = _rule_body(dashboard_css, ".pg-connection")
        assert "height: 42px" in connection
        connection_select = _rule_body(dashboard_css, ".pg-connection-select")
        for declaration in ("height: 100%", "border: 0", "background: transparent"):
            assert declaration in connection_select

        companions = ui_css.split(
            "/* Compact rows keep their action companions level with the 24px field. */",
            1,
        )[1].split("}", 1)[0]
        for selector in (
            ".add-bar > .btn",
            ".bootstrap-form > .btn",
            ".pg-add-btn",
            ".qym-inline-action",
            ".tv-header-btn",
            ".tv-close",
        ):
            assert selector in companions
        for declaration in (
            "min-height: var(--control-height)",
            "height: var(--control-height)",
            "padding-top: 0",
            "padding-bottom: 0",
        ):
            assert declaration in companions

        trace = _rule_body(ui_css, ".tv-search-wrap > input.tv-search")
        assert "padding-left: 26px" in trace
        root_cause_action = _rule_body(
            ui_css,
            ".root-cause-dropdown .rc-custom-input > button.qym-inline-action",
        )
        assert "border-radius: var(--control-radius)" in root_cause_action
        assert "font-size: var(--font-sm)" in root_cause_action
        assert "padding: 0 var(--space-sm)" in root_cause_action
        review_search = _rule_body(
            ui_css, ".dsx-search-wrap input,\n.fp-search input,\n.reviews-search input"
        )
        assert "height: 100%" in review_search
        assert "padding-top: 0" in review_search
        assert "padding-bottom: 0" in review_search

        mapping = _rule_body(ui_css, ".pg-mapping-label,\n.pg-mapping-arrow")
        assert "align-items: center" in mapping
        assert "min-height: var(--control-height)" in mapping
        assert "padding-top: 0" in mapping

        docs_js = (DASHBOARD_DIR / "docs.js").read_text(encoding="utf-8")
        reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
        run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
        compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
        assert 'class="qym-control qym-search"' in docs_js
        assert reviews.count('class="qym-control qym-input"') >= 2
        assert run.count('class="qym-control qym-input"') >= 3
        assert compare.count('class="qym-control qym-input"') >= 3

    def test_shared_ui_behavior_is_accessible_and_exportable(self):
        assert UI_BEHAVIOR.exists(), "ui_components.js is the shared behavior layer"
        source = UI_BEHAVIOR.read_text(encoding="utf-8")
        for contract in (
            "marker.setAttribute('aria-describedby', tooltip.id);",
            "button.setAttribute('aria-haspopup', 'dialog');",
            "button.setAttribute('aria-expanded'",
            "directTabs(tablist)",
            "'ArrowLeft', 'ArrowRight', 'Home', 'End'",
            "new MutationObserver",
        ):
            assert contract in source, f"shared UI behavior lost: {contract}"

    def test_qym_component_rules_are_not_forked(self):
        """Canonical qym component CSS is defined in one file only."""
        component_rule = re.compile(
            r"\.qym-(?:control|input|select|search|dropdown[\w-]*|tabs[\w-]*|"
            r"segmented[\w-]*|badge[\w-]*|tag[\w-]*|chip[\w-]*|"
            r"icon-action|clear-action|stat-strip[\w-]*|"
            r"help[\w-]*|pagination[\w-]*)(?:[:.#\[][^,{]*)?\s*(?:,|\{)"
        )
        forks = []
        for path in DASHBOARD_DIR.glob("*.css"):
            if path == UI_COMPONENTS:
                continue
            if component_rule.search(path.read_text(encoding="utf-8")):
                forks.append(path.name)
        assert not forks, f"canonical qym component rules forked outside ui_components.css: {forks}"

    def test_auto_analysis_component_compatibility_uses_upstream_layer(self):
        """Analyzer adapters extend the upstream primitives without replacing them."""
        css = UI_COMPONENTS.read_text(encoding="utf-8")
        source = UI_BEHAVIOR.read_text(encoding="utf-8")

        for selector in (
            ".qym-dropdown > .qym-dropdown__trigger",
            ".qym-dropdown > .qym-dropdown__menu",
            ".qym-dropdown.is-open > .qym-dropdown__menu",
            ".qym-pagination--compact",
            ".qym-pagination--run",
            ".qym-icon-action--danger",
        ):
            assert selector in css

        for contract in (
            "function renderLegacyPagination",
            "function toggleStructuredDropdown",
            "function filterStructuredDropdown",
            "options.variant === 'run'",
            "options.variant === 'compact'",
            "document.querySelectorAll('.qym-dropdown.is-open')",
        ):
            assert contract in source

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
        assert "ui_components.css" in text and "ui_components.js" in text
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
