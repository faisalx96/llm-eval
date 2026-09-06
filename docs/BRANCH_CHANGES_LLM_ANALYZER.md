# LLM analyzer branch changes

This document records the final behavior of the `llm_analyzer` branch relative to
the repository's local `upstream/main` reference (`6fa6883`). It is a developer
and operator handoff for the analyzer work; the [Platform User Guide](../packages/platform/docs/USER_GUIDE.md)
contains the shorter end-user workflow.

## Scope

The branch turns root-cause analysis into a project-scoped workflow. Analysis can
use enabled reference documents, versioned production rules, a versioned
diagnosis-category catalog, editable project system prompts, native trace
evidence, and a project-owned LLM connection. A run may be analyzed for several
metrics at once, with an independent diagnosis and review candidate for each
item/metric pair. The same first-class page also provides a project diagnosis
dashboard and run comparison.

## User-facing workflow

The platform exposes a first-class Auto-analysis page at:

- `/projects/<project-slug>/analysis` for project-wide analyzer context and run selection;
- `/projects/<project-slug>/runs/<run-id>/analyzer` for a project-scoped run; and
- `/run/<run-id>/analyzer` for the legacy run route.

The page exposes five tabs:

| Tab | Scope | Implemented surface |
| --- | --- | --- |
| **Dashboard** | Project | Saved-diagnosis filters, summary statistics, category distribution, direction-aware score context, run/category view, occurrence map, and run comparison. |
| **Analyze run** | Run | Metric selection, context switches, request instructions, nested input mapping, failed-target filtering, exact item/metric selection, prompt preview, one-target test, and background analysis. A project-only route shows a run-selection state. |
| **Diagnosis categories** | Project | Category search/add/remove, taxonomy guidance, reusable details, approved-example coverage, and full-snapshot save. |
| **Production rules** | Project | Rule search/editing, draft/publish/production lifecycle, lineage drawer, compare/merge, generation, delete/restore, and provenance. |
| **Documents** | Project | Shared upload library, project-enabled state, prompt-budget counters, and confirmed removal. |

Persistent system prompts are intentionally outside this page. Project managers
and admins edit the analyzer, aggregator, and rules-writer prompts under **Project
Settings → AI system prompts**. The Auto-analysis page contains only request-level
instructions and field mapping.

Project managers can edit category catalogs, rules, documents, connections, and
system prompts. Run owners and project managers can spend the configured LLM
connection on analysis. Project members can view the analysis workspace when they
can view the run.

### Diagnosis dashboard

`Dashboard` opens by default on the project route. It filters saved diagnoses by
date range, run, task, dataset, model, metric, category, detail, source, and review
status. Searchable multiselect filters retain explicit empty selections instead of
silently reverting to “all.” The summary strip reports diagnosis occurrences,
affected run/item pairs, categories, the most repeated category, and failure
coverage.

The page renders a category distribution, direction-aware run score context, a
stacked run/category view, and an occurrence grid. The occurrence grid requests
500 records per page until the complete filtered result has been loaded; every
dot is focusable/selectable and drives an inspector with the run, item, category,
detail, metric, score, source, note, and run link.

Users can select two to eight runs. The comparison endpoint returns a baseline,
direction-aware improvement state, score compatibility, category/metric matrices,
run summaries, and change data. The UI can group by category, run, or metric and
switch between occurrence count, share, and average score while preserving its
controls across filtered rerenders.

## Analyzer behavior

### Prompt context

The analyzer builds a bounded, metric-specific prompt from:

- the project name, task, dataset, evaluated model, and active analysis rules;
- the selected metric's score, label, explanation, metadata, direction, and pass threshold;
- the input, expected output, actual output, error, and selected item metadata;
- an organized view of the native trace span payload already used by the trace
  viewer, with agent and evaluation sections; and
- selected reference documents, treated as evidence rather than instructions.

The playground supports nested field mapping, selected paths, metadata fields, and
custom variables in additional instructions. Secret-like keys such as API keys,
tokens, credentials, passwords, and authorization values are redacted before any
item or metric context is sent to the analyzer. The analyzer organizes the same
serialized span payload as the trace viewer into agent and evaluation sections,
emitting only new message/thinking content at each step, subject to the
analyzer's context limit.

The default system prompt asks only for a diagnosis JSON object containing
`root_cause`, `root_cause_detail`, `confidence`, and `root_cause_note`. It does not
ask the model to produce a remediation or recommendation. Custom prompts remain
supported; omitted analyzer context is appended so a custom template cannot
silently discard required evidence. Confidence is bounded and conservatively
calibrated against the quality of the returned category, detail, and note.

Reasoning-model responses are supported when the provider puts the answer in a
reasoning field or returns an empty content field. The saved result includes model,
prompt hash, provider request ID, and token-usage fields when the provider returns
them.

### Metric-aware targeting and persistence

`POST /api/runs/{run_id}/analyze` accepts either `metric` or `metrics[]`. A target
is an item/metric pair, so one item can have different diagnoses for `accuracy`,
`format`, or any other run metric. `only_unanalyzed` is applied independently per
metric. Failed, passed, error, explicit item, complexity, domain, root-cause, and
threshold filters are applied before analysis; metric direction is respected for
minimize metrics. The optional `limit` selects the most severe matching items;
all selected metric targets for each selected item are retained.

Results are stored in `item_metadata.metric_analyses[metric_name]`. A compatible
item-level summary is retained for older dashboard consumers and identifies the
metric that supplied it. The run payload also exposes metric-scoped review
candidate IDs and statuses.

The dedicated page starts analysis through a persisted background job. It polls
the job, resumes an active job after navigation, exposes cancellation, and applies
completed results back to the local run snapshot before refreshing target counts
and action availability. `analyze-test` accepts up to three item IDs at the API
boundary, while the current page intentionally sends the one selected item/metric
target.

After a batch, category, detail, and legacy solution labels are canonicalized across
the batch. Deterministic case/whitespace/inflection variants are collapsed locally;
the analyzer makes one joint LLM mapping pass only when semantic consolidation is
needed. A low-reduction detail result gets one bounded quality retry. Invalid or
timed-out aggregation never discards the raw item diagnoses.

### Diagnosis-category catalog

Project diagnosis categories are stored as immutable full-snapshot versions. A
legacy project without a saved snapshot is exposed as synthetic read-only `v0`.
Every saved snapshot contains stable category entries, taxonomy guidance, detail
maps, active/archived state, `max_root_cause_categories`, a content hash, and
lineage/restore provenance. Manager saves use an expected revision, normalized
no-op detection, and an HTTP 409 conflict response containing the current
catalog. Restoring a historic snapshot creates a new version instead of mutating
history.

Analysis requests may pin `category_catalog_version_id` (or the compatible
numeric `config.category_catalog_version`). Otherwise the active project snapshot
is resolved. The resolved numeric version and ID are stored on every metric
analysis. The current category tab edits and saves the active snapshot; catalog
history, restore, and request pinning are API-only surfaces for now.

### Project rules

Rules are short title/instruction pairs describing business requirements,
invariants, decision logic, and evidence checks. They are guidance for diagnosis,
not a list of root-cause answers. The rule-writer is explicitly instructed to write
for the downstream root-cause analyzer: rules must explain how domain facts and
observed evidence help identify or distinguish failure mechanisms and map those
mechanisms to a root-cause category/detail when the evidence supports that mapping.
They must not be judge rubrics, pass/fail criteria, evaluated-agent instructions, or
remediation advice.
The rule-writer can use any combination of selected documents and approved correction
examples.
Generated rules are returned as a draft; they are never silently made production.
Generation is append-only: it includes the current rules as writer context, filters
redundant results, and never edits or removes an existing rule. When the selected
version is already a draft, new rules are added to that draft; otherwise a child
draft carries the selected rules forward and adds only the new rules.

The rule editor preserves stable rule IDs so edits can be compared. Identical
edits reuse the current draft, while an explicit “create version” action creates a
new snapshot even when the content is unchanged.

Drafts can merge another live version. The merge preview separates non-conflicting
changes from rule-identity conflicts, allows per-conflict resolution, and records
all merge parents in the version graph. Opening the Rules tab renders the resolved
selected version immediately, including its rules and provenance, rather than
waiting for a later interaction to refresh the editor.

### Reference documents

The shared project library accepts `.pdf`, `.docx`, `.txt`, `.text`, `.md`,
`.markdown`, `.html`, `.htm`, `.csv`, `.json`, `.yaml`, `.yml`, `.log`, and `.rst`.
Each upload is limited to 10 MiB. The normal prompt-safe representation is
40,000 characters per document, while the explicit full-content choice can
retain up to 200,000 characters. A document above the prompt-safe limit first
returns a confirmation response; the caller must choose `truncate` or `full`.
The analyzer prompt accepts at most eight selected documents and 80,000
reference characters in total, and then applies a final 640,000-character
message budget before calling the provider.

The item analyzer retains up to 400,000 characters of formatted trace, within
a 500,000-character item-context budget. Input, expected output and actual
output each retain their existing 20,000-character cutoff. Trace content beyond
the limit is still shortened with an omission notice; raising the limit does
not summarize or process unlimited history. A provider context-size rejection
can retry with the existing 160,000-character fallback ceiling. These limits
count characters, not model tokens.

Rule inference has separate source budgets: documents and approved examples are
packed into 256,000-character source patches and each writer request is capped
at 320,000 characters. Documents are processed first and approved examples are
then applied as a second bounded update; additional patches are sequential
updates. No source is silently dropped. The UI exposes these counters and the
backend returns `inference_stats` with call and patch counts.

Text, Markdown, CSV, JSON, YAML, log, and RST files are decoded as text; DOCX
paragraphs are extracted from the document XML; HTML script/style content is
discarded; and scanned PDFs require OCR before upload. Filenames are reduced to a
safe basename and extracted text is normalized before storage.

Documents have a project-level enabled state. The Documents tab controls that
state; the Analyze run tab exposes one request-level switch that includes or
excludes the enabled set. This replaces the older documentation model in which
each run selected documents independently.

PDF extraction runs in a bounded child process: at most 100 pages, 4 MiB of
decompressed content, 5 seconds, and 256 MiB of worker address space. DOCX XML is
limited to 4 MiB and unsafe ZIP compression ratios are rejected. The service fails
closed when the host cannot apply the required PDF resource limits.

## Project LLM connections

LLM provider settings are project-scoped and are managed from **Project Settings →
LLM Connections**, not from the global profile. A project may have multiple named
connections, one default connection, and an explicit connection override per
analysis request. Each connection stores a model and OpenAI-compatible base URL;
the API key is encrypted at rest and only a last-four-character hint is returned.
The settings page can test a connection with a short probe.

The platform validates the base URL before saving and again at request time. By
default it requires `http` or `https`, rejects credentials/fragments, blocks
non-public IP addresses, resolves DNS off the event loop, pins the validated
address for the socket connection, disallows Unix sockets, and does not follow
redirects. Set `QYM_ALLOW_PRIVATE_LLM_BASE_URLS=true` only for trusted local
providers in a controlled deployment.

OpenAI-compatible calls retry narrowly when a provider rejects `max_tokens` in
favor of `max_completion_tokens`, or rejects `response_format`; unrelated provider
errors are not retried as compatibility fallbacks.

## Project analysis prompts

The project settings page manages three independent system prompts:
`llm_analyzer_system_prompt`, `aggregator_system_prompt`, and
`rules_writer_system_prompt`. Read/write endpoints require a project manager or
admin, normalize empty/oversized values, and return built-in defaults so each
prompt can be reset independently. Migration `0041_analysis_prompts`
stores the project overrides. Request-specific instructions remain in the run
workspace and do not overwrite these persistent system prompts.

## Rule release lifecycle

Every new project starts with one editable `v1` analysis-rule version. A project
manager can:

1. edit the current draft or create a draft from a prior version;
2. compare rule identities and instructions between versions;
3. preview and apply a merge from another live version, resolving conflicts;
4. publish a non-empty draft, which makes it immutable and records a content hash;
5. point an alias such as `production` at a published version; and
6. activate a published version for future analyzer requests.

Published versions cannot be edited. Run owners/project managers may delete a live
version subject to the “at least one live version” guard; descendants are detached
when necessary and an active production version is re-resolved. For records already
marked deleted, an admin can use the restore endpoint, and only an admin can
permanently remove them. Permanent removal is blocked while aliases or descendant
versions still reference the record. The resolved rule-version ID is saved with
each AI analysis result.

The version endpoints are:

The same version lifecycle is available without selecting a run through the
project-scoped prefix `/api/projects/{project_slug}`. These endpoints use the
project's active rules and permissions directly, so a project with zero runs
can still maintain its rule library.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/runs/{run_id}/analysis-rule-versions` | List versions, status, aliases, lineage, hashes, and production pointer. |
| `GET` | `/api/runs/{run_id}/analysis-rule-lineage` | Return the parent-linked history. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions` | Create a mutable draft, optionally from a version or alias. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{ref}:publish` | Publish a draft and optionally set an alias. |
| `POST` | `/api/runs/{run_id}/analysis-rule-aliases/{alias}` | Point an alias at a published version. |
| `GET` | `/api/runs/{run_id}/analysis-rule-versions/{ref}:compare?base={ref}` | Return added, removed, changed, and unchanged rules. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{target}:merge` | Preview or apply a source-version merge into a draft, with explicit conflict resolutions. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{id}/activate` | Move `production` to a published version. |
| `DELETE` | `/api/runs/{run_id}/analysis-rule-versions/{id}` | Delete a live version subject to dependency guards. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{id}/restore` | Admin-only restore of a deleted version. |
| `DELETE` | `/api/runs/{run_id}/analysis-rule-versions/{id}/permanent` | Admin-only permanent deletion. |

## Analysis and document endpoints

All analysis and correction endpoints use the UI-session principal. The primary
analysis endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs/{run_id}/analyze` | Run analysis and persist results. Supports filters, metric selection, an item `limit`, concurrency `1..20`, and `connection_id`. |
| `POST` | `/api/runs/{run_id}/analyze-stream` | Same operation with newline-delimited progress events. |
| `POST` | `/api/runs/{run_id}/analysis-jobs` | Start the persisted background job used by the page. |
| `GET` | `/api/runs/{run_id}/analysis-jobs/active` | Return the active resumable job for the run, if any. |
| `GET` | `/api/runs/{run_id}/analysis-jobs/{job_id}` | Poll job phase, progress, results, and failure information. |
| `POST` | `/api/runs/{run_id}/analysis-jobs/{job_id}/cancel` | Request cancellation of an active job. |
| `POST` | `/api/runs/{run_id}/analyze-preview` | Render the exact messages for one item without an LLM call. |
| `POST` | `/api/runs/{run_id}/analyze-test` | Analyze one to three items without saving; returns results and messages. |
| `GET` | `/api/runs/{run_id}/analysis-config` | Return project context, connection choices, catalogs, counts, and active rule version. |
| `GET` | `/api/runs/{run_id}/analysis-documents` | List the run project's documents and project-level enabled state. |
| `POST` | `/api/runs/{run_id}/analysis-documents` | Extract, store, and enable an uploaded project document. |
| `GET` | `/api/runs/{run_id}/analysis-examples` | Page and filter approved examples for explicit rule-writer selection. |
| `PATCH` | `/api/runs/{run_id}/analysis-documents/{id}` | Enable or disable a document for project analyzer prompts. |
| `DELETE` | `/api/runs/{run_id}/analysis-documents/{id}` | Remove a document from the project library. |
| `PATCH` | `/api/runs/{run_id}/analysis-context` | Save the working rule draft/version. |
| `POST` | `/api/runs/{run_id}/analysis-rules/infer` | Generate a draft ruleset from selected sources. |
| `GET` | `/api/runs/{run_id}/corrections` | Read approved correction records available as rule-writer evidence. |

Project dashboard and category-catalog endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/projects/{project_slug}/root-cause-dashboard` | Return filtered summary, facets, grouped distributions, score context, and trends. |
| `GET` | `/api/projects/{project_slug}/root-cause-dashboard/occurrences` | Page matching occurrence-level diagnoses for the dot map. |
| `GET` | `/api/projects/{project_slug}/root-cause-dashboard/compare` | Compare two to eight selected runs with a baseline and optional score metric. |
| `GET` | `/api/projects/{project_slug}/analysis-category-catalog` | Read the active or requested immutable category snapshot. |
| `GET` | `/api/projects/{project_slug}/analysis-category-catalog/versions` | List catalog history, including synthetic legacy `v0`. |
| `PUT` | `/api/projects/{project_slug}/analysis-category-catalog` | Manager-only full-snapshot save with optimistic conflict detection. |
| `POST` | `/api/projects/{project_slug}/analysis-category-catalog/versions/{id}:restore` | Restore a historic snapshot as a new active version. |

Project-scoped document, example, context, rule-version, lineage, publish,
compare, merge, alias, activate, delete, restore, and permanent-delete endpoints
mirror the run-prefixed rule/document APIs under `/api/projects/{project_slug}`.
Persistent system prompts use `GET /v1/projects/{project_id}/analysis-prompts`
and `PUT /v1/projects/{project_id}/analysis-prompts`.

The project connection endpoints are under
`/v1/projects/{project_id}/llm-connections`: list, create, update, delete, set
default, and test. A new connection becomes default when it is the project's
first connection; deleting the default promotes the oldest remaining connection.

## Corrections and review history

AI analysis creates a pending candidate. Human edits are persisted as revisioned
state changes with input, expected, output, and score snapshots. Corrections can be
scoped to an item or to an item/metric pair. Approving a metric analysis can
materialize a legacy saved metric result into a review candidate. Approving a newer
candidate supersedes the older active candidate; reset returns it to pending; and
“delete” removes it from the active queue while retaining rejected history.

Approved corrections are used by the rule-writer as evidence. They are not
inserted as few-shot examples into the per-item analyzer prompt. This separation
prevents a prior reviewer label from becoming an instruction or leaking snapshots
from another item into the current diagnosis. For rule inference, each approved
correction is projected into these fields: `input`, `expected`, `output`,
`previous_ai_root_cause`, `previous_ai_root_causes`,
`approved_root_cause`, `approved_root_causes`, `approved_detail`, and
`reviewer_reasoning`.
Solutions, solution notes, scores, trace data, item/run identifiers, and review
metadata are not included in that payload. The approved human diagnosis/detail/note
are treated as reviewed evidence; previous AI fields are historical hypotheses.
Run-scoped inference uses active approved corrections for the run's task and project;
project-scoped inference uses all active approved corrections in the project.

## Database migrations

Run `alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head`
before starting a deployment. The branch adds the following revisions and merges
them into one upgrade head (`0041_analysis_prompts`):

| Revision | Change |
| --- | --- |
| `0026_expand_correction_details` | Store AI and human detail text without the old 200-character limit. |
| `0027_analyzer_document_library` | Add project documents and per-run selection records. |
| `0028_project_analyzer_roles` | Add the interim project analyzer-role storage used by the migration path. |
| `0029_metric_scoped_corrections` | Add `metric_name` and metric-scoped active-candidate indexes. |
| `0030_analysis_rule_versions` | Replace legacy analyzer roles with versioned project rules and migrate existing rules. |
| `0031_repair_rule_activation` | Repair activation columns and the active-version index for early `0030` databases. |
| `0032_rule_release_lifecycle` | Add draft/published/archived metadata, lineage, content hashes, and aliases. |
| `0033_merge_migration_heads` | Merge the analyzer branch with the run metric-analysis migration branch. |
| `0034_draft_rule_activation` | Allow unpublished drafts to have no activation timestamp. |
| `0035_rule_merge_lineage` | Add merge-parent edges and merge-base provenance for rule-version lineage. |
| `0036_document_enabled` | Replace per-run document selection with project-level analyzer inclusion. |
| `0037_remove_project_desc` | Remove the obsolete project description from analyzer context. |
| `0038_multi_root_cause_categories` | Persist multiple root-cause categories per analysis/review candidate. |
| `0039_category_taxonomy` | Store category taxonomy guidance with review candidates. |
| `0040_category_catalog` | Add immutable project category-catalog snapshots, lineage, restore provenance, and active-version uniqueness. |
| `0041_analysis_prompts` | Add editable project-scoped analyzer, aggregator, and rules-writer system prompts. |

## SDK, CLI, examples, and build changes

- `qym analyze run <run_id>` now calls the implemented `/api` route, reports
  item-metric counts, and limits concurrency to `1..20`. `qym analyze summary`
  counts metric analyses and falls back to the legacy item summary when needed.
- The dependency-free SDK platform client URL-encodes run IDs before analysis
  requests. Evaluator imports preserve judge-input validation behavior.
- The platform package adds `pypdf` for bounded PDF extraction. The Docker dev
  stage copies SDK README/version metadata before dependency installation so
  editable builds resolve package metadata correctly.
- The Text-to-SQL example adds three business-context documents and now evaluates
  execution accuracy, SQL validity, relevance, and toxicity with multi-column CSV
  input mapping.

## Verification coverage

The branch adds or extends tests for document extraction and archive limits, PDF
resource failures, LLM endpoint validation and DNS pinning, OpenAI compatibility
fallbacks, metric-scoped permissions and review history, rule lifecycle and
migrations, project access, category-catalog conflicts and restore, custom system
prompts, CLI summaries, root-cause dashboard/compare APIs, metric-aware
breakdowns, prompt redaction/context projection, reasoning-model parsing, and
semantic aggregation.

The deterministic browser release gate serves the production analyzer assets and
exercises the five-tab project/run routes, exact target selection, direction copy,
retry/no-connection/zero-target states, keyboard tabs, narrow and RTL layout,
dashboard filter serialization, paged occurrence loading, run comparison, console
errors, and automated serious/critical accessibility checks. The separate
[Auto-analysis release audit](internal/Auto%20Analyze%20Audit.md) records the
manual visual and production-scale gates and the verified remediation of all 14
design-language contradictions. `test_design_language.py` and the analyzer-specific
static contract both guard the repaired component, token, scope, and page-renderer
choices.

The final Auto-analysis layout refinement aligns the page hero and tab strip to
the same centered edges as the configuration cards, removes the repetitive
`Project setting` tags and the redundant Production-rules information marker,
and moves **Max categories per item** into the Analyze run **Targets** controls.
That value is sent with the run request, while category-catalog saves preserve
the loaded project default.
