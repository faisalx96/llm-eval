# Root Cause Analysis Learning System

## Problem Statement

The auto root cause analyzer currently uses **5 most recent approved corrections** as few-shot examples. This is insufficient for the AI to develop domain expertise comparable to a subject matter expert (SME). The system lacks:

- Domain-specific knowledge (product context, evaluation criteria, domain heuristics)
- Intelligent example selection (most recent != most relevant)
- Pattern compression (can't scale raw examples beyond token limits)
- Structured expertise capture (SME decision rules are never recorded)

## Solution: Dynamic Prompting + Knowledge Engineering + Smart Retrieval

No fine-tuning required. Three layers, each building on the last.

---

## Layer 1: Agent Knowledge Base

The SME creates an **Analysis Agent** — a domain profile that structures their expertise into a reusable, prompt-injectable format.

### What the Agent stores

| Field | Purpose |
|---|---|
| Name & description | Identify the agent and its domain |
| Task scope | Which tasks this agent covers |
| Domain context | Free-text description of the product/system being evaluated |
| Category taxonomy | Custom root cause categories with **descriptions and decision criteria**, not just labels |
| Decision rules | Explicit heuristics the SME uses (e.g., "If retrieval score < 0.3 AND output contradicts source, classify as Hallucination") |
| Reference documents | Product specs, evaluation rubrics — chunked and embedded for RAG retrieval |
| LLM config | Model, temperature, provider URL/key |
| Field mapping | Which item fields to include, custom variable mapping |

### How it's used

All agent knowledge is injected into the **system prompt** as structured context. It serves as the "textbook" the AI reads before analyzing any item. The category taxonomy replaces the current hardcoded `ROOT_CAUSE_CATEGORIES` list with rich, descriptive entries that teach the LLM *when* to apply each category.

### Example: Category with decision criteria

```
Category: Hallucination
Description: The model fabricates information not present in the retrieved context.
When to apply:
  - Output includes specific numbers, dates, or facts not in the source documents
  - Retrieval score > 0.5 but output contradicts or extends beyond source material
  - Model presents invented references or citations
Common confusion: Don't confuse with "Knowledge Gap" — Hallucination means the model
  invented something, Knowledge Gap means the model correctly identified it doesn't know.
```

---

## Layer 2: Smart Few-Shot Selection

Replace `ORDER BY created_at DESC LIMIT 5` with **semantic similarity + diversity-aware retrieval**.

### Approach

1. **Embed all approved corrections** — store vector embeddings in DB alongside `ReviewCorrection` records
2. **At analysis time** — embed the current item's context, retrieve top-K most similar corrections
3. **Ensure diversity** — select examples covering different categories (not 5 examples of the same failure type)
4. **Priority weighting** — corrections where the AI was wrong and human corrected it carry higher weight (these are the "mistakes to learn from")
5. **Scale to 10-15 examples** — with smart selection, more examples = better accuracy, within token budget

### Selection algorithm

```
1. Embed current item context
2. Retrieve top-30 most similar approved corrections (by cosine similarity)
3. Score each: similarity * recency_weight * correction_value_weight
   - correction_value_weight: higher if AI was wrong and human corrected
4. Greedily select top-K ensuring:
   - No more than 3 examples from any single category
   - At least 1 example from the current item's likely category (if detectable)
   - Mix of AI-agreed and AI-corrected examples
5. Return 10-15 examples ordered by relevance
```

### Why this matters

This is the single highest-impact change. It's the difference between a student studying random textbook pages vs. studying the most relevant practice problems for their exam.

---

## Layer 3: Pattern Distillation

As the correction bank grows (50+ approved corrections), raw examples become redundant. Use the LLM itself to **compress knowledge into rules**.

### Process

1. Trigger distillation (manually or on schedule)
2. Feed all approved corrections for a task/agent to the LLM
3. LLM extracts recurring patterns:
   - Common failure signatures per category
   - Decision boundaries between confusable categories
   - Metric threshold patterns (e.g., "faithfulness < 0.4 almost always indicates Hallucination")
4. SME reviews and approves/edits each distilled pattern
5. Approved patterns are injected into the agent's system prompt

### Example distilled pattern

```
Pattern: Faithfulness-Score Hallucination Indicator
Based on: 14 approved corrections
Rule: When metric `faithfulness` < 0.4 and the output contains specific statistics
  or numerical claims, the root cause is Hallucination (confirmed in 12/14 cases).
Exception: If the expected answer also contains those statistics, check for
  "Wrong Format" instead.
```

### Benefits

- Compresses 50 examples worth of tokens into a few paragraphs of high-signal rules
- Frees context window for more few-shot examples
- Makes the AI's reasoning more transparent and auditable

---

## Resulting Prompt Architecture

```
+--------------------------------------------------+
| SYSTEM PROMPT                                     |
|   - Base instructions (classify failures)         |
|   - Domain context (from Agent profile)           |
|   - Category taxonomy with decision criteria      |
|   - SME decision rules / heuristics               |
|   - Distilled patterns (from correction bank)     |
|   - Reference doc excerpts (retrieved via RAG)    |
|                                                   |
| USER MESSAGE                                      |
|   - 10-15 semantically similar corrections        |
|     (prioritizing AI mistakes the SME fixed)      |
|   - Current item to analyze                       |
+--------------------------------------------------+
```

---

## UI/UX: Dedicated Root Cause Analysis Page

Root cause analysis has outgrown its current home (a modal in the run page + a separate reviews page). It needs a dedicated hub at `/analysis`.

### Page structure: four tabs

```
/analysis
  |-- Agents        (configure domain expertise)
  |-- Analyze       (run analysis on items)
  |-- Knowledge Bank (corrections, patterns, docs)
  |-- Performance   (track AI accuracy & improvement)
```

---

### Tab 1: Agents — Configuration & Setup

The SME creates and manages analysis agents here.

#### Agent setup wizard (step-by-step)

1. **Basics** — Name, domain description, which tasks this agent covers
2. **Categories** — Define root cause categories with descriptions, examples, and decision criteria. Start with defaults, fully customizable. Drag to reorder priority.
3. **Knowledge** — Paste decision rules, heuristics, domain notes. Upload reference docs (product specs, evaluation rubrics). Docs get chunked and embedded.
4. **LLM Config** — Model, temperature, provider URL/key (reuses existing PlaygroundConfig structure)
5. **Field Mapping** — Which item fields to include, custom variable mapping (reuses existing config)

#### Agent list view

Card layout showing each agent with:
- Name and task scope
- Number of approved corrections
- Last used timestamp
- Accuracy trend sparkline
- Quick actions: edit, duplicate, archive

---

### Tab 2: Analyze — Run Analysis

Replaces the "Auto-Analyze" button currently embedded in the run page.

#### Workflow

1. **Select Agent** — pick the agent configured for this domain
2. **Select Run(s)** — choose which run(s) to analyze
3. **Configure filters** — metric thresholds, which items to include (failed only, all, specific items)
4. **Preview** — see a sample prompt before committing
5. **Run** — execute with real-time progress

#### Results view

- Each item shows the AI suggestion with confidence score
- **Inline review**: accept, correct, or skip each result directly (no need to leave the page)
- Batch actions: accept all high-confidence (>0.8), flag low-confidence for manual review
- Color-coded confidence: green (>0.8), yellow (0.5-0.8), red (<0.5)

---

### Tab 3: Knowledge Bank — Evolved Reviews

Replaces the current `/reviews` page and adds knowledge management capabilities.

#### Sub-section: Corrections

The existing reviews list, enhanced with:
- Filter by agent, category, AI-was-wrong vs AI-was-right
- Bulk approve/reject (existing functionality)
- Visual diff: AI suggestion vs Human correction with highlighted differences
- Correction quality indicators (how much did the human change?)

#### Sub-section: Patterns

Distilled rules extracted from corrections:
- "Distill Patterns" button triggers LLM analysis of all approved corrections
- Each pattern shows: rule text, evidence count, categories affected
- SME can edit, approve, or reject each pattern
- Approved patterns auto-inject into the agent's system prompt
- Version history for pattern changes

#### Sub-section: Documents

Uploaded reference docs with:
- Document preview and metadata
- Chunk visualization (how the doc was split)
- Usage stats: which docs are being retrieved for which analyses

---

### Tab 4: Performance — Agent Quality Metrics

Track whether the AI is actually learning and improving.

#### Key metrics

| Metric | What it shows |
|---|---|
| Agreement rate over time | % of AI suggestions the human accepted without changes (line chart) |
| Category confusion matrix | Where the AI gets it wrong (e.g., consistently confuses "Context Missing" with "Knowledge Gap") |
| Confidence calibration | Are high-confidence predictions actually correct? |
| Corrections needed trend | Are corrections decreasing over time? (the "is it learning?" metric) |
| Per-category accuracy | Which categories has the AI mastered vs. still struggling with |
| Time-to-review | How long does the SME spend reviewing AI suggestions? (should decrease) |

#### Visualizations

- Line chart: agreement rate over time (by week/month)
- Heatmap: confusion matrix (AI category vs Human category)
- Calibration plot: predicted confidence vs actual accuracy
- Bar chart: per-category F1 scores

---

## Integration with Existing Pages

### `/run/{id}` (run detail page)

- Keep the root cause breakdown visualization and inline editing
- "Auto-Analyze" button becomes "Analyze with Agent":
  - If only one agent exists for the task, run it directly
  - If multiple agents exist, show a picker
  - Links to `/analysis?tab=analyze&run={id}` for full control

### `/compare` (compare runs page)

- Keep aggregated root cause comparison
- Add link to `/analysis` for deeper investigation

### `/reviews` (corrections page)

- Redirect to `/analysis?tab=knowledge` or keep as a shortcut alias

---

## Implementation Priority

### Phase 1: Smart Few-Shot Selection (backend only)

**Impact: Highest. No UI changes needed.**

- Add embedding column to `ReviewCorrection` model
- Implement embedding generation on correction approval
- Replace `get_few_shot_examples()` with similarity-based retrieval
- Add diversity-aware selection algorithm
- Increase default example count from 5 to 10-15

### Phase 2: Agent Knowledge Base

**Impact: High. New DB model + Tab 1 UI.**

- Create `AnalysisAgent` model (name, task, domain_context, categories, rules, config)
- Build agent CRUD API endpoints
- Build the Agents tab with setup wizard
- Wire agent config into `build_analysis_prompt()` (replace hardcoded categories/prompt)

### Phase 3: Dedicated `/analysis` Page

**Impact: High. Better UX for the complete workflow.**

- Build page shell with tab navigation
- Implement Analyze tab (run selection, progress, inline review)
- Migrate reviews to Knowledge Bank tab
- Connect agent selection to analysis flow

### Phase 4: Pattern Distillation

**Impact: Medium. Scales knowledge compression.**

- Build distillation prompt and pipeline
- Add Patterns sub-section to Knowledge Bank
- SME review workflow for patterns
- Auto-injection into agent system prompt

### Phase 5: Performance Dashboard

**Impact: Medium. Measures and demonstrates improvement.**

- Aggregate correction data into accuracy metrics
- Build confusion matrix and calibration visualizations
- Track agreement rate trends over time

---

## Data Model Changes

### New: `AnalysisAgent`

```
analysis_agent
  id              UUID PK
  name            String(200)
  task            String(200)      -- which task(s) this agent covers
  domain_context  Text             -- free-text domain description
  categories      JSON             -- [{name, description, criteria, examples}]
  decision_rules  JSON             -- [{rule, explanation, priority}]
  llm_config      JSON             -- model, temperature, base_url, etc.
  field_mapping   JSON             -- reuses PlaygroundConfig structure
  system_prompt   Text             -- custom or template-based
  is_active       Boolean
  created_by      String FK
  created_at      DateTime
  updated_at      DateTime
```

### New: `DistilledPattern`

```
distilled_pattern
  id              UUID PK
  agent_id        UUID FK -> analysis_agent
  task            String(200)
  pattern_text    Text             -- the distilled rule
  evidence_count  Integer          -- how many corrections support this
  categories      JSON             -- which categories this pattern relates to
  status          Enum             -- DRAFT, APPROVED, REJECTED, ARCHIVED
  reviewed_by     String FK
  reviewed_at     DateTime
  created_at      DateTime
```

### Modified: `ReviewCorrection`

```
+ embedding       Vector(1536)     -- or stored in a separate embeddings table
+ agent_id        UUID FK -> analysis_agent (nullable, for migration)
```

---

## Key Design Decisions

1. **No fine-tuning** — all learning happens through prompt engineering, knowledge injection, and smart retrieval. This keeps the system model-agnostic and avoids the cost/complexity of fine-tuning pipelines.

2. **SME-in-the-loop** — the AI never learns unsupervised. Every correction must be approved, every distilled pattern must be reviewed. This ensures quality and gives the SME confidence in the system.

3. **Task-scoped agents** — each agent is tied to specific tasks, so domain knowledge doesn't bleed across unrelated evaluation domains.

4. **Backward compatible** — existing corrections and review workflows continue to work. The agent system layers on top without breaking the current flow.

5. **Progressive enhancement** — each phase delivers standalone value. Smart few-shot selection alone (Phase 1) will significantly improve accuracy without any UI changes.
