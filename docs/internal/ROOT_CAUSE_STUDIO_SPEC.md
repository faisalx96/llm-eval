# Root Cause Studio Product Spec

## Summary

`Root Cause Studio` is a dedicated workspace for configuring, running, reviewing, and improving AI-assisted root cause analysis (RCA).

The current product supports:

- provider/model setup on the profile page
- quick auto-analysis launched from run and compare pages
- manual inline root-cause editing on run and compare pages
- correction approval and review on a separate reviews page

That is sufficient for lightweight auto-labeling. It is not sufficient for building a domain-adaptive analyzer that behaves more like a subject matter expert (SME).

This spec defines a first-class RCA workspace that turns the current auto-analyzer into a persistent, inspectable, versioned system with:

- analyzer profiles
- taxonomy and domain knowledge management
- searchable case memory from approved corrections
- batch RCA sessions
- result review workflows
- benchmark and quality tracking

## Problem

The current UX is fragmented across multiple surfaces:

- [`profile.html`](/Users/faisalbh/qym/packages/platform/qym_platform/_static/dashboard/profile.html) stores provider credentials and model settings
- [`run.html`](/Users/faisalbh/qym/packages/platform/qym_platform/_static/dashboard/run.html) lets users launch quick auto-analysis and edit root causes inline
- [`compare.html`](/Users/faisalbh/qym/packages/platform/qym_platform/_static/dashboard/compare.html) lets users launch quick auto-analysis across compared runs
- [`reviews.html`](/Users/faisalbh/qym/packages/platform/qym_platform/_static/dashboard/reviews.html) lets users inspect and approve corrections

This fragmentation creates product limitations:

- analyzer behavior is treated like a modal configuration, not a managed system
- domain knowledge, taxonomy, and decision rules do not have a dedicated home
- approved corrections are visible, but not curated as deliberate case memory
- analysis jobs are launched ad hoc, without versioning or durable session history
- review is detached from the analysis workspace
- the app does not show whether the analyzer is actually improving over time

## Product Goal

Enable teams to create and evolve task-specific RCA analyzers that become progressively more aligned with SME behavior through:

- explicit taxonomy and policy definition
- domain knowledge ingestion
- approved case memory
- structured review workflows
- benchmark-driven iteration

## Non-Goals

- replacing inline root-cause editing in run/compare views
- removing the quick auto-analyze modal entirely
- introducing a fully autonomous general-purpose agent
- relying on fine-tuning as the primary learning mechanism

## Product Principles

1. Keep credentials separate from analyzer behavior.
2. Keep point-of-use editing in run/compare for speed.
3. Move durable RCA configuration and iteration into a dedicated workspace.
4. Make the analyzer's memory and reasoning support visible to users.
5. Version analyzer behavior and show which version produced each result.
6. Route uncertain or novel cases to humans instead of forcing bad predictions.
7. Measure quality with benchmarks and agreement, not intuition.

## Current State

### Existing Strengths

- Users can already label and correct root causes inline in run and compare views.
- Users can already launch quick LLM-based RCA from run and compare views.
- Users can already test prompt changes and inspect prompt preview in the playground UI.
- Approved corrections already exist and can feed later analysis.

### Existing Weaknesses

- The main auto-analyzer workflow is hidden inside a modal.
- The analyzer has no dedicated lifecycle or home in the product.
- Taxonomy, domain documents, and case memory are not modeled as first-class product objects.
- Review is correction-centric, not analyzer-operations-centric.
- There is no benchmark or health loop showing whether the analyzer is becoming more SME-like.

## Proposed Solution

Add a top-level workspace named `Root Cause Studio`.

`Root Cause Studio` becomes the system of record for RCA configuration, execution, review, and continuous improvement.

Run and compare pages remain important, but their role changes:

- they remain the best place for quick triage and inline edits
- they keep a lightweight quick-analyze entry point
- they deep-link into `Root Cause Studio` for full RCA workflows

## Information Architecture

Add a new top-level navigation item:

- `Root Cause Studio`

Studio contains the following primary sections:

- `Analysts`
- `Sessions`
- `Review Queue`
- `Benchmarks`

## Core Domain Objects

### Analyst

A named RCA profile owned by a user or team.

UI term: `Analyst`

Rationale: this is clearer and more controlled than exposing the term `Agent` in the product.

Fields:

- `id`
- `name`
- `description`
- `owner_user_id`
- `owner_team_id`
- `task_scope`
- `default_metric`
- `status` (`draft`, `active`, `archived`)
- `current_version_id`
- `created_at`
- `updated_at`

### Analyst Version

An immutable published configuration used for analysis sessions.

Fields:

- `id`
- `analyst_id`
- `version_label`
- `status` (`draft`, `published`, `archived`)
- `system_behavior_config`
- `taxonomy_config`
- `retrieval_config`
- `review_policy_config`
- `created_at`
- `published_at`

### Taxonomy

The root-cause ontology and decision policy.

Fields:

- root cause category
- root cause detail
- definition
- positive signals
- negative signals
- required evidence
- common confusions
- example boundary notes

### Knowledge Source

Domain knowledge attached to an analyst.

Examples:

- SME-authored notes
- glossary entries
- product rules
- uploaded docs
- tool behavior references
- URLs or imported content

Fields:

- `id`
- `analyst_id`
- `type`
- `title`
- `content`
- `source_url`
- `tags`
- `status` (`processing`, `ready`, `failed`, `stale`)

### Case Memory Entry

A curated, searchable precedent derived from approved corrections or manually authored examples.

Fields:

- `id`
- `analyst_id`
- `source_type` (`approved_correction`, `manual_example`, `benchmark_example`)
- `task`
- `root_cause`
- `root_cause_detail`
- `sme_note`
- `evidence_summary`
- `alternative_rejected`
- `metadata_tags`
- `quality_score`
- `active`

### Analysis Session

A launched RCA job against a run or selection of runs/items.

Fields:

- `id`
- `analyst_id`
- `analyst_version_id`
- `task`
- `run_scope`
- `filter_config`
- `status` (`queued`, `running`, `completed`, `failed`)
- `created_by`
- `created_at`
- `completed_at`

### Result Item

One analyzed item inside a session.

Fields:

- `session_id`
- `item_id`
- `run_id`
- `prediction`
- `prediction_detail`
- `prediction_note`
- `confidence`
- `support_summary`
- `alternative_considered`
- `review_status`
- `review_reason`

### Benchmark

A curated set of gold-labeled cases for evaluating analyzer quality.

Fields:

- `id`
- `name`
- `task`
- `owner`
- `status`
- `case_count`
- `agreement_metrics`

## Page Specs

## 1. Analysts Index

### Purpose

Browse, create, and manage RCA analyzers.

### Primary UI

- table or card grid of analysts
- `New Analyst` primary CTA
- filters: task, owner, status, health
- sort: updated recently, benchmark score, pending review count

### Display Fields

- analyst name
- task scope
- owner
- status
- current version
- last run time
- last benchmark score
- pending review count

### Row Actions

- open
- duplicate
- archive
- compare versions

### Empty State

Explain that analysts combine:

- taxonomy
- knowledge
- case memory
- review policy

CTA:

- `Create Your First Analyst`

## 2. New Analyst Wizard

### Purpose

Create a new analyzer profile with a guided setup flow.

### Steps

#### Step 1: Basics

- analyst name
- description
- task scope
- default metric
- intended users or team

#### Step 2: Taxonomy

- create categories
- create details under categories
- add definitions
- add evidence requirements
- add common confusions
- add boundary examples

#### Step 3: Knowledge

- upload docs
- add glossary entries
- paste rules or domain notes
- tag each source

#### Step 4: Memory

- choose approved corrections to seed the analyst
- inspect representative examples
- remove noisy examples
- mark certain examples as canonical

#### Step 5: Behavior

- confidence threshold
- low-confidence routing policy
- novelty handling
- retrieval defaults
- review defaults

#### Step 6: Test & Publish

- select 1-3 sample items
- run preview
- inspect retrieved support
- inspect output
- publish as version `v1`

### Notes

This replaces the current modal as the primary analyzer-configuration flow, while preserving the modal as a quick test tool.

## 3. Analyst Detail

### Purpose

Manage one analyst over time.

### Tabs

#### Overview

Show:

- summary
- owner
- task scope
- current version
- benchmark trend
- recent sessions

#### Taxonomy

Editable tree view for:

- categories
- details
- definitions
- evidence criteria
- confusion notes

#### Knowledge

List and preview all attached sources.

Per source:

- title
- tags
- status
- source type
- freshness
- remove or reprocess action

#### Memory

Search and curate case memory.

Capabilities:

- search by category, detail, tag, or text
- preview source correction
- promote examples
- disable noisy examples
- inspect quality flags

#### Evaluation

Show:

- agreement with human corrections
- agreement by category/detail
- edit rate
- low-confidence rate
- confusion pairs

#### Versions

Show version history and diffs.

Capabilities:

- compare versions
- inspect changed taxonomy
- inspect changed knowledge sources
- inspect changed retrieval/review settings
- restore an older version as draft

## 4. Launch Session

### Purpose

Run RCA as a first-class job.

### Inputs

- analyst
- analyst version
- task
- run or runs
- item filters
- metric
- threshold
- mode (`preview`, `sample test`, `full batch`)
- review routing policy

### Filters

- failed / passed / errors
- score threshold
- domain
- complexity
- root-cause status
- item selection

### Pre-Launch Summary

Show:

- selected analyst version
- estimated item count
- memory coverage warning
- benchmark freshness warning
- predicted review load

### Launch Actions

- `Preview Prompt`
- `Test on Sample`
- `Run Full Analysis`

## 5. Session Results

### Purpose

Review RCA output in a focused workspace.

### Layout

#### Left Pane: Item Queue

Filters:

- all
- accepted
- corrected
- rejected
- needs review
- low confidence
- novel
- weak support

Show for each item:

- item id
- category/detail
- confidence
- status badge

#### Center Pane: Item Detail

Show:

- input
- expected
- output
- error
- scores
- metadata
- predicted root cause
- detail
- note

#### Right Pane: Support Panel

Show:

- retrieved case memory
- retrieved knowledge snippets
- evidence summary
- alternative considered
- analyst version

### Per-Item Actions

- accept
- edit
- reject
- mark `needs SME review`
- add feedback note
- promote into memory candidate

### Result Badges

- `High confidence`
- `Low confidence`
- `Novel case`
- `Weak support`
- `Policy conflict`

## 6. Review Queue

### Purpose

Operational review center for analyzer outputs and memory candidates.

### Relationship to Current Reviews Page

The existing reviews page should evolve into this section.

The current page is correction-centric. The new section should be review-operations-centric.

### Primary Views

- pending analyzer results
- approved corrections awaiting memory decision
- low-confidence items
- novel items
- disagreements

### Filters

- analyst
- session
- task
- status
- confidence range
- novelty
- source type

### Bulk Actions

- approve
- reject
- route to SME
- exclude from memory
- approve into memory

## 7. Benchmarks

### Purpose

Measure whether the analyzer is improving toward SME-level behavior.

### Views

- benchmark set list
- run benchmark against analyst version
- compare benchmark performance across versions

### Metrics

- overall agreement
- agreement by category
- agreement by detail
- calibration by confidence bucket
- confusion matrix
- edit rate after AI suggestion

### Use

No analyst should be treated as trusted without benchmark visibility.

## Integration With Existing Pages

## Run Page

Keep:

- inline root-cause editing
- feedback editing
- quick auto-analyze action

Add:

- `Analyze In Studio`
- analyst/version badge on AI-generated results
- review-status chip

The run page remains the best place for quick point-of-use RCA.

## Compare Page

Keep:

- inline root-cause editing per run
- quick auto-analyze action
- cross-run failure inspection

Add:

- `Analyze In Studio`
- analyst/version badge
- status chip summarizing session outcome

The compare page remains the best place for exploratory failure analysis.

## Profile Page

Keep only:

- provider credentials
- model configuration
- connection test

Do not keep analyzer behavior here.

Analyzer behavior belongs to `Root Cause Studio`.

## State Model

### Analyst

- `draft`
- `active`
- `archived`

### Analyst Version

- `draft`
- `published`
- `archived`

### Knowledge Source

- `processing`
- `ready`
- `failed`
- `stale`

### Session

- `queued`
- `running`
- `completed`
- `failed`

### Result Item

- `suggested`
- `accepted`
- `corrected`
- `rejected`
- `escalated`

### Memory Candidate

- `pending`
- `approved`
- `excluded`

## Backend and Data Model Implications

Likely new entities:

- `analyst_profiles`
- `analyst_versions`
- `taxonomy_nodes`
- `knowledge_sources`
- `case_memory_entries`
- `analysis_sessions`
- `analysis_result_items`
- `benchmarks`

Existing `ReviewCorrection` should remain, but become one feeder into `case_memory_entries` rather than the entire learning system.

## Learning Operating Model

The system must **not** run a learning update automatically after every SME edit or approval.

Instead, the product must use an explicit Studio-driven learning workflow:

1. SMEs continue to label and correct root causes in run/compare views.
2. Corrections continue to be stored immediately.
3. Newly approved corrections are marked as `pending ingestion` for one or more analysts.
4. `Root Cause Studio` clearly shows that new learnings are available.
5. A user explicitly starts a `Learning Job` from Studio.
6. That job converts approved corrections into case memory, updates retrieval indices, and refreshes learned rules for the selected analyst/version draft.
7. The user reviews the learning outcome and publishes a new analyst version.

This model is preferred because:

- it avoids hidden behavior changes after every edit
- it gives teams control over when analyzer behavior changes
- it keeps analyzer versions auditable
- it makes "new information available" visible in the UI

## Concrete Implementation Plan

This section is the implementation plan to hand to the technical team.

## Product Behavior Summary

There are three distinct product workflows:

### 1. Correction Capture Workflow

This happens in existing run and compare pages.

User action:

- assign root cause
- correct AI root cause
- add optional note

System action:

- persist the correction immediately
- mark it as a candidate for future analyst learning
- do **not** change any analyst memory automatically

### 2. Learning Workflow

This happens only in `Root Cause Studio`.

User action:

- open an analyst
- see pending new learnings
- start a learning job

System action:

- gather newly approved corrections relevant to that analyst
- transform them into structured case memory
- update retrieval assets
- regenerate distilled rules
- produce a draft analyst version update
- present summary of what changed

### 3. Analysis Workflow

This happens from run/compare deep-link or from Studio launch.

System action:

- use only the currently published analyst version
- retrieve from the analyst's stored memory and rules
- run RCA
- store results with analyst/version provenance

This means:

- corrections are live immediately
- learning is explicit and batched
- analysis uses stable published behavior

## Backend Implementation

## Existing Tables to Keep

Keep using:

- `review_corrections`
- `runs`
- `run_items`
- `run_item_scores`

`review_corrections` remains the raw source of truth for SME actions.

## New Tables

### `analyst_profiles`

Purpose:

- stable top-level RCA analyzer object

Columns:

- `id`
- `name`
- `description`
- `owner_user_id`
- `owner_team_id`
- `task_scope`
- `default_metric`
- `status` (`draft`, `active`, `archived`)
- `current_published_version_id`
- `created_at`
- `updated_at`

### `analyst_versions`

Purpose:

- immutable versions used by analysis jobs

Columns:

- `id`
- `analyst_id`
- `version_number`
- `status` (`draft`, `published`, `archived`)
- `base_version_id`
- `taxonomy_snapshot_json`
- `retrieval_config_json`
- `review_policy_json`
- `knowledge_config_json`
- `created_by_user_id`
- `created_at`
- `published_at`

### `analyst_learning_candidates`

Purpose:

- bridge between approved corrections and analysts that may learn from them

This is the key table for the new operating model.

Columns:

- `id`
- `analyst_id`
- `correction_id`
- `candidate_status` (`pending`, `included`, `skipped`, `superseded`)
- `reason`
- `created_at`
- `resolved_at`

Behavior:

- when a correction is approved, candidate rows are created for matching analysts
- no memory changes happen yet
- Studio counts `pending` candidates and surfaces them to users

### `case_memory_entries`

Purpose:

- structured precedent memory for a specific analyst version draft

Columns:

- `id`
- `analyst_id`
- `source_correction_id`
- `source_learning_job_id`
- `task`
- `root_cause`
- `root_cause_detail`
- `summary_text`
- `evidence_text`
- `sme_note`
- `rejected_alternative`
- `metadata_tags_json`
- `embedding_vector`
- `quality_score`
- `active`
- `created_at`

### `policy_memory_entries`

Purpose:

- distilled rules learned from groups of approved corrections

Columns:

- `id`
- `analyst_id`
- `source_learning_job_id`
- `task`
- `root_cause`
- `root_cause_detail`
- `rule_text`
- `support_count`
- `confusion_labels_json`
- `active`
- `created_at`

### `learning_jobs`

Purpose:

- explicit Studio-triggered batch learning jobs

Columns:

- `id`
- `analyst_id`
- `base_version_id`
- `target_draft_version_id`
- `status` (`queued`, `running`, `completed`, `failed`, `cancelled`)
- `triggered_by_user_id`
- `candidate_count`
- `included_count`
- `skipped_count`
- `new_case_count`
- `new_rule_count`
- `summary_json`
- `error_text`
- `created_at`
- `started_at`
- `completed_at`

### `analysis_sessions`

Purpose:

- batch RCA execution record

Columns:

- `id`
- `analyst_id`
- `analyst_version_id`
- `task`
- `run_scope_json`
- `filter_config_json`
- `status`
- `created_by_user_id`
- `created_at`
- `completed_at`

### `analysis_result_items`

Purpose:

- item-level output for one session

Columns:

- `id`
- `session_id`
- `run_id`
- `item_id`
- `predicted_root_cause`
- `predicted_root_cause_detail`
- `predicted_note`
- `confidence`
- `retrieved_case_ids_json`
- `retrieved_rule_ids_json`
- `support_summary`
- `alternative_considered`
- `review_status`
- `review_reason`
- `created_at`

## Backend Jobs

There are two job families:

### A. Candidate Registration Job

Trigger:

- correction approval

Purpose:

- create `analyst_learning_candidates`
- do **not** update memory

Logic:

1. correction is approved
2. find analysts whose `task_scope` matches the correction task
3. create pending candidate rows

This should be lightweight and synchronous or near-synchronous.

### B. Learning Job

Trigger:

- user clicks `Apply New Learnings` in Studio

Purpose:

- batch-ingest pending candidates into analyst memory

Steps:

1. create `learning_jobs` row with status `queued`
2. create or reuse a draft `analyst_version`
3. load pending candidates for that analyst
4. fetch underlying approved corrections
5. normalize them into structured case summaries
6. generate embeddings
7. write/update `case_memory_entries`
8. cluster/group entries by task/category/detail
9. generate `policy_memory_entries`
10. mark candidates as `included` or `skipped`
11. write job summary
12. mark learning job `completed`

Important:

- this job updates the analyst draft state
- it must not silently mutate the currently published version

## Backend Services

## 1. Candidate Service

Responsibilities:

- map approved corrections to relevant analysts
- create `analyst_learning_candidates`
- compute pending counts

## 2. Memory Builder Service

Responsibilities:

- turn corrections into structured case memory

Input:

- `ReviewCorrection`

Output:

- `case_memory_entries`

Case summary should include:

- failure summary
- key evidence
- correct label
- incorrect alternative if available
- tags

## 3. Rule Distillation Service

Responsibilities:

- analyze groups of related case memories
- generate reusable rule summaries

Output:

- `policy_memory_entries`

## 4. Retrieval Service

Responsibilities:

- given a new run item, retrieve:
  - similar case memories
  - relevant policy rules
  - optionally hard negatives

The analyzer should retrieve from stored memory, not from the last few corrections.

## 5. Analysis Service

Responsibilities:

- build RCA inference context
- call the LLM
- parse result
- run verification
- persist session results

The analysis service must use:

- published analyst version only
- associated case memory and policy memory from that version lineage

## Backend API Plan

## Analyst APIs

- `GET /api/rca/analysts`
- `POST /api/rca/analysts`
- `GET /api/rca/analysts/{id}`
- `PATCH /api/rca/analysts/{id}`
- `POST /api/rca/analysts/{id}/archive`

## Version APIs

- `GET /api/rca/analysts/{id}/versions`
- `POST /api/rca/analysts/{id}/versions/draft`
- `POST /api/rca/versions/{id}/publish`
- `GET /api/rca/versions/{id}`

## Learning APIs

- `GET /api/rca/analysts/{id}/learning-summary`
- `GET /api/rca/analysts/{id}/learning-candidates`
- `POST /api/rca/analysts/{id}/learning-jobs`
- `GET /api/rca/learning-jobs/{job_id}`
- `GET /api/rca/learning-jobs/{job_id}/results`

### `GET /learning-summary` response should include:

- `pending_candidate_count`
- `last_learning_job_at`
- `last_learning_job_status`
- `published_version`
- `draft_version`
- `new_categories_detected`
- `new_details_detected`

This endpoint drives the "new information available" UI.

## Session APIs

- `POST /api/rca/sessions`
- `GET /api/rca/sessions`
- `GET /api/rca/sessions/{id}`
- `GET /api/rca/sessions/{id}/items`
- `POST /api/rca/sessions/{id}/cancel`

## Review APIs

- `POST /api/rca/result-items/{id}/accept`
- `POST /api/rca/result-items/{id}/correct`
- `POST /api/rca/result-items/{id}/reject`
- `POST /api/rca/result-items/{id}/escalate`

Existing correction APIs can remain for now, but Studio should gradually move to RCA-specific APIs.

## Frontend Implementation

## Root Cause Studio Entry Experience

Add a top-level nav item:

- `Root Cause Studio`

Landing page sections:

- analysts list
- pending learnings summary
- recent learning jobs
- recent RCA sessions

The landing page must immediately answer:

- which analysts exist
- which analysts have new information pending
- which analyst versions are published vs draft

## Frontend Page Requirements

## 1. Analysts Page

Each analyst card must show:

- name
- task scope
- published version
- draft version if present
- pending learning count
- last learning job status
- last RCA session status

Primary CTA:

- `Open`

Secondary CTA:

- `Apply New Learnings`

If pending learning count > 0, show a prominent badge:

- `12 New Learnings`

## 2. Analyst Detail Page

Tabs:

- `Overview`
- `Memory`
- `Learning`
- `Sessions`
- `Versions`

### Learning Tab

This is the most important new frontend surface.

It must show:

- pending approved corrections not yet ingested
- last completed learning job
- difference between published and draft versions
- CTA: `Apply New Learnings`

#### Learning tab panels

##### A. Pending Learnings

Columns:

- correction id
- task
- item id
- human root cause
- human detail
- source run
- approved at

##### B. Learning Summary

Show:

- pending count
- learned since last run
- potential new categories/details
- warnings for noisy or conflicting corrections

##### C. Apply Learnings Panel

Controls:

- include all pending
- exclude selected
- optional notes
- start learning job

Button:

- `Apply New Learnings`

##### D. Last Job Outcome

Show:

- new case memories created
- new policy rules created
- candidates skipped
- errors
- link to draft version

## 3. Learning Job Progress View

When a learning job is running, show:

- job status
- progress steps
- counts processed

Progress steps:

- collecting candidates
- building case memory
- generating embeddings
- distilling rules
- saving draft version

On completion, show:

- what changed
- link to inspect draft
- CTA to publish draft

## 4. Launch Session Page

Inputs:

- analyst
- published version
- run selection
- filters

Important:

- default to the published version
- draft version may be testable, but must be clearly marked as unpublished

Buttons:

- `Test Draft Version`
- `Run Published Version`

## 5. Session Results Page

Each result item must show:

- analyst name
- analyst version
- prediction
- confidence
- support summary
- reviewed or not reviewed

Right-side support panel must show:

- retrieved case memories
- retrieved policy rules

This makes the stored learning visible to users.

## Frontend Integration With Existing Pages

## Run Page

Keep current inline editing and quick auto-analyze.

Add:

- `Analyze in Studio`
- `Send to Analyst`
- analyst badge on AI-produced root causes

When a user corrects a root cause:

- save correction exactly as today
- optionally show a subtle toast:
  - `Saved. Available for analyst learning in Root Cause Studio.`

Do not imply the analyst already learned from it.

## Compare Page

Same integration pattern as run page:

- keep quick auto-analyze
- keep inline correction
- add deep-link into Studio with current task/run context

## Reviews Page

Current `reviews.html` should eventually become a Studio section or redirect into it.

Its conceptual role changes:

- from generic correction approval
- to RCA memory operations and review queue support

## Frontend State Model

For each analyst, frontend state must track:

- `published_version`
- `draft_version`
- `pending_learning_count`
- `last_learning_job`
- `learning_job_status`

For each correction displayed in Studio learning views:

- `approved_but_not_ingested`
- `already_ingested`
- `excluded_from_learning`

For each session:

- `used_published_version`
- `used_draft_version`

This is essential to avoid user confusion.

## End-to-End Interaction Flow

This is the required interaction between frontend and backend.

## Flow A: SME Corrects a Root Cause in Run Page

1. User edits a root cause in run or compare page.
2. Frontend calls existing correction persistence API.
3. Backend stores/updates `review_corrections`.
4. Reviewer later approves correction.
5. Backend creates `analyst_learning_candidates` rows for matching analysts.
6. Frontend Studio now shows pending learning count for those analysts.

Important:

- no case memory is created yet
- no rules are updated yet
- no published analyst behavior changes yet

## Flow B: User Applies New Learnings in Studio

1. User opens analyst detail page.
2. Frontend calls `GET /learning-summary` and `GET /learning-candidates`.
3. User clicks `Apply New Learnings`.
4. Frontend calls `POST /learning-jobs`.
5. Backend creates a learning job and returns job id.
6. Frontend polls `GET /learning-jobs/{id}`.
7. Backend processes candidates into case memory and policy memory tied to draft version.
8. Backend marks job completed.
9. Frontend shows job summary and link to draft version.
10. User may publish the draft version.

## Flow C: User Runs RCA Session

1. User launches RCA from Studio or deep-link from run/compare.
2. Frontend calls `POST /api/rca/sessions`.
3. Backend resolves the selected analyst version.
4. Backend retrieval service fetches stored case memory and policy memory.
5. Backend runs analysis and stores `analysis_result_items`.
6. Frontend shows results and support evidence.

## Publication Flow

Publication must be explicit.

1. Learning job updates draft version.
2. User inspects draft changes.
3. User clicks `Publish`.
4. Backend marks draft as published.
5. Backend updates `analyst_profiles.current_published_version_id`.

This ensures RCA behavior changes only when deliberately promoted.

## Technical Delivery Order

## Backend Phase 1

- create new RCA tables
- add candidate registration from approved corrections
- add analyst CRUD APIs
- add learning job APIs
- add draft/published version model

## Frontend Phase 1

- add `Root Cause Studio` nav entry
- add analysts list page
- add analyst detail page with learning tab
- add pending learnings badges
- add `Apply New Learnings` job flow

## Backend Phase 2

- implement memory builder
- implement rule distillation
- implement retrieval service over stored memory
- implement RCA sessions using analyst versions

## Frontend Phase 2

- add launch session page
- add session results page
- add retrieved support panel
- add version inspection and publish flow

## Backend Phase 3

- add benchmark tables and APIs
- add quality metrics and version comparison support

## Frontend Phase 3

- add benchmark UI
- add analyst health views
- add version comparison UI

## UX Positioning of the Current Modal

The current playground modal should stay, but be repositioned as:

- `Quick Analyze`
- `Quick Test`
- `Prompt Preview`

It should not remain the primary place where analyzer systems are created and managed.

## Suggested Rollout

## Phase 1

- add `Root Cause Studio`
- add analysts index
- add new analyst wizard
- add launch session flow
- add session results page
- deep-link from run/compare into Studio
- move reviews navigation under Studio

## Phase 2

- add knowledge source management
- add case memory curation
- add versioning and publish flow
- show retrieved support in results

## Phase 3

- add benchmarks
- add analyst health views
- add version comparison
- add shared/team analysts
- add governance workflows

## MVP Recommendation

If scope must be constrained, build this MVP:

- Analysts index
- New analyst wizard
- Launch session page
- Session results page
- Deep-link from run/compare
- Review Queue integrated into Studio

This is the smallest useful version that turns RCA into a coherent product area rather than a modal plus a correction inbox.
