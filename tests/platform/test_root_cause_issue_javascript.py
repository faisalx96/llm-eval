"""Execute production dashboard functions with Node, including real events."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "packages/platform/qym_platform/_static/dashboard"
)


def _function(page: str, name: str) -> str:
    source = (DASHBOARD / f"{page}.html").read_text()
    start = re.search(rf"^      (?:async )?function {name}\(", source, re.MULTILINE)
    assert start, name
    end = re.search(r"^      }$", source[start.start() :], re.MULTILINE)
    assert end, name
    return source[start.start() : start.start() + end.end()]


def _run_javascript(script: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for dashboard behavior tests")
    result = subprocess.run(
        [node],
        input=(
            "const assert = require('node:assert/strict');\n"
            "async function test() {\n" + script + "\n}\n"
            "test().catch(error => { console.error(error); process.exitCode = 1; });"
        ),
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("page", ["run", "compare"])
def test_item_level_chart_preserves_all_issues(page: str) -> None:
    functions = "\n".join(
        _function(page, name)
        for name in (
            "rootCauseCategories",
            "rootCauseIssues",
            "getRowRootCauseAnalyses",
        )
    )
    _run_javascript(
        functions
        + """
        const state = { allMetrics: ['accuracy'] };
        const MAX_ROOT_CAUSE_CATEGORIES = 3;
        const isRepeatAggregateView = () => false;
        const issues = [
          {category: 'Agent', subcategory: 'Lookup', finding: 'First finding'},
          {category: 'Agent', subcategory: 'Filter', finding: 'Second finding'},
        ];
        const row = {item_metadata: {
          root_cause_issues: issues, root_causes: ['Agent'],
          root_cause: 'Agent', root_cause_detail: 'Lookup', root_cause_note: 'First finding',
        }};
        const chartIssues = getRowRootCauseAnalyses(row, 'all').flatMap(rootCauseIssues);
        assert.equal(chartIssues.length, 2);
        assert.deepEqual(chartIssues.map(issue => issue.subcategory), ['Lookup', 'Filter']);
        assert.deepEqual(chartIssues.map(issue => issue.finding), ['First finding', 'Second finding']);
        row.item_metadata.root_cause_issues = [];
        assert.deepEqual(getRowRootCauseAnalyses(row, 'all'), []);
        delete row.item_metadata.root_cause_issues;
        row.item_metadata.root_causes = ['Agent', 'Evaluator'];
        const legacy = getRowRootCauseAnalyses(row, 'all').flatMap(rootCauseIssues);
        assert.deepEqual(legacy.map(issue => issue.finding), ['First finding', 'First finding']);
    """
    )


@pytest.mark.parametrize("scope_kind", ["metric", "pass", "legacy", "new"])
def test_compare_displays_and_saves_the_same_scope(scope_kind: str) -> None:
    functions = "\n".join(
        _function("compare", name)
        for name in (
            "rootCauseCategories",
            "rootCauseIssues",
            "rootCauseIssuePatch",
            "passRefBase",
            "compareRootCauseScope",
            "compareExecutionErrorInfo",
            "renderCompareOutputGroup",
            "wireRootCauseHandlers",
            "saveRootCauseIssues",
        )
    )
    _run_javascript(
        "const window = {};\n"
        + (DASHBOARD / "metrics.js").read_text()
        + "\n"
        + functions
        + f"\nconst scopeKind = '{scope_kind}';\n"
        + """
        const PASS_REF_SEP = '::pass';
        const MAX_ROOT_CAUSE_CATEGORIES = 3;
        const IS_COMPARE_EXPORT = false;
        const issues = finding => [{category: 'Agent', subcategory: 'Lookup', finding}];
        const row = {
          item_id: 'raw-item', status: 'completed', metric_values: [0, 0],
          item_metadata: {
            root_cause_issues: issues('Stale summary'), root_cause_metric_name: 'accuracy',
            metric_analyses: {
              accuracy: {root_cause_issues: issues('Accuracy finding')},
              style: {root_cause_issues: issues('Style finding')},
            },
          },
          pass_metric_analyses: {
            style: [
              {root_cause_issues: issues('First pass finding')},
              {root_cause_issues: issues('Second pass finding')},
            ],
          },
        };
        const expectedFinding = scopeKind === 'pass' ? 'Second pass finding'
          : scopeKind === 'legacy' ? 'Legacy finding' : 'Style finding';
        if (scopeKind === 'legacy') row.item_metadata = {root_cause_issues: issues('Legacy finding')};
        if (scopeKind === 'new') row.item_metadata = {};
        const state = {
          selectedItemsMetric: 'style', allMetrics: ['accuracy', 'style'],
          metricIsBoolean: {}, metricThresholds: {}, visibleMetricMetaFields: {},
          rootCauseValues: [], runs: [{
            run: {file_path: scopeKind === 'pass' ? 'run-1::pass2' : 'run-1'},
            snapshot: {metric_names: ['accuracy', 'style'], rows: [row]},
          }],
        };
        const COLORS = ['green'];
        const OPEN_LINK_ICON = '', COPY_ICON = '', SAVE_ICON = '', CLOSE_ICON = '', EDIT_ICON = '';
        const escapeAttr = value => String(value || '');
        const escapeHtml = escapeAttr, renderMarkdownSafe = escapeAttr, apiUrl = escapeAttr;
        const rootCauseColor = () => 'green';
        const buildLangfuseTraceUrl = () => '';
        const buildLangfuseTraceUrlFromRun = () => '';
        const html = renderCompareOutputGroup('compare-item', [row]);
        if (scopeKind !== 'new') assert.ok(html.includes(expectedFinding), html);
        assert.ok(!html.includes('Stale summary'));
        assert.ok(!html.includes('Accuracy finding'));
        const metricName = scopeKind === 'legacy' ? '' : 'style';
        assert.ok(html.includes('data-rc-issues-metric="' + metricName + '"'));

        const trigger = new EventTarget();
        trigger.dataset = {rcIssuesItem: 'compare-item', rcIssuesRunIdx: '0', rcIssuesMetric: metricName};
        let opened;
        const showRootCauseIssuesEditor = (...args) => { opened = args; };
        wireRootCauseHandlers({querySelectorAll: selector => selector === '[data-rc-issues-item]' ? [trigger] : []});
        trigger.dispatchEvent(new Event('click'));
        assert.deepEqual(opened, ['compare-item', 0, metricName]);

        // Changing the page selection must not retarget an already open editor.
        state.selectedItemsMetric = 'accuracy';
        let request;
        const fetch = async (_url, options) => {
          request = JSON.parse(options.body);
          return {ok: true, json: async () => ({ok: true})};
        };
        const findRowByCompareId = rows => rows[0];
        const buildCategoryDropdowns = () => {};
        const renderItems = () => {};
        const edited = issues('Reviewed finding');
        assert.equal(await saveRootCauseIssues('compare-item', 0, edited, metricName), true);
        assert.equal(request.run_id, 'run-1');
        assert.equal(request.item_id, 'raw-item');
        assert.equal(request.metric_name, metricName || undefined);
        assert.equal(request.pass_number, scopeKind === 'pass' ? 2 : undefined);
        assert.deepEqual(request.root_cause_issues, edited);
        const updated = compareRootCauseScope(row, 0, metricName);
        assert.deepEqual(updated.analysis.root_cause_issues, edited);
        if (scopeKind === 'metric' || scopeKind === 'pass') {
          assert.equal(row.item_metadata.metric_analyses.accuracy.root_cause_issues[0].finding, 'Accuracy finding');
          assert.equal(row.item_metadata.root_cause_issues[0].finding, 'Stale summary');
        }
        if (scopeKind === 'pass') {
          assert.equal(row.pass_metric_analyses.style[0].root_cause_issues[0].finding, 'First pass finding');
        }
    """
    )


@pytest.mark.parametrize("page", ["run", "compare"])
@pytest.mark.parametrize("failure", ["false", "reject"])
def test_issue_editor_restores_save_button_and_allows_retry(
    page: str, failure: str
) -> None:
    editor = _function(page, "showRootCauseIssuesEditor")
    start = editor.index("editor.querySelector('[data-save-issues]').addEventListener(")
    end = editor.index("\n        });", start) + len("\n        });")
    handler = editor[start:end]
    _run_javascript(
        f"const failure = '{failure}';\n"
        + """
        const button = new EventTarget();
        const editor = {querySelector: () => button};
        const classes = new Set();
        const status = {textContent: '', classList: {
          add: value => classes.add(value), remove: value => classes.delete(value),
        }};
        const issues = [{category: 'Agent', subcategory: 'Lookup', finding: 'Finding'}];
        const itemId = 'item-1', metricName = 'accuracy', runIdx = 0;
        const readRows = () => {};
        let closed = false;
        const cleanup = () => { closed = true; };
        let resolveSave, rejectSave;
        const saveRootCauseIssues = () => new Promise((resolve, reject) => {
          resolveSave = resolve; rejectSave = reject;
        });
    """
        + handler
        + """
        button.dispatchEvent(new Event('click'));
        assert.equal(button.disabled, true);
        if (failure === 'reject') rejectSave(new Error('Connection lost'));
        else resolveSave(false);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(button.disabled, false);
        assert.equal(closed, false);
        assert.equal(status.textContent, 'Could not save these issues.');
        assert.ok(classes.has('is-error'));
        button.dispatchEvent(new Event('click'));
        assert.equal(button.disabled, true);
        resolveSave(true);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(button.disabled, false);
        assert.equal(closed, true);
        assert.ok(!classes.has('is-error'));
    """
    )
