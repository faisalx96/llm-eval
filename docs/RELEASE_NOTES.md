# 🚀 qym v0.8.4 — Release Notes

**📅 December 2025 – February 2026**

---

## 📢 Big News

**qym is now a fully deployed platform!** Evaluations are no longer confined to local machines — everything runs through a centralized web dashboard accessible to the entire organization. Run evaluations from the SDK, and results stream live to the platform where teams can review, compare, and approve them together. The local dashboard has been retired in favor of this new shared experience.

---

## 🌐 Platform

- 🆕 Centralized web platform for managing and collaborating on evaluations in one place
- 📡 Real-time streaming — results flow in live as evaluations run
- 🔄 Structured approval workflow with clear status lifecycle:
  - 🔵 RUNNING → 🟣 COMPLETED / 🔴 FAILED → 🟡 SUBMITTED → 🟢 APPROVED / ⛔ REJECTED
- 🔐 Role-based visibility:
  - 👨‍💼 **Managers** see all evaluations across the team
  - 🏢 **GMs & VPs** see only **approved** evaluations — leadership always views validated results
- 🏗️ Organization management — define **Sectors → Departments → Teams** from a full admin panel with user management, role assignment, and platform settings
- 🔑 Profile page — securely generate and manage API keys

---

## 📋 Runs View

- 📁 Smart run grouping — identical configurations are grouped with collapsible sections and a **"Compare All"** shortcut
- 👤 Owner column with color-coded avatars — see who ran what at a glance
- 🏷️ Readable run names instead of cryptic IDs
- ⋯ Role-aware action menu — Submit, Approve, Reject, or Delete in one click
- 📊 Live progress column — real-time completion percentages and item counts
- 🔗 Langfuse integration — one-click jump to the trace
- 🔎 Filter status bar — active filters for task, dataset, model, status, and search always visible

---

## 📊 Compare View

- 🛠️ Rebuilt from the ground up with 15+ new capabilities
- 🔍 Instant search across all items
- 🏷️ Metadata filters — slice by complexity, domain, or any custom field
- 📈 Score range filters — greater-than / less-than on any metric
- 📊 Interactive charts — click bar segments to filter the view
- 📥 One-click CSV export with active filters applied
- 🧩 Metadata breakdown cards — color-coded by complexity (🟢 easy → 🔴 hard → 🟣 expert) and domain, showing scores and latency
- 🏷️ Per-item metadata badges — complexity and domain displayed as styled badges on each item for quick visual context
- 📋 Per-item metadata display with configurable field selector
- 📝 Markdown rendering for inputs, outputs, and expected answers
- 📋 Hover-to-copy on any field
- 🏆 Winner badges — gold star on the best-performing run per item
- 📐 Aligned outputs — responses height-matched across runs
- ✅ Pass/Fail badges — each item shows a clear green Pass or red Fail indicator based on the selected metric's threshold
- 🔬 Root cause analysis — assign root causes to underperforming items directly from the compare view, with built-in categories (Hallucination, Reasoning Error, Context Missing, Knowledge Gap, and more) or custom values
- 📊 Root cause breakdown — aggregate cards show root cause distribution across runs, with a dedicated filter to drill down by cause

---

## 🖥️ Single Run View

- 🎨 Completely redesigned — cleaner typography, better spacing, cohesive visual experience

---

## 📊 Models View

- 📉 Consistency and Reliability show "N/A" when data is insufficient instead of a misleading "0%"

---

## ⚡ Performance

- 🚀 Parallel metric execution — run multiple metrics simultaneously with `max_metric_concurrency`
- 🔔 Smart blocking detection — warns when code accidentally slows down the event loop, with fix suggestions right in the terminal

---

## 🛠️ SDK Enhancements

- 🔄 Zero-config platform streaming — set an API key and evaluations stream automatically
- 🏷️ `--task-name` flag — label evaluations with a custom name
- ⏱️ Accurate TUI timing — shows pure task duration, excluding metric overhead
- 💬 Friendlier error messages — clear guidance on file parsing issues
- 📁 Smarter file naming — results use the custom run name without redundant timestamps

---

## ⚠️ Breaking Changes

- 🖥️ `qym dashboard` now opens the platform instead of a local server
- 📄 Confluence publishing has been retired — use the platform or CSV export

---

Happy evaluating! 🎉
