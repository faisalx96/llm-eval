"""Browser contracts for the canonical dashboard component bundle.

The fixture is served directly from the repository, so these tests never need
authentication, a database, or a running FastAPI application.
"""

from __future__ import annotations

import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest


REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = "/tests/platform/fixtures/components_contract.html"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture(scope="module")
def component_fixture_server(chromium_browser: object) -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(REPO))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{FIXTURE_PATH}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture(scope="module")
def chromium_browser() -> Iterator[object]:
    sync_api = pytest.importorskip(
        "playwright.sync_api",
        reason="Install packages/platform[test] and run playwright install chromium.",
    )
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                yield browser
            finally:
                browser.close()
    except sync_api.Error as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Chromium is unavailable ({exc}). Run: playwright install chromium")


@pytest.fixture
def component_page(chromium_browser: object, component_fixture_server: str) -> Iterator[object]:
    context = chromium_browser.new_context(reduced_motion="reduce")
    page = context.new_page()
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(component_fixture_server)
    page.wait_for_function(
        "() => Boolean(window.QymUIComponents && document.querySelector('.qym-segmented--ready'))"
    )
    try:
        yield page
    finally:
        context.close()
        assert not console_errors, "Browser console errors: " + "; ".join(console_errors)


pytestmark = pytest.mark.browser


def test_tabs_roving_disabled_and_overflow(component_page: object) -> None:
    tabs = component_page.locator("#tabs .qym-tabs__tab")
    tabs.nth(0).focus()
    component_page.keyboard.press("ArrowRight")
    assert tabs.nth(1).get_attribute("aria-selected") == "true"
    assert tabs.nth(1).get_attribute("tabindex") == "0"

    component_page.keyboard.press("ArrowRight")
    assert tabs.nth(0).get_attribute("aria-selected") == "true"
    assert tabs.nth(2).get_attribute("aria-selected") == "false"
    assert tabs.nth(2).is_disabled()

    component_page.locator("#overflow-tabs .qym-tabs__tab").nth(0).evaluate(
        """tab => {
          tab.focus();
          tab.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'End', bubbles: true, cancelable: true,
          }));
        }"""
    )
    assert component_page.locator("#overflow-tabs .qym-tabs__tab").nth(4).get_attribute("aria-selected") == "true"
    assert component_page.locator(".fixture-overflow").evaluate("el => el.scrollWidth > el.clientWidth")
    component_page.wait_for_function("() => document.querySelector('.fixture-overflow').scrollLeft > 0")


def test_segmented_control_syncs_aria_and_disables_motion(component_page: object) -> None:
    options = component_page.locator("#segmented .qym-segmented__option")
    options.nth(1).click()
    assert options.nth(1).get_attribute("aria-pressed") == "true"
    assert options.nth(0).get_attribute("aria-pressed") == "false"
    assert component_page.locator("#segmented").evaluate(
        "el => getComputedStyle(el, '::before').transitionDuration"
    ) == "0s"


def test_dropdown_search_actions_escape_and_focus_restoration(component_page: object) -> None:
    trigger = component_page.locator("#dropdown .qym-dropdown__trigger")
    trigger.click()
    search = component_page.locator("#dropdown .qym-dropdown__search")
    component_page.wait_for_function("document.activeElement === document.querySelector('#dropdown .qym-dropdown__search')")
    assert search.evaluate("el => document.activeElement === el")
    assert component_page.locator("#dropdown .qym-dropdown__menu").get_attribute("role") == "group"

    search.fill("latency")
    options = component_page.locator("#dropdown .qym-dropdown__option")
    assert options.nth(0).evaluate("el => el.hidden")
    assert not options.nth(1).evaluate("el => el.hidden")

    search.fill("")
    options.nth(1).locator("input").check()
    assert options.nth(1).locator("input").is_checked()

    search.focus()
    component_page.keyboard.press("Escape")
    assert not component_page.locator("#dropdown").evaluate("el => el.classList.contains('is-open')")
    assert trigger.evaluate("el => document.activeElement === el")


def test_help_marker_has_aria_and_escape_unpins(component_page: object) -> None:
    marker = component_page.locator("#help")
    tooltip_id = marker.get_attribute("aria-describedby")
    assert tooltip_id
    marker.click()
    assert marker.evaluate("el => el.classList.contains('is-open')")
    assert marker.get_attribute("aria-expanded") == "true"
    assert component_page.locator(".qym-help-tooltip-portal.is-open").inner_text() == "Coverage is the share of targets with a saved diagnosis."
    component_page.keyboard.press("Escape")
    assert not marker.evaluate("el => el.classList.contains('is-open')")
    assert marker.get_attribute("aria-expanded") == "false"


def test_pagination_supports_navigation_direct_entry_and_page_size(component_page: object) -> None:
    component_page.locator("#pagination [data-qym-page='next']").click()
    assert component_page.locator("#pagination-output").inner_text() == "page:2"

    component_page.evaluate("window.renderFixturePagination(2)")
    component_page.locator("#pagination-scroll-host").evaluate("el => { el.scrollTop = 100; }")
    component_page.locator("#pagination [data-qym-page='next']").click()
    assert component_page.locator("#pagination-output").inner_text() == "page:3"
    assert component_page.locator("#pagination-scroll-host").evaluate("el => el.scrollTop") == 0

    page_input = component_page.locator("#pagination .qym-pagination__input")
    page_input.fill("3.7")
    page_input.evaluate("el => el.blur()")
    assert component_page.locator("#pagination-output").inner_text() == "page:3"

    component_page.locator("#pagination .qym-pagination__size").select_option("50")
    assert component_page.locator("#pagination-output").inner_text() == "size:50"


def test_scroll_mirror_stays_synchronized(component_page: object) -> None:
    component_page.wait_for_function("() => !document.getElementById('scroll-mirror').hidden")
    component_page.locator("#scroll-mirror").focus()
    component_page.keyboard.press("End")
    component_page.wait_for_function(
        "() => document.getElementById('scroll-target').scrollLeft > 0"
    )

    component_page.locator("#scroll-target").evaluate(
        "el => { el.scrollLeft = 120; el.dispatchEvent(new Event('scroll')); }"
    )
    component_page.wait_for_function(
        "() => document.getElementById('scroll-mirror').getAttribute('aria-valuenow') === '120'"
    )


def test_form_and_feedback_state_recipes_are_semantic(component_page: object) -> None:
    checkbox = component_page.locator("#fixture-checkbox")
    checkbox.check()
    assert checkbox.is_checked()

    switch = component_page.locator("#fixture-switch")
    assert switch.get_attribute("role") == "switch"
    component_page.locator("label[for='fixture-switch']").click()
    assert switch.is_checked()

    assert component_page.locator("#fixture-alert").get_attribute("role") == "status"
    assert component_page.locator("#fixture-empty .qym-empty-state__title").inner_text() == "No saved views"
    assert component_page.locator("#fixture-loading").get_attribute("role") == "status"
    assert component_page.locator("#fixture-saved").inner_text() == "Saved"


def test_fixture_has_no_serious_or_critical_axe_violations(component_page: object) -> None:
    axe_module = pytest.importorskip(
        "axe_playwright_python.sync_playwright",
        reason="Install packages/platform[test] to run axe component checks.",
    )
    results = axe_module.Axe().run(component_page)
    violations = [
        violation
        for violation in results.response["violations"]
        if violation.get("impact") in {"serious", "critical"}
    ]
    assert not violations, "Axe violations: " + ", ".join(
        f"{violation['id']} ({violation.get('impact')}): "
        + ", ".join(" ".join(node.get("target", [])) for node in violation.get("nodes", []))
        for violation in violations
    )


def test_refresh_is_idempotent_for_dynamic_roots(component_page: object) -> None:
    component_page.locator("#dynamic-root").evaluate(
        """root => {
          root.innerHTML = '<button class="qym-help-marker" type="button">i<span class="qym-help-tooltip">Dynamic help</span></button>';
        }"""
    )
    component_page.wait_for_function(
        "() => Boolean(document.querySelector('#dynamic-root .qym-help-marker[aria-describedby]'))"
    )
    described_by = component_page.locator("#dynamic-root .qym-help-marker").get_attribute(
        "aria-describedby"
    )
    component_page.locator("#dynamic-root").evaluate(
        "root => { window.QymUIComponents.refresh(root); window.QymUIComponents.refresh(root); }"
    )
    assert described_by.startswith("qym-help-tooltip-")
    assert (
        component_page.locator("#dynamic-root .qym-help-marker").get_attribute(
            "aria-describedby"
        )
        == described_by
    )
