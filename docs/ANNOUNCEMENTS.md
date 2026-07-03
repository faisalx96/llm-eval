# qym — Release Announcements

Short, punchy, copy-paste-ready announcements for every qym release — one
title, one emoji feature list, nothing else. Inspired by No Man's Sky update
posts. Each block below is inside a code fence so it copies to X/Slack/email
exactly as written.

For the long-form archive, see [RELEASE_NOTES.md](RELEASE_NOTES.md).

## How to write one (for future releases)

1. Name the release after its **hero feature** (`qym v1.X: The <Thing>`).
2. 8–14 feature lines (the flagship release of an era may run longer), each:
   one emoji + 2–5 words. Feature names, not descriptions.
3. As short as possible, but **self-explanatory to a stranger** — someone who
   hasn't opened the app should know what the line means. Name the noun
   ("Dataset Version Names") and the action ("Pin a Production Version",
   not "Production Alias").
4. **User-facing only.** Internal work — design docs, CI rules, test repairs,
   refactors, build tooling — never gets a line. If a user can't see it or
   touch it, it doesn't appear; at most it dissolves silently into the
   closing bundle line.
5. Lead with the hero feature.
6. Bug fixes, QoL tweaks, speed-ups, and minor items don't get their own
   lines — bundle them into **one closing group line** (🔧/✨), e.g.
   "🔧 30+ Fixes & QoL Upgrades". One headline feature per line, one bundle
   line per release, always last.
7. If a line needs a comma, it's two lines (slashes for action sets are fine:
   "Stop / Trash / Restore Runs"). If it needs explaining, it's a docs link,
   not an announcement line.
8. Append the new block to the top of this file in the same commit as the
   version bump.

---

## v1.2 — DRAFT (unreleased, on main)

```
qym 1.2: The Library

🗃️ Dataset Page Overhaul
📊 Run Aggregates per Dataset
📖 Docs Inside the Dashboard
🏷️ Dataset Version Names
🔤 One Font System Everywhere
♿ Sharper Text Contrast
🧷 Metrics From Task Metadata
✅ Task Output Validation
🔧 UI Polish & Fixes
```

---

## v1.1 — June 2026

```
qym 1.1: The Dataset

🗂️ Native Dataset Management
📌 Dataset Versioning
🚦 Pin a Production Version
✏️ Draft & Publish Dataset Flow
🌳 Dataset Lineage Graph
🔀 Dataset Version Diff
🕘 Item Edit History
📜 Run History per Item
🔌 Bring Your Own LLM Keys
🔴 Live Runs Feed
🧪 Product Eval API
📦 Packaged Eval Presets
♻️ Un-approve / Un-reject Runs
⏹️ Stop In-Progress Evals
🧮 Filter by Edited Metrics
👮 Run Summaries for Admins
✨ Faster Pages & QoL Upgrades
```

---

## v1.0 — May 2026

```
qym 1.0: The Trace

🔭 Built-in Trace Viewer
🌊 Span Waterfall Timelines
💬 LLM Calls as Chat Bubbles
🧠 See Model Reasoning
🚨 Auto-Jump to Errors
🔗 Shareable Trace Links
📦 OTEL Tracing for 15+ Providers
🤖 AI Evaluator Playground
💡 AI-Suggested Solutions
✅ Corrections Review Queue
⚖️ 7 Built-in LLM Judges
🧮 Sweep Comparisons
📊 Rebuilt Charts View
🏷️ Run Version Tracking
📉 Model Stats Page
🏢 Per-Project Access Control
🔑 Personal API Keys Page
🗑️ Stop / Trash / Restore Runs
⌨️ New qym CLI
📄 Share Runs as HTML
🧭 Redesigned Navigation
🔧 100+ Fixes & QoL Upgrades
```

---

## v0.9 — March 2026

```
qym 0.9: The Analyst

🧠 AI Root-Cause Analysis
📚 AI Learns Your Corrections
🏷️ Root-Cause Categories
🔬 Redesigned Run Page
✍️ Editable Metric Scores
▶️ Resume Interrupted Runs
🔁 Auto-Retry Failed Items
🌿 Runs Record Git Version
⚖️ LLM-as-Judge Metric
🧩 Breakdowns by Metadata
🎛️ Filters in Compare View
💬 Per-Item Feedback Notes
🔧 Charts & Dashboard QoL
```

---

## v0.7 — December 2025

```
qym 0.7: The Platform

🏛️ Deployed Team Platform
🗄️ Central Run Database
📡 Runs Stream Live
👥 User Accounts
🛡️ Admin Console
🔑 API Key Auth
🐳 One-Command Docker Deploy
🎨 New Name: قيِّم
🔧 Setup & Stability Fixes
```

---

## v0.6 — December 2025

```
qym 0.6: Sharper Tools

📁 Evaluate From CSV Files
🧮 New Built-in Metrics
🧵 Faster Parallel Evals
🔎 Trace IDs Everywhere
🪄 Auto-Detects Langfuse Project
🔧 Error Handling Overhaul
```

---

## v0.4 — November 2025

```
llm-eval 0.4: Mission Control

🤖 Evaluate Multiple Models at Once
🖥️ Live Terminal Dashboard
🕘 Browse Past Runs
📈 Charts View
⚖️ Compare Two Runs
🔀 Parallel Evaluations
🏷️ Auto Run Naming
📤 Excel Export
✨ Speed & Dashboard QoL
```

---

## v0.2 — September 2025

```
llm-eval 0.2: First Light

🚀 Run Evals From Python
🧩 Custom Python Metrics
🔗 LangChain Support
📊 Live Results Table
🌐 Web Results Report
⏱️ Latency at a Glance
🌗 Light & Dark Themes
📤 CSV Export
🔌 Langfuse Tracing
📦 Offline / Air-Gapped Install
🔧 Assorted Fixes & Polish
```
