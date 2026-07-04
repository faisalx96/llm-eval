# قيِّم — Evaluation Features: Full Proposal (v1)

> Companion docs: interactive screens → `tmp/mockups/eval-features-mock.html` · styled version → `tmp/mockups/eval-proposal.html`

Nine capabilities, grouped so each one copies a pattern that already exists in qym. Nothing here is green-field — most is wiring primitives already shipped (`group_analysis` pass@k, `create_judge`, `run_item_attempts`, Datasets, Auto Root Cause, Reviews) into first-class, named features.

---

## The mental model

Every feature is one of three shapes. This is the rule that keeps the UI/SDK split clean:

| Shape | Existing example | New features |
|---|---|---|
| ① **UI feature over runs** — select → model panel → instructions → preview → run | Auto Root Cause | Arena + ELO, Human voting |
| ② **UI artifact, referenced by code** — versioned, `production` alias | Datasets | Unit-test suites |
| ③ **SDK run shape** — a config knob / item shape | `EvaluatorConfig` | Repeats, Jury, Multi-turn, Follow-ups, Stress, Stats |

**Badge key:** `UI` = built in the platform, no code · `SDK` = called from code · `UI+SDK` = authored in UI, referenced from code.

---

## Summary matrix — everything at a glance

| # | Feature | Lives | You invoke it by | Modeled on | Effort | Phase |
|---|---|---|---|---|---|---|
| 1 | Repeats / pass@k | `SDK` | `samples=8, reduce=[...]` | group_analysis | S | 1 |
| 2 | Jury metric (panel of judges) | `UI+SDK` | `jury("q", panel=[...])` | create_judge | S | 1 |
| 3 | Unit testing | `UI+SDK` | `test_suite("name")` | Datasets | M | 2 |
| 4 | Arena + ELO leaderboard | `UI` | select runs → judge panel | Auto Root Cause | M | 3 |
| 5 | Human voting | `UI` | select runs → blind A/B | Auto Root Cause + Reviews | M | 3 |
| 6 | Multi-turn / chat-history | `SDK` | `mode="conversation"` | new item shape | L | 4 |
| 7 | Follow-up questions | `SDK` | `followup_robustness(...)` | layer on #6 | S | 4 |
| 8 | Stress testing (conc. sweep) | `SDK` | `.stress(concurrency=[...])` | max_concurrency | M | 4 |
| 9 | Statistics (CIs, significance) | `SDK` | automatic on every number | stats helper | M | 0→all |

---

## The foundation — build once, the rest are thin wrappers

Four shared pieces sit under everything. Phase 0 builds them; features 1–9 plug in.

| Piece | What | Reuses |
|---|---|---|
| **Per-item samples** | Keep all k attempts per item, not just the last (today `_execute_task` discards them) | `run_item_attempts` table (already exists) |
| **Scorer + Reducer registry** | Generalize "metric" into kinds {code · pointwise · jury · pairwise · rubric · unit-test · human} + reducers {mean · pass@k · pass^k · majority · …} | metric registry + the dead `MetricResult.kind` enum |
| **Stats module** | `bootstrap_ci`, `mcnemar`, paired bootstrap, `bradley_terry_elo`, `krippendorff_alpha` | new, ~1 file, numpy/sklearn |
| **Comparison + suite tables** | `arena_matches` (votes) and `test_suites` (assertions) | modeled on Reviews + Datasets tables |

Also: centralize score-parsing — it is currently duplicated in 4 files (`results.py`, `group_analysis.py`, `run_discovery.py`, `checkpoint.py`).

---

## 1 · Repeats / pass@k — `SDK`

Run each item **k times as one logical run**; collapse the k tries with a reducer. Replaces today's "launch k runs and hand-group them."

**Reuses:** `group_analysis` (already computes pass@k, pass^k, consistency, reliability) as reducers + `run_item_attempts` for storage.

```python
result = Evaluator(
    task, dataset, metrics=["correctness"],
    samples=8,                                        # draw 8 tries / item
    reduce=["pass@1", "pass@3", "pass^3", "majority"],  # collapse 8 → 1
).run()

result.metrics["pass@3"]   # 0.89  "works at least once?"  (+ 95% CI)
result.metrics["pass^3"]   # 0.43  "works every time?" (reliability)
```

pass@k = unbiased Codex estimator `1 − C(n−c,k)/C(n,k)`. pass^k = all-k-pass. They diverge ~3× — show both. → mock tab "Repeats / pass@k".

### 1.1 · Settled design (decided 2026-06-21)

**Defaults (Faisal's simplification):** `samples=8` alone auto-reports `mean` / `any@8` / `all@8` — zero config. `reduce=["pass@3", ...]` with k < n is the **opt-in** for power users; that's the only place the unbiased estimator is used, and it also powers the **accuracy-vs-k report**: one run of n samples yields pass@k for *every* k ≤ n (the whole curve from one execution, vs re-running at each k).

**API surface — FINAL (simplified 2026-07-04, Faisal's simplicity rule: no knob without a clear use case):**

```python
result = Evaluator(task, dataset, metrics=["correctness"], samples=8).run()  # the ONLY new arg
result.metrics["correctness"]   # 0.61 ±0.05  (mean per attempt)
result.pass_at(3)               # any k ≤ n, on demand — a METHOD, not config
```

- `samples=` — **kept**, the only new parameter.
- `sample_strategy=` — **removed**. Sequential passes IS the behavior (pass 1 completes, its slice metrics final, then pass 2 — preserving the progressive group-run UX users know). Interleaved mode has no user-facing knob until a use case appears.
- `reduce=` — **removed**. Anything beyond the defaults via `result.pass_at(k)` / `result.pass_hat(k)` methods, computed from stored attempts.

**Reported metric set (decided 2026-07-04): the existing group-analysis vocabulary with k = samples.** A ×5 run auto-reports `Pass@5 · Pass^5 · Avg@5 · Max@5 · Consistency · Reliability` — the same names and formulas users already know from platform group analysis. This set appears in: the terminal final-summary panel, the runs-list expansion footer row, and the run-detail summary. Run detail additionally holds the in-depth view (accuracy-vs-k curve, any-k band, per-item dots). No "any@k/all@k" aliases — one vocabulary everywhere.

**Execution semantics:** dataset runs k sequential passes; an **attempt slice** (all items' attempt #j) is first-class, so per-pass metrics render like today's per-run rows. The existing `max_concurrency` caps in-flight calls; **no other parallelism knob**. Checkpoint/resume per (item, attempt). SDK warns when `temperature=0` or all attempts are byte-identical (prompt caching defeats sampling).

**No reducer lock-in (hard rule):** the platform stores all n attempts and computes **any pass@k / pass^k for k ≤ n on demand** (plus the accuracy-vs-k curve). *Reduction is a display concern, never a data commitment.*

**Composition rules:**
- `samples=` is the **only** way to express repeats. A runs list is only for *different* runs; duplicating a spec ×3 with `samples=3` gives 3 logical runs × 3 samples (legal, pointless) → SDK warns *"duplicate spec — did you mean samples=9?"*.
- Parallelism hierarchy: `run_parallel(max_parallel_runs)` → runs · `max_concurrency` → calls in flight per run · `samples` → tries per item (same queue).
- Surface cleanup: `run()` = one run · `samples=` = repeats · `model=[...]` = model fan-out · `run_parallel([specs])` = different runs. `MultiModelRunner` becomes internal plumbing of `run_parallel`; duplicate-spec-for-repeats is deprecated.

**Design pattern:** no new class — *new parameter when it's the same behavior repeated, new class when behavior genuinely differs.* Repeats = same evaluation × k → parameter + a new pure-function module `qym/core/reducers.py` (registered like metrics). A `RepeatEvaluator` would duplicate Evaluator's plumbing and drift (see `MultiModelRunner` as the cautionary tale).

**Note on `group_analysis`:** it stays what it is — the code-level accessor for the platform's post-hoc metrics. We port its pass@k/pass^k **formulas** into `reducers.py`; the attempt-pooling engine is **new code**, not a repurposing.

**THE UI RULE — the attempt is the atomic unit.** All repeat math runs over the *pooled set of attempts*, however produced (a ×8 run = 8 attempts/item; a legacy single run = 1). Consequences per view:
- **Shared metric columns (runs list / charts):** always show **mean score per attempt** — the same semantic in every row, so ×1 and ×8 runs are apples-to-apples. Multi-sample rows display `0.61 ±0.06` (the CI itself is the differentiator, plus a `×8` chip). pass@k / pass^k **never** enter the shared column — they're repeat-only columns (`—` for single runs) or live in run detail + the accuracy-vs-k report.
- **Models view:** selecting runs pools their attempts → **one** pass@k computation over the pool (k ≤ total attempts). No pass@k-of-pass@k nesting, ever. Today's cross-run pass@3 is the special case where each run donates 1 attempt.
- **Run detail:** per item, a dot strip `✅❌✅✅❌✅✅✅` + reduced score, expandable to the attempts.
- **Dataset item history:** one row per *logical* run; a ×3 run is one row with its dot strip.
- **Runs grouping:** `runs.samples` column replaces the timestamp+model+task grouping heuristic (legacy rows keep the heuristic).

**Data contract:** `runs.samples` (int) · attempts in `run_item_attempts` (verify migration-0015 shape fits) · `run_item_scores` stores the **mean-per-attempt** — so every existing view keeps working with now-defined semantics · `RunEventV1` gains `attempt_index` on item events.

**Docs & deprecations (same release):**
| Today | Becomes |
|---|---|
| Duplicate a spec ×k in `--runs-config` for repeats | **Deprecated** — warning: "did you mean samples=k?" |
| SDK_INTEGRATION_GUIDE "Group Run Analysis" as the repeats recipe | Rewritten: repeats = `samples=`; group analysis reframed for **cross-run comparison only** (different models/prompts) |
| Platform product-eval presets fan out k RunSpecs internally (`services/product_evals.py`) | Migrate to `samples=k` (same behavior, one logical run) |
| RUN_EVENT_SCHEMA / DB_SCHEMA | Gain `attempt_index` on item events + `runs.samples` |

**UI placement — no new pages, no overhaul (settled 2026-07-04; page-accurate mock: `tmp/mockups/repeats-ui-mock.html` v2):**
- **Runs list** (`index.html` + `dashboard.js`): three deltas only — ①`×k` pill in the RUN cell, ②`±CI` beside metric values (its presence signals multi-sample), ③pass member-rows reuse the existing `run-group-header` expand/collapse component (dashboard.js:3077), fed by `runs.samples` instead of the timestamp heuristic. Expansion footer shows the group-analysis set (`Pass@k · Pass^k · Avg@k · Max@k · Consistency · Reliability`, k = samples); per-pass rows are **lazy-loaded on expand** via a small new endpoint (decided 2026-07-04 — list payload stays unchanged/fast). Same columns, sorting, checkboxes, compare. Legacy heuristic groups render unchanged.
- **Implementation defaults (unobjected 2026-07-04):** pass threshold reuses the group-analysis default (`score ≥ 0.8`); each metric gets its own group set (footer shows the primary metric's); an attempt failing after `max_retries` scores 0 and counts as a failed attempt; Stage 2 adds a platform-capability check so a new SDK against an old platform degrades to local-only attempts with a warning.
- **Live per-pass progress**: NOT a new page — the `/run/<id>` page already renders live state; a ×k run adds a compact pass table above the items table while running. Overview's Live Runs card shows `pass 2/5` in its existing Progress column.
- **Accuracy-vs-k + full k-band**: a collapsible section of `/run/<id>`, rendered only when `samples>1` (it describes one run; not in the Charts page).
- **Run detail items table**: gains a dot-strip cell + attempt expansion; root cause/reviews attach per attempt.
- **Terminal TUI**: single-run dashboard gains a pass counter + per-pass lines reusing the multi-run dashboard's row style; final summary panel adds `any@k / all@k / pass@k` lines.
- **Models view / dataset item history**: same pages; group analysis input unit becomes the attempt; item history shows one row per logical run (QymDataTable per the design language).
- All new UI follows `docs/DESIGN_LANGUAGE.md` (shared `QymDataTable`, current text ramp, token-only sizes) — CI-enforced by `tests/platform/test_design_language.py`.

**Build plan — three shippable stages:**
1. **SDK:** `samples`/`reduce`/`sample_strategy` in config · pass-by-pass execution (default) with per-slice results · `reducers.py` · results hold attempts, main score = mean ± CI · per-attempt checkpoint rows · duplicate-spec + temp=0 warnings.
2. **Platform data:** `runs.samples` migration · attempts ingest · `attempt_index` in events (defaults to 1 for old SDKs) · reduced mean into `run_item_scores` · on-demand pass@k/pass^k endpoint (any k ≤ n).
3. **UI:** per the mock — ±CI + `×n` chip + expandable passes in runs list · live per-pass progress · dot strips in run detail · accuracy-vs-k chart · models view pools attempts server-side · retire the grouping heuristic for new runs (legacy keeps it).

---

## 2 · Jury metric — panel of judges — `UI+SDK`

**POINTWISE.** N judge models each score the *same output*; aggregate to one number per item. (Different axis from the Arena, which is pairwise ranking.)

**Reuses:** `create_judge` / `llm_judge` run N× · panel = your `ProjectLlmConnection`s · per-judge detail rides in `MetricResult.metadata`.

```python
from qym import jury

quality = jury(
    "quality",
    prompt="Q: {input}\nA: {output}\nCorrect, safe, complete?",
    choices={"yes": 1.0, "partly": 0.5, "no": 0.0},
    panel=["gpt-4.1", "claude-sonnet", "gemini-2.5"],
    aggregate="mean",        # mean|median|majority|min|max|weighted
)
Evaluator(task, dataset, metrics=[quality]).run()

# breakdown per item:
# {score: 0.83, panel: {gpt-4.1: 1.0, claude-sonnet: 0.5, gemini-2.5: 1.0},
#  agreement: 0.71, split: true}   ← judges disagreed → route to human queue
```

| `aggregate=` | combines by | use when |
|---|---|---|
| `mean` *(default)* | average | general; smooths single-judge noise |
| `median` | middle value | robust to one rogue judge |
| `majority` | modal label | yes/no checks (judge self-consistency) |
| `min` / `max` | strictest / lenient | safety gate / "anyone accept it" |
| weighted | per-judge weights | trust a stronger judge more |

Why a panel: *Replacing Judges with Juries* (PoLL, arXiv:2404.18796) — 3 diverse small judges cut self-preference bias, match humans better, ~7× cheaper than one big judge.

---

## 3 · Unit testing — `UI+SDK`

A **Test Suite** = a versioned collection of pass/fail assertions, authored in the UI like a dataset, referenced from code by name.

**Reuses:** the Datasets machinery (Dataset→Version→Item becomes Suite→Version→Assertion): drafts, publish, `production` alias, lineage, API-key access.

| Assertion (authored in UI) | Type | Config |
|---|---|---|
| No destructive SQL | `not_contains` | DROP, DELETE, TRUNCATE |
| Valid SQL | `sql_parses` | dialect: postgres |
| Returns ≤ 3 rows | `json_path` | `$.length <= 3` |
| Filters to 2025 | `llm_assert` | "Does it filter to 2025?" |

```python
from qym import Evaluator, test_suite

Evaluator(
    task=run_sql_agent,
    dataset="text2sql-eval",                              # UI dataset, by name
    metrics=[ test_suite("sql-safety", version="v3") ],   # UI suite, by name
).run()

result.tests.pass_rate   # 0.92
result.tests.failures    # [(q_0511, "No destructive SQL")]
```

→ mock tab "Unit tests". Frontier: promptfoo / OpenAI-Evals assertions, but UI-managed + versioned like the datasets.

---

## 4 · Arena + ELO leaderboard — `UI`

**PAIRWISE, UI-driven.** Select runs, pick a judge panel, write criteria — qym runs position-swapped A/B battles and ranks models by ELO with confidence intervals. **No code.**

**Built exactly like Auto Root Cause** (`/api/runs/{id}/analyze`):

| Auto Root Cause (today) | Arena (proposed) |
|---|---|
| select items | select **runs** (multi-pick) |
| pick LLM Connection | pick **judge panel** (1..n connections) |
| system_prompt + instructions | comparison criteria ("what is better") |
| preview / test on 1–3 | preview / test on a few **pairs** |
| `analyze-stream` | `arena-stream` (A/B, position-swapped) |
| saves to item_metadata | saves votes to `arena_matches` |
| — | Bradley-Terry → ELO + bootstrap CIs → leaderboard |

```
# new endpoints — twins of the analyze endpoints
POST /api/arena         { run_ids, judge_connection_ids, criteria,
                          swap_and_average: true, style_control: true }
POST /api/arena-stream  # live battle progress
GET  /api/arena/{id}/leaderboard   # models + ELO + 95% CI
```

Leaderboard ranks by Bradley-Terry MLE (logistic regression) on the Elo scale with bootstrap CIs — overlapping CIs ⇒ rank is a range. Style control debiases length/markdown. → mock tabs "Arena setup" + "Leaderboard". (LMArena / Arena-Hard-Auto: ~98.6% correlation with human Arena.)

---

## 5 · Human voting — `UI`

The blind A/B screen. Select runs in the UI (same as Arena), choose **human** instead of a judge panel — your votes land in the **same `arena_matches` table → same ELO leaderboard**.

- Blind, randomized left/right; vote A / Tie / B / Both-bad with hotkeys.
- Annotation queue with reviewer assignment + reservation lock (mirrors Reviews) so two people never grade the same pair.
- One rubric drives both the LLM judge and the human form — single source of truth.
- Bonus: judge-vs-human agreement (Cohen κ) is free since both vote on the same pairs.

→ mock tabs "Human vote" + "Annotation queue".

---

## 6 · Multi-turn / chat-history evals — `SDK`

Score performance **across a long conversation**. The dataset item becomes a list of turns; the task is called turn-by-turn holding session state; metrics score per-turn *and* over the whole trajectory.

```python
# item: {"input": {"turns": ["Top 3 customers 2025?",
#                            "break down by region", "just the top one?"]}}

def run_sql_agent(session):              # task gets a session, not a string
    for turn in session.turns:
        session.reply( my_agent(turn, history=session.history) )

Evaluator(task=run_sql_agent, dataset="multiturn-sql",
          metrics=["correctness", "context_retention"],
          mode="conversation").run()

result.by_turn    # score curve turn 1→2→3 (does it degrade deep in a chat?)
```

Frontier: MT-Bench multi-turn, τ-bench (tool agents).

---

## 7 · Follow-up questions — `SDK`

A thin layer on multi-turn: auto-append **scripted probe turns** that test whether context and conviction survive.

```python
metrics=[ followup_robustness(probes=[
    "are you sure?",            # does it flip-flop under pressure?
    "what about last year?",    # does it carry '2025' to a new year?
]) ]
# scores: consistency-under-challenge, context-carryover
```

---

## 8 · Stress testing — low vs high concurrency — `SDK`

Run the same set at **rising concurrency** and chart how latency and error-rate hold up — load testing folded into an eval run.

**Reuses:** `max_concurrency` config + the latency p50/p90/p99 already captured.

```python
report = Evaluator(task, "text2sql-eval", metrics=["correctness"]).stress(
    concurrency=[1, 10, 50, 100]
)
# conc  p50    p95    err     throughput
# 1     1.9s   2.4s   0.0%    0.5/s
# 100   8.7s   31.2s  6.3%    11/s    ← where it starts to break
```

New view: latency & error-rate vs concurrency curve. CLI: `qym stress run --concurrency 1,10,50,100`.

---

## 9 · Statistics everywhere — `SDK`

Not a button — a **rule applied to every number**: bootstrap 95% CI + error rate on each metric, and a real significance test on run-vs-run diffs.

```python
result.metrics["correctness"]
# 0.61  (95% CI 0.55–0.67, n=120, errors 3.3%)   ← not a bare "0.61"

compare(run_a, run_b)
# correctness +0.05  → "significant" (McNemar p=0.01)  vs  "within noise"
```

Stops a 2-point "win" that's just noise from looking like a win. Overlapping CIs on the leaderboard ⇒ rank shown as a range.

---

## Roadmap — what to build, in order

| Phase | Ships | Why this order |
|---|---|---|
| **0 · Foundation** | Per-item samples · Scorer+Reducer registry · Stats module · centralize score-parsing | Unlocks 1, 2, 9 immediately and 3, 4 later. Nothing user-visible, but everything after is a thin wrapper. |
| **1 · Quick wins** | Repeats/pass@k · Jury metric · Stats surfaced | Pure SDK, high impact. Kills the pass@k duct-tape, adds the panel-of-judges, puts CIs on every number. Mostly wiring existing pieces. |
| **2 · High reuse** | Unit testing | Test-suite tables + UI authoring page (clone the Datasets page) + `test_suite()` SDK reference. Brand-new capability with the most reuse. |
| **3 · High wow** | Arena + ELO + Human voting | `arena_matches` + ELO scorer (reuses Phase-0 stats) · Arena setup UI (clone Auto Root Cause) · leaderboard · blind-vote screen · annotation queue. The flagship visual feature. |
| **4 · New modes** | Multi-turn · Follow-ups · Stress | Most net-new (changes the item shape / run loop) — sequence last. |

---

## Existing decisions this respects

- **Declarative `qym.yaml` is the contract** — every SDK feature is a config field or named reference, no new imperative surface.
- **No user code runs on the platform** — Arena, voting, and unit-test authoring are pure UI/data; the SDK only references them by name.
- **Native in-platform execution stays deferred** — nothing here requires it.
- **Build on what exists** — Datasets, Auto Root Cause, Reviews, group_analysis, create_judge, run_item_attempts are reused, not replaced.

---

## Frontier basis (research references)

| Area | Sources |
|---|---|
| ELO / pairwise ranking | LMArena Bradley-Terry (arXiv:2403.04132), Arena-Hard-Auto (arXiv:2406.11939), style control (LMSYS 2024-08-28) |
| pass@k / repeats | Codex unbiased pass@k (arXiv:2107.03374), Large Language Monkeys (arXiv:2407.21787), Inspect AI epochs+reducers, pass^k reliability (philschmid) |
| Judge panels | Replacing Judges with Juries / PoLL (arXiv:2404.18796), MT-Bench (arXiv:2306.05685), G-Eval (arXiv:2303.16634), AlpacaEval LC (arXiv:2404.04475), HealthBench rubrics |
| Human-eval UIs | LangSmith pairwise annotation queues, Langfuse annotation queues, Phoenix score configs, Label Studio IAA |
| Statistics | bootstrap CIs (Efron/Tibshirani; Raschka arXiv:1811.12808), McNemar (Dietterich 1998), paired bootstrap (Koehn 2004), Krippendorff α, Benjamini-Hochberg |
