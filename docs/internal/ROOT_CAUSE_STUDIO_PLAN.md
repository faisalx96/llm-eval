# Root Cause Studio — Unified Implementation Plan

This plan merges the Root Cause Studio product spec with the learning system implementation details into a single actionable document.

---

## 1. Problem

The current auto-analyzer uses **5 most recent approved corrections** as few-shot examples, injected via a generic system prompt with hardcoded categories. This is fundamentally insufficient for domain-adaptive RCA.

### What's missing

| Gap | Impact |
|---|---|
| No domain knowledge | LLM has zero context about the product, evaluation criteria, or domain heuristics |
| Random example selection | Most recent != most relevant. 5 Hallucination examples teach nothing about Context Missing |
| No pattern compression | Can't scale beyond ~15 raw examples without blowing context windows |
| No structured expertise | SME decision rules ("if retrieval < 0.3 AND contradicts source, it's Hallucination") are never captured |
| No versioning | Analyzer behavior changes silently after every correction approval |
| No session history | Analysis jobs are fire-and-forget with no provenance |
| Fragmented UX | Config in profile, analysis in modal, corrections in reviews — no coherent workspace |

### Current code bottleneck

```python
# llm_analyzer.py:get_few_shot_examples()
db.query(ReviewCorrection)
    .filter(task=task, status=APPROVED, is_active=True)
    .order_by(ReviewCorrection.created_at.desc())
    .limit(5)  # <-- this is the entire "learning" system
```

---

## 2. Solution Overview

Three layers of intelligence, wrapped in a Studio product experience.

### Layer 1: Analyst Knowledge Base

The SME structures their domain expertise into a versioned Analyst profile: taxonomy with decision criteria, domain context, knowledge sources, and behavioral policies.

### Layer 2: Smart Retrieval (Case Memory)

Replace "last 5 corrections" with embedding-based semantic retrieval from curated case memory. Diversity-aware selection ensures coverage across failure categories.

### Layer 3: Rule Distillation (Policy Memory)

As case memory grows, use the LLM to compress patterns into reusable rules. These go into the system prompt, freeing context window for more few-shot examples.

### Product wrapper: Root Cause Studio

A dedicated top-level workspace that manages the full lifecycle: create analysts, run sessions, review results, apply learnings, benchmark quality.

---

## 3. Prompt Architecture

This is the assembled prompt that the Analysis Service builds at inference time. Every section maps to a concrete data source.

```
+--------------------------------------------------------------+
| SYSTEM PROMPT                                                 |
|                                                               |
|   1. Base instructions                                        |
|      Source: analyst_versions.system_behavior_config           |
|      "You are an expert RCA analyst. Classify failures..."    |
|                                                               |
|   2. Domain context                                           |
|      Source: analyst_profiles.description + knowledge_sources  |
|      "We are evaluating a customer support chatbot for a      |
|       fintech product that handles account inquiries..."      |
|                                                               |
|   3. Category taxonomy with decision criteria                 |
|      Source: analyst_versions.taxonomy_snapshot_json           |
|      Each category includes: definition, positive signals,    |
|      negative signals, required evidence, common confusions   |
|                                                               |
|   4. Distilled policy rules                                   |
|      Source: policy_memory_entries (active, for this analyst)  |
|      "When faithfulness < 0.4 and output contains specific    |
|       statistics, root cause is Hallucination (12/14 cases)"  |
|                                                               |
|   5. Retrieved knowledge snippets                             |
|      Source: knowledge_sources (RAG over embedded chunks)      |
|      Relevant product docs, glossary entries, domain rules    |
|                                                               |
+--------------------------------------------------------------+
| USER MESSAGE                                                  |
|                                                               |
|   6. Retrieved case memory (10-15 examples)                   |
|      Source: case_memory_entries (via retrieval service)       |
|      Semantically similar, diversity-balanced, prioritizing   |
|      cases where the AI was wrong and SME corrected           |
|                                                               |
|   7. Current item to analyze                                  |
|      Source: run_items + run_item_scores                       |
|      INPUT / EXPECTED / ACTUAL / SCORES / METADATA            |
|                                                               |
+--------------------------------------------------------------+
```

### Taxonomy entry example

```
Category: Hallucination
Definition: The model fabricates information not present in the retrieved context.
Positive signals:
  - Output includes specific numbers, dates, or facts not in source documents
  - Retrieval score > 0.5 but output contradicts or extends beyond source material
  - Model presents invented references or citations
Negative signals:
  - Output is vague or generic (more likely Incomplete Answer)
  - Information is correct but poorly formatted (more likely Wrong Format)
Required evidence: Identify the specific fabricated claim and confirm it is absent from source.
Common confusions:
  - vs Knowledge Gap: Hallucination = model invented something. Knowledge Gap = model
    correctly identified it doesn't know, or genuinely lacks the information.
  - vs Context Missing: If the source documents don't contain the answer at all,
    prefer Context Missing. Hallucination requires the model to have access to relevant
    context but fabricate beyond it.
```

### Distilled rule example

```
Rule: Faithfulness-Score Hallucination Indicator
Based on: 14 approved corrections
Pattern: When metric `faithfulness` < 0.4 and the output contains specific statistics
  or numerical claims, the root cause is Hallucination (confirmed in 12/14 cases).
Exception: If the expected answer also contains those statistics, check for
  "Wrong Format" instead.
Confusion labels: [Hallucination, Context Missing, Knowledge Gap]
```

---

## 4. Retrieval Algorithm

The Retrieval Service replaces `get_few_shot_examples()`. This is the highest-impact single change.

### Algorithm

```
Input: current item context (input, expected, output, scores, metadata)
Output: 10-15 case memory entries for few-shot injection

1. Embed the current item context using the analyst's configured embedding model.

2. Retrieve top-30 most similar case_memory_entries by cosine similarity
   (filtered to analyst_id, active=True).

3. Score each candidate:
   score = similarity * recency_weight * correction_value_weight

   Where:
   - recency_weight: 1.0 for <30 days, 0.9 for 30-90 days, 0.8 for 90+ days
   - correction_value_weight:
     - 1.5 if AI was wrong and SME corrected (source_type = approved_correction
       with ai_root_cause != human_root_cause)
     - 1.0 if human-only label (no prior AI suggestion)
     - 0.8 if AI was correct and SME confirmed

4. Greedy diversity-aware selection:
   selected = []
   category_counts = {}
   for candidate in ranked_candidates:
       cat = candidate.root_cause
       if category_counts.get(cat, 0) >= 3:
           continue  # max 3 per category
       selected.append(candidate)
       category_counts[cat] = category_counts.get(cat, 0) + 1
       if len(selected) >= 15:
           break

5. Return selected, ordered by similarity (most relevant first).
```

### Why this matters

- "Last 5" gives 5 random examples. This gives 10-15 targeted examples with coverage.
- AI-was-wrong examples teach the model its own mistake patterns.
- Category diversity prevents the model from anchoring on one failure type.
- Can be shipped as a backend-only change before any Studio UI exists (see Phase 0).

---

## 5. Learning Operating Model

The system must **not** learn automatically after every SME edit or approval.

### Three distinct workflows

#### A. Correction Capture (run/compare pages)

User corrects a root cause. System persists correction immediately and marks it as a candidate for future analyst learning. No analyst memory changes.

#### B. Learning (Studio only)

User opens an analyst, sees pending learnings, clicks "Apply New Learnings". System:
1. Gathers newly approved corrections for that analyst
2. Transforms them into structured case memory entries
3. Generates embeddings
4. Clusters and distills policy rules
5. Produces a draft analyst version update
6. Presents summary of what changed

#### C. Analysis (Studio launch or run/compare deep-link)

System uses only the currently **published** analyst version. Retrieves from stored case memory and policy rules. Stores results with analyst/version provenance.

### Why explicit learning

- Avoids hidden behavior changes after every correction
- Teams control when analyzer behavior changes
- Analyst versions remain auditable
- "New information available" is visible in UI

---

## 6. Core Domain Objects

### Analyst

A named RCA profile owned by a user or team. UI term: "Analyst" (not "Agent").

### Analyst Version

An immutable published configuration used for analysis sessions. Snapshots taxonomy, retrieval config, review policy, and knowledge config at publish time.

### Taxonomy

The root-cause ontology and decision policy. Each entry: category, detail, definition, positive signals, negative signals, required evidence, common confusions, boundary examples.

### Knowledge Source

Domain knowledge attached to an analyst: SME-authored notes, glossary entries, product rules, uploaded docs, tool behavior references, URLs.

### Case Memory Entry

A curated, searchable precedent derived from approved corrections or manually authored. Includes: root cause, detail, evidence summary, SME note, rejected alternative, embedding vector, quality score.

### Policy Memory Entry

A distilled rule learned from groups of case memories. Includes: rule text, support count, confusion labels.

### Analysis Session

A launched RCA job with provenance: analyst, version, task scope, filters, status, timestamps.

### Result Item

One analyzed item inside a session: prediction, confidence, retrieved case/rule IDs, support summary, review status.

### Benchmark

A curated set of gold-labeled cases for evaluating analyzer quality against specific analyst versions.

---

## 7. Data Model

### Existing tables (keep as-is)

- `review_corrections` — raw source of truth for SME corrections
- `runs`, `run_items`, `run_item_scores` — evaluation data

### New tables

#### `analyst_profiles`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(200) | |
| `description` | Text | Domain context for system prompt |
| `owner_user_id` | UUID FK | |
| `owner_team_id` | UUID FK | Nullable |
| `task_scope` | String(200) | Which tasks this analyst covers |
| `default_metric` | String(100) | |
| `status` | Enum | `draft`, `active`, `archived` |
| `current_published_version_id` | UUID FK | Nullable |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

#### `analyst_versions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `version_number` | Integer | |
| `status` | Enum | `draft`, `published`, `archived` |
| `base_version_id` | UUID FK | Nullable, what version this was derived from |
| `taxonomy_snapshot_json` | JSON | Frozen taxonomy at publish time |
| `retrieval_config_json` | JSON | Embedding model, K, diversity params |
| `review_policy_json` | JSON | Confidence thresholds, routing rules |
| `knowledge_config_json` | JSON | Field mapping, additional instructions |
| `system_prompt_template` | Text | Custom or template-based prompt |
| `created_by_user_id` | UUID FK | |
| `created_at` | DateTime | |
| `published_at` | DateTime | Null if still draft |

#### `analyst_learning_candidates`

The bridge between approved corrections and analysts that may learn from them.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `correction_id` | UUID FK | -> review_corrections |
| `candidate_status` | Enum | `pending`, `included`, `skipped`, `superseded` |
| `reason` | Text | Why skipped/superseded |
| `created_at` | DateTime | |
| `resolved_at` | DateTime | When included/skipped |

#### `case_memory_entries`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `source_correction_id` | UUID FK | Nullable |
| `source_learning_job_id` | UUID FK | Nullable |
| `source_type` | Enum | `approved_correction`, `manual_example`, `benchmark_example` |
| `task` | String(200) | |
| `root_cause` | String(200) | |
| `root_cause_detail` | String(200) | |
| `summary_text` | Text | Structured failure summary |
| `evidence_text` | Text | Key evidence extracted |
| `sme_note` | Text | |
| `rejected_alternative` | String(200) | What the AI guessed wrong |
| `metadata_tags_json` | JSON | |
| `embedding_vector` | Vector(1536) | For semantic retrieval |
| `quality_score` | Float | |
| `active` | Boolean | |
| `created_at` | DateTime | |

#### `policy_memory_entries`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `source_learning_job_id` | UUID FK | |
| `task` | String(200) | |
| `root_cause` | String(200) | |
| `root_cause_detail` | String(200) | |
| `rule_text` | Text | The distilled rule |
| `support_count` | Integer | How many cases support this |
| `confusion_labels_json` | JSON | Categories this rule disambiguates |
| `status` | Enum | `draft`, `approved`, `rejected`, `archived` |
| `reviewed_by_user_id` | UUID FK | |
| `reviewed_at` | DateTime | |
| `active` | Boolean | |
| `created_at` | DateTime | |

#### `knowledge_sources`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `type` | Enum | `note`, `glossary`, `document`, `url`, `rule` |
| `title` | String(200) | |
| `content` | Text | |
| `source_url` | Text | Nullable |
| `tags` | JSON | |
| `status` | Enum | `processing`, `ready`, `failed`, `stale` |
| `created_at` | DateTime | |

#### `learning_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `base_version_id` | UUID FK | |
| `target_draft_version_id` | UUID FK | |
| `status` | Enum | `queued`, `running`, `completed`, `failed`, `cancelled` |
| `triggered_by_user_id` | UUID FK | |
| `candidate_count` | Integer | |
| `included_count` | Integer | |
| `skipped_count` | Integer | |
| `new_case_count` | Integer | |
| `new_rule_count` | Integer | |
| `summary_json` | JSON | |
| `error_text` | Text | |
| `created_at` | DateTime | |
| `started_at` | DateTime | |
| `completed_at` | DateTime | |

#### `analysis_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analyst_id` | UUID FK | |
| `analyst_version_id` | UUID FK | |
| `task` | String(200) | |
| `run_scope_json` | JSON | Which runs/items |
| `filter_config_json` | JSON | Thresholds, filters |
| `status` | Enum | `queued`, `running`, `completed`, `failed` |
| `item_count` | Integer | |
| `created_by_user_id` | UUID FK | |
| `created_at` | DateTime | |
| `completed_at` | DateTime | |

#### `analysis_result_items`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `session_id` | UUID FK | |
| `run_id` | UUID FK | |
| `item_id` | String | |
| `predicted_root_cause` | String(200) | |
| `predicted_root_cause_detail` | String(200) | |
| `predicted_note` | Text | |
| `confidence` | Float | |
| `retrieved_case_ids_json` | JSON | Which memories were used |
| `retrieved_rule_ids_json` | JSON | Which rules were used |
| `support_summary` | Text | |
| `alternative_considered` | String(200) | |
| `review_status` | Enum | `suggested`, `accepted`, `corrected`, `rejected`, `escalated` |
| `review_reason` | Text | |
| `created_at` | DateTime | |

---

## 8. Backend Services

### 1. Candidate Service

- On correction approval, find analysts whose `task_scope` matches
- Create `analyst_learning_candidates` rows with status `pending`
- Compute pending counts for Studio badges
- Lightweight, synchronous

### 2. Memory Builder Service

- Input: approved `ReviewCorrection`
- Output: structured `case_memory_entries`

Each case memory should include:
- Failure summary (1-2 sentences: what happened)
- Key evidence (which metrics, what in the output)
- Correct label + detail
- Rejected alternative (what AI guessed wrong)
- Tags (category, detail, difficulty)

### 3. Embedding Service

- Generate embeddings for case memory entries
- Generate embeddings for item context at query time
- Configurable model (default: text-embedding-3-small)

### 4. Retrieval Service

The core intelligence layer. Given a new run item:
1. Embed item context
2. Retrieve similar case memories (algorithm in Section 4)
3. Retrieve relevant policy rules (by category overlap)
4. Retrieve relevant knowledge source chunks (RAG)
5. Return assembled context for prompt building

### 5. Rule Distillation Service

- Analyze groups of related case memories by category/detail
- Call LLM to generate reusable rule summaries
- Output: `policy_memory_entries` with status `draft`
- SME reviews and approves before rules are used

### 6. Analysis Service

- Build prompt using the prompt architecture (Section 3)
- Must use published analyst version only
- Call LLM, parse result, run optional verification
- Persist `analysis_result_items` with retrieved case/rule IDs
- This makes the analyzer's reasoning inspectable

---

## 9. Backend API

### Analyst APIs

- `GET /api/rca/analysts` — list
- `POST /api/rca/analysts` — create
- `GET /api/rca/analysts/{id}` — detail
- `PATCH /api/rca/analysts/{id}` — update
- `POST /api/rca/analysts/{id}/archive`

### Version APIs

- `GET /api/rca/analysts/{id}/versions` — list versions
- `POST /api/rca/analysts/{id}/versions/draft` — create draft
- `POST /api/rca/versions/{id}/publish` — publish draft
- `GET /api/rca/versions/{id}` — inspect version

### Learning APIs

- `GET /api/rca/analysts/{id}/learning-summary` — pending count, last job status, new categories detected
- `GET /api/rca/analysts/{id}/learning-candidates` — list pending candidates
- `POST /api/rca/analysts/{id}/learning-jobs` — trigger learning job
- `GET /api/rca/learning-jobs/{job_id}` — job status/progress
- `GET /api/rca/learning-jobs/{job_id}/results` — job outcome

### Session APIs

- `POST /api/rca/sessions` — launch analysis
- `GET /api/rca/sessions` — list sessions
- `GET /api/rca/sessions/{id}` — session detail
- `GET /api/rca/sessions/{id}/items` — result items
- `POST /api/rca/sessions/{id}/cancel`

### Review APIs

- `POST /api/rca/result-items/{id}/accept`
- `POST /api/rca/result-items/{id}/correct`
- `POST /api/rca/result-items/{id}/reject`
- `POST /api/rca/result-items/{id}/escalate`

### Memory APIs

- `GET /api/rca/analysts/{id}/memory` — search case memory
- `POST /api/rca/analysts/{id}/memory` — manually add entry
- `PATCH /api/rca/memory/{id}` — edit/deactivate
- `GET /api/rca/analysts/{id}/rules` — list policy rules
- `POST /api/rca/rules/{id}/approve` — approve draft rule
- `POST /api/rca/rules/{id}/reject`

---

## 10. Frontend: Studio Pages

### Landing Page

Top-level nav item: `Root Cause Studio`

Landing page immediately answers:
- Which analysts exist
- Which have pending learnings (badge: "12 New Learnings")
- Which versions are published vs draft
- Recent sessions and their outcomes

### Analysts Index

Card grid. Each card shows: name, task scope, published version, pending learning count, last session status.

Row actions: open, duplicate, archive, compare versions.

Empty state: explain what analysts combine (taxonomy + knowledge + memory + policy) with CTA "Create Your First Analyst".

### New Analyst Wizard

6-step guided setup:

1. **Basics** — name, description, task scope, default metric, team
2. **Taxonomy** — create categories with definitions, evidence requirements, common confusions, boundary examples. Start from defaults or blank.
3. **Knowledge** — upload docs, add glossary entries, paste domain rules and notes. Tag each source.
4. **Memory** — choose approved corrections to seed the analyst. Inspect representative examples, remove noisy ones, mark canonical examples.
5. **Behavior** — confidence threshold, low-confidence routing policy, novelty handling, retrieval defaults (K, diversity params), review defaults.
6. **Test & Publish** — select 1-3 sample items, run preview, inspect retrieved support and output, publish as v1.

### Analyst Detail

Tabs:

#### Overview
Summary, owner, task scope, current version, benchmark trend sparkline, recent sessions.

#### Taxonomy
Editable tree view: categories > details > definitions > evidence criteria > confusion notes.

#### Knowledge
List/preview all attached sources. Per source: title, tags, status, type, freshness. Actions: remove, reprocess.

#### Memory
Search and curate case memory. Search by category, detail, tag, or text. Preview source correction. Promote/disable examples. Inspect quality flags.

#### Learning
The most important new surface.

Shows:
- Pending approved corrections not yet ingested (table: correction id, task, item id, human root cause, source run, approved at)
- Learning summary: pending count, potential new categories/details, warnings for conflicts
- "Apply New Learnings" CTA with controls: include all / exclude selected / optional notes
- Last job outcome: new cases created, new rules created, candidates skipped, link to draft version

#### Evaluation
- Agreement rate over time (line chart, by week/month)
- Category confusion matrix (heatmap: AI category vs Human category)
- Confidence calibration (plot: predicted confidence vs actual accuracy)
- Per-category F1 scores (bar chart)
- Edit rate, low-confidence rate, corrections needed trend

#### Versions
Version history with diffs. Compare versions side-by-side. Inspect changed taxonomy, knowledge, retrieval settings. Restore older version as draft.

### Launch Session

Inputs: analyst, version (default: published), run(s), filters (failed/passed/errors, score threshold, domain, complexity, root-cause status, item selection).

Pre-launch summary: selected version, estimated item count, memory coverage warning, benchmark freshness warning, predicted review load.

Actions: `Preview Prompt`, `Test on Sample` (1-3 items), `Run Full Analysis`.

Draft version testable but clearly marked as unpublished.

### Session Results

Three-pane layout:

**Left — Item Queue**: filterable list (all, accepted, corrected, rejected, needs review, low confidence, novel, weak support). Each item: id, category/detail, confidence, status badge.

**Center — Item Detail**: input, expected, output, error, scores, metadata, predicted root cause, detail, note. Per-item actions: accept, edit, reject, escalate, add feedback, promote to memory candidate.

**Right — Support Panel**: retrieved case memories, retrieved policy rules, knowledge snippets, evidence summary, alternative considered, analyst version. This makes the analyzer's reasoning visible.

Result badges: High confidence, Low confidence (color-coded: green >0.8, yellow 0.5-0.8, red <0.5), Novel case, Weak support, Policy conflict.

### Review Queue

Operational review center. Evolves from current reviews.html.

Primary views: pending analyzer results, approved corrections awaiting memory decision, low-confidence items, novel items, disagreements.

Filters: analyst, session, task, status, confidence range, novelty, source type.

Bulk actions: approve, reject, route to SME, exclude from memory, approve into memory.

### Benchmarks

Curated gold-labeled case sets for objective quality measurement.

Views: benchmark set list, run benchmark against version, compare across versions.

Metrics: overall agreement, by category, by detail, calibration by confidence bucket, confusion matrix, edit rate.

---

## 11. Integration With Existing Pages

### Run Page

Keep: inline root-cause editing, feedback editing, quick auto-analyze.

Add:
- "Analyze in Studio" deep-link (pre-fills analyst + run)
- Analyst/version badge on AI-produced root causes
- Review-status chip
- Toast on correction: "Saved. Available for analyst learning in Root Cause Studio."

### Compare Page

Same pattern: keep quick auto-analyze and inline correction, add deep-link to Studio.

### Profile Page

Keep only: provider credentials, model configuration, connection test. Analyzer behavior belongs to Studio.

### Reviews Page

Eventually becomes the Studio Review Queue section or redirects to it.

### Current Playground Modal

Stays, repositioned as: Quick Analyze, Quick Test, Prompt Preview. Not the primary analyzer configuration surface.

---

## 12. End-to-End Flows

### Flow A: SME Corrects Root Cause

1. User edits root cause in run/compare page.
2. Frontend calls existing correction API.
3. Backend stores/updates `review_corrections`.
4. Reviewer approves correction.
5. Candidate Service creates `analyst_learning_candidates` for matching analysts.
6. Studio shows pending learning count.
7. **No memory or behavior changes yet.**

### Flow B: Apply New Learnings

1. User opens analyst detail > Learning tab.
2. Frontend calls `GET /learning-summary` and `GET /learning-candidates`.
3. User clicks "Apply New Learnings".
4. Frontend calls `POST /learning-jobs`.
5. Backend creates learning job, processes candidates:
   - Fetch underlying corrections
   - Build structured case memory entries
   - Generate embeddings
   - Cluster by category/detail
   - Distill policy rules
   - Mark candidates as included/skipped
6. Frontend polls `GET /learning-jobs/{id}` showing progress: collecting candidates > building memory > generating embeddings > distilling rules > saving draft.
7. Job completes. Frontend shows: new cases, new rules, skipped, errors, link to draft version.
8. User inspects draft, clicks "Publish".
9. Backend marks draft as published, updates `analyst_profiles.current_published_version_id`.

### Flow C: Run Analysis Session

1. User launches from Studio or deep-link from run/compare.
2. Frontend calls `POST /api/rca/sessions`.
3. Backend resolves published analyst version.
4. For each item:
   a. Retrieval Service fetches similar case memories + relevant rules + knowledge snippets (Section 4 algorithm).
   b. Analysis Service assembles prompt (Section 3 architecture).
   c. LLM call, parse response.
   d. Store `analysis_result_items` with retrieved IDs.
5. Frontend shows results with support panel.
6. User reviews: accept / correct / reject / escalate per item.

---

## 13. Delivery Phases

### Phase 0: Smart Retrieval Quick Win (backend only, no UI)

**Highest impact, zero frontend work.** Ship before any Studio UI.

- Add `embedding` column to `case_memory_entries` (or directly on `review_corrections` as interim)
- Implement embedding generation on correction approval
- Replace `get_few_shot_examples()` with similarity-based retrieval using the algorithm from Section 4
- Increase default example count from 5 to 10-15
- Wire into existing `build_analysis_prompt()` and existing auto-analyze modal

This immediately improves every auto-analysis run across the product.

### Phase 1: Studio Foundation

**Backend:**
- Create new tables: `analyst_profiles`, `analyst_versions`, `analyst_learning_candidates`, `case_memory_entries`, `policy_memory_entries`, `knowledge_sources`, `learning_jobs`
- Candidate registration from approved corrections
- Analyst CRUD APIs
- Learning job APIs
- Draft/publish version model

**Frontend:**
- `Root Cause Studio` top-level nav entry
- Analysts index (card grid with pending learning badges)
- New Analyst wizard (6 steps)
- Analyst detail page with Learning tab
- "Apply New Learnings" job flow with progress view
- Deep-link from run/compare into Studio

### Phase 2: Sessions & Memory

**Backend:**
- Create tables: `analysis_sessions`, `analysis_result_items`
- Memory Builder Service
- Embedding Service
- Retrieval Service (full algorithm from Section 4)
- Rule Distillation Service
- Analysis Service using analyst versions and assembled prompts

**Frontend:**
- Launch Session page
- Session Results page (3-pane layout with support panel)
- Version inspection and publish flow
- Memory curation UI in Analyst Detail
- Knowledge source management

### Phase 3: Benchmarks & Quality

**Backend:**
- Benchmark tables and APIs
- Quality metrics computation (agreement, confusion matrix, calibration)
- Version comparison support

**Frontend:**
- Benchmark UI (create sets, run against versions, compare)
- Evaluation tab in Analyst Detail (charts: agreement trend, confusion heatmap, calibration plot, per-category F1)
- Version comparison UI
- Review Queue (evolved from reviews.html)

---

## 14. State Models

### Analyst
`draft` > `active` > `archived`

### Analyst Version
`draft` > `published` > `archived`

### Knowledge Source
`processing` > `ready` | `failed` > `stale`

### Learning Candidate
`pending` > `included` | `skipped` | `superseded`

### Learning Job
`queued` > `running` > `completed` | `failed` | `cancelled`

### Session
`queued` > `running` > `completed` | `failed`

### Result Item
`suggested` > `accepted` | `corrected` | `rejected` | `escalated`

### Policy Rule
`draft` > `approved` | `rejected` > `archived`

---

## 15. MVP (Minimum Viable Studio)

If scope must be constrained:

1. Phase 0 (smart retrieval) — ships immediately, backend only
2. Analysts index + wizard — create and configure analysts
3. Launch session + results page — run analysis with provenance
4. Deep-link from run/compare — bridge existing UX to Studio
5. Review Queue in Studio — evolve reviews.html

This is the smallest version that turns RCA from "a modal + a correction inbox" into a coherent product area with a learning loop.
