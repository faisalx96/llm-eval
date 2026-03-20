# 🚀 qym — Since v0.9.0 Summary

**📅 March 2026**

---

**Coverage:** this summary groups everything shipped after commit `e2fda02` through `cae762d`.

## 🌟 Major Highlights

- 🤖 **AI Evaluator Playground** — preview, test, and run AI analysis with editable prompts, variable mapping, additional instructions, reusable category/detail catalogs, and visible few-shot examples before launching analysis
- 🧠 **Structured analysis workflow** — root-cause analysis expanded from a single label into **category + detail + note + solution + solution note**, with inline editing across run and compare views
- ✅ **Corrections review system** — a dedicated review queue now supports approval states, inline edits, bulk moderation, immutable revision history, and approved-example curation for the analyzer
- 📊 **Dashboard redesign for scale** — charts now use per-task cards with dataset tabs and run/version/model grouping, while the runs dashboard adds pagination, sticky tables, metric visibility, and stronger version filtering
- ⚖️ **LLM-as-judge metrics** — 7 built-in judges (relevance, faithfulness, correctness, hallucination, toxicity, conciseness, tool calling) plus a `create_judge()` factory for custom binary or multi-level judges, with structured results (score + label + explanation) stored in the platform
- 🖥️ **Agent-native CLI + sturdier SDK runs** — the new Typer CLI adds noun-verb commands and JSON output, while the SDK adds version capture, retries, STOPPED/PENDING statuses, OTEL tracing, and stable CSV item identity

## 🤖 Analysis & Review

- AI analysis now supports `root_cause_detail`, `root_cause_note`, `solution`, and `solution_note`, and preserves both AI and human versions in review records
- Approved corrections are the only examples reused by the analyzer; stale approvals now promote the active candidate for that run item
- Root-cause catalogs now merge built-in defaults, current-run values, approved task history, and category→detail mappings
- Reviews preserve input / expected / output / score snapshots and append-only revision timelines, while newer approved examples supersede older ones for the same item
- Approval filtering in run and compare views is now simplified to `All`, `Approved`, and `Not Approved`

## 🖥️ Run & Compare Views

- Run pages can be exported as self-contained HTML, reopened offline, edited locally, and re-downloaded with annotations baked in
- Compare and run views now show separate badges for root-cause detail, root-cause category, and solution, plus solution Sankey visualizations and detail-aware summaries
- Domain drill-down now supports AND matching plus an exclusive mode for sole-domain items, and breakdown cards stay aligned with current item filters
- Metric cards became interactive drill-down controls, and long analysis badges now wrap cleanly instead of breaking the layout
- Header user menus now expose Profile/Admin shortcuts across run, compare, and reviews pages

## 📊 Dashboard & Charts

- The runs dashboard now paginates API fetches, renders the first page immediately, and merges background pages for faster large-workspace loads
- Charts render one card per task with dataset tabs and inline `Run / Version / Model` grouping, including collapsible aggregate rows and latency-last tables
- Version metadata is visible throughout the dashboard via a Version column, search/filter/sort controls, and version leaderboards
- Metric visibility is user-configurable, sticky first columns keep wide run tables usable, and multi-select controls now use consistent `Select All / None` behavior

## 🧰 SDK, CLI & Platform

- The CLI now provides `qym run`, `qym analyze`, `qym metric`, and `qym config` command groups, `--json` output, legacy command rewriting, and `qym run tasks`
- Platform task listings can hide configured tasks from both the CLI and dashboard
- The SDK auto-detects git branch/commit, defaults timeout to `300s`, retries failed items up to `2` times with exponential backoff + jitter, and streams `retry_count` metadata to the platform
- LLM judge metrics use `JudgeConfig` with env var cascade, clear missing-config errors, and per-judge model/key/URL overrides for mixed-provider setups
- OpenTelemetry/OpenLLMetry support can link SDK spans to Langfuse traces and emit tool-call spans
- CSV ingest and compare alignment now use deterministic fingerprints when explicit stable item IDs are missing, improving imported-run alignment

## 🗃️ Data & Workflow

- New migrations persist solution fields, root-cause detail fields, correction approval state, root-cause revision history, run created-at indexing, `PENDING` / `STOPPED` statuses, and metric `label` / `explanation` columns
- Platform ingest and event handling now preserve retry metadata, metric labels/explanations, and correctly dispatch final status payloads
