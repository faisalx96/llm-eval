# 🚀 qym — Since v0.9.0 Summary

**📅 March 2026**

---

**Coverage:** this summary groups everything shipped after commit `e2fda02` through `548e15a`.

## 🌟 Major Highlights

- 🔁 **Repeat runs & pass@k** *(July 2026)* — `samples=8` evaluates every item 8× as ONE run with Pass@k/Pass^k/Consistency/Reliability, confidence intervals, per-pass storage end-to-end, an accuracy-vs-k curve, and repeat-run UI (×k pills, pass expansion, dot strips); replaces the duplicate-spec duct-tape and the timestamp grouping heuristic
- 🤖 **AI Evaluator Playground** — preview, test, and run AI analysis with editable prompts, variable mapping, additional instructions, reusable category/detail catalogs, and visible few-shot examples before launching analysis
- 🧠 **Structured analysis workflow** — root-cause analysis expanded from a single label into **category + detail + note + solution + solution note**, with inline editing across run and compare views
- ✅ **Corrections review system** — a dedicated review queue now supports approval states, inline edits, bulk moderation, immutable revision history, and approved-example curation for the analyzer
- 📊 **Dashboard redesign for scale** — charts now use per-task cards with dataset tabs and run/version/model grouping, while the runs dashboard adds pagination, sticky tables, metric visibility, and stronger version filtering
- ⚖️ **LLM-as-judge metrics** — 7 built-in judges (relevance, faithfulness, correctness, hallucination, toxicity, conciseness, tool calling) plus a `create_judge()` factory for custom binary or multi-level judges, with structured results (score + label + explanation) stored in the platform
- 🖥️ **Agent-native CLI + sturdier SDK runs** — the new Typer CLI adds noun-verb commands and JSON output, while the SDK adds version capture, retries, STOPPED/PENDING statuses, OTEL tracing, and stable CSV item identity
- 🔭 **Trace Viewer** — an embedded per-item trace viewer with span tree visualization, LLM message reconstruction, reasoning display, error path highlighting, framework noise collapsing, and full OTEL auto-instrumentation across 15+ LLM providers and 6+ frameworks

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
- Interactive **category chip selectors** on metadata breakdown cards for quick filtering by complexity, domain, or custom metadata fields

## 🔭 Trace Viewer

- Embedded **per-item trace viewer** in run and compare pages showing the full span tree for each evaluation item
- Typed **SVG icon badges** for each span kind (LLM, TOOL, AGENT, CHAIN, EVALUATOR, RETRIEVER, EMBED) with color-coded tree connectors
- **Waterfall duration bars** showing relative timeline and duration, with header chips for span count, total duration, tokens, cost, and errors
- **Tabbed detail panel** with Messages (LLM chat bubbles), Response (model/tokens/cost), Input/Output (tool args/results), Metrics, Scores, and Raw attributes — tabs shown dynamically per span type
- **"Show Thinking" expandable sections** on LLM assistant messages for reasoning content (Anthropic, DeepSeek, etc.)
- **Red L-shaped error connectors** and auto-expand to first error span so users land on problems immediately
- **Framework noise auto-collapse** — LangChain/LangGraph internal wrapper spans (ChannelRead, RunnableLambda, routing) are collapsed while preserving meaningful graph nodes
- **Resizable panels**, real-time span search with keyboard navigation (j/k, arrows, `/`), CodeMirror JSON highlighting, modal expand views, and shareable `?trace=itemId` URLs
- Copy buttons for error details (type, message, stack trace) and all raw span data

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
- **Auto-instrumentation** (`qym[otel]`) captures every LLM call, tool invocation, and agent step across 15+ providers (OpenAI, Anthropic, Google, Bedrock, Cohere, Mistral, Groq, Ollama, etc.) and 6+ frameworks (LangChain, LangGraph, LlamaIndex, CrewAI, Haystack, OpenAI Agents) plus vector DBs (Pinecone, Chroma, Qdrant, Weaviate, Milvus)
- `QymSpanProcessor` streams spans to the platform with **deduplication** (no double-tracing when framework + provider instrumentors both fire) and **noise filtering** (connect/dns/tls spans dropped)
- CSV ingest and compare alignment now use deterministic fingerprints when explicit stable item IDs are missing, improving imported-run alignment

## 🗃️ Data & Workflow

- New migrations persist solution fields, root-cause detail fields, correction approval state, root-cause revision history, run created-at indexing, `PENDING` / `STOPPED` statuses, metric `label` / `explanation` columns, **spans table** (`0011`), and **span links** (`0012`)
- Platform ingest and event handling now preserve retry metadata, metric labels/explanations, correctly dispatch final status payloads, and handle `span_completed` events with savepoint transactions for safety
