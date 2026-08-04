# LLM analyzer branch changes

This document records the final behavior of the `llm_analyzer` branch relative to
the repository's local `upstream/main` reference (`6fa6883`). It is a developer
and operator handoff for the analyzer work; the [Platform User Guide](../packages/platform/docs/USER_GUIDE.md)
contains the shorter end-user workflow.

## Scope

The branch turns root-cause analysis into a project-scoped workflow. Analysis can
now use project context, selected reference documents, versioned analysis rules,
and a project-owned LLM connection. A run may be analyzed for several metrics at
once, with an independent diagnosis and review candidate for each item/metric
pair.

## User-facing workflow

The platform exposes a first-class Auto-analysis page at:

- `/projects/<project-slug>/analysis` for project-wide analyzer context and run selection;
- `/projects/<project-slug>/runs/<run-id>/analyzer` for a project-scoped run; and
- `/run/<run-id>/analyzer` for the legacy run route.

The page is split into two scopes:

1. **Project context** — edit the business description, manage analysis rules,
   generate rules from project material, and manage the shared document library.
2. **Run analysis** — choose a run and one or more metrics, filter matched items,
   preview the rendered prompt, test up to three items without saving, and run the
   analysis with progress reporting.

Project managers can edit context and rules. Run owners and project managers can
spend the configured LLM connection on analysis. Project members can view the
analysis workspace when they can view the run.

## Analyzer behavior

### Prompt context

The analyzer builds a bounded, metric-specific prompt from:

- the project name, task, dataset, evaluated model, and active analysis rules;
- the selected metric's score, label, explanation, metadata, direction, and pass threshold;
- the input, expected output, actual output, error, and selected item metadata;
- useful trace evidence, including reconstructed LLM messages, reasoning, tool
  calls, tool results, and error events; and
- selected reference documents, treated as evidence rather than instructions.

The playground supports nested field mapping, selected paths, metadata fields, and
custom variables in additional instructions. Secret-like keys such as API keys,
tokens, credentials, passwords, and authorization values are redacted before any
item or metric context is sent to the analyzer. Redundant telemetry and trace
values that duplicate the item record are omitted.

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
minimize metrics.

Results are stored in `item_metadata.metric_analyses[metric_name]`. A compatible
item-level summary is retained for older dashboard consumers and identifies the
metric that supplied it. The run payload also exposes metric-scoped review
candidate IDs and statuses.

After a batch, category, detail, and legacy solution labels are canonicalized across
the batch. Deterministic case/whitespace/inflection variants are collapsed locally;
the analyzer makes one joint LLM mapping pass only when semantic consolidation is
needed. A low-reduction detail result gets one bounded quality retry. Invalid or
timed-out aggregation never discards the raw item diagnoses.

### Project rules

Rules are short title/instruction pairs describing business requirements,
invariants, decision logic, and evidence checks. They are guidance for diagnosis,
not a list of root-cause answers. The rule-writer agent can use any combination of
selected documents and approved correction examples.
Generated rules are returned as a draft; they are never silently made production.

The rule editor preserves stable rule IDs so edits can be compared. Identical
edits reuse the current draft, while an explicit “create version” action creates a
new snapshot even when the content is unchanged.

### Reference documents

The shared project library accepts `.pdf`, `.docx`, `.txt`, `.text`, `.md`,
`.markdown`, `.html`, `.htm`, `.csv`, `.json`, `.yaml`, `.yml`, `.log`, and `.rst`.
Each upload is limited to 10 MiB and extracted text is limited to 40,000
characters per document. The analyzer prompt accepts at most eight selected
documents and 80,000 reference characters in total.

Text, Markdown, CSV, JSON, YAML, log, and RST files are decoded as text; DOCX
paragraphs are extracted from the document XML; HTML script/style content is
discarded; and scanned PDFs require OCR before upload. Filenames are reduced to a
safe basename and extracted text is normalized before storage.

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

## Rule release lifecycle

Every new project starts with one editable `v1` analysis-rule version. A project
manager can:

1. edit the current draft or create a draft from a prior version;
2. compare rule identities and instructions between versions;
3. publish a non-empty draft, which makes it immutable and records a content hash;
4. point an alias such as `production` at a published version; and
5. activate a published version for future analyzer requests.

Published versions cannot be edited. Run owners/project managers may delete a live
version subject to the “at least one live version” guard; descendants are detached
when necessary and an active production version is re-resolved. For records already
marked deleted, an admin can use the restore endpoint, and only an admin can
permanently remove them. Permanent removal is blocked while aliases or descendant
versions still reference the record. The resolved rule-version ID is saved with
each AI analysis result.

The version endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/runs/{run_id}/analysis-rule-versions` | List versions, status, aliases, lineage, hashes, and production pointer. |
| `GET` | `/api/runs/{run_id}/analysis-rule-lineage` | Return the parent-linked history. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions` | Create a mutable draft, optionally from a version or alias. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{ref}:publish` | Publish a draft and optionally set an alias. |
| `POST` | `/api/runs/{run_id}/analysis-rule-aliases/{alias}` | Point an alias at a published version. |
| `GET` | `/api/runs/{run_id}/analysis-rule-versions/{ref}:compare?base={ref}` | Return added, removed, changed, and unchanged rules. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{id}/activate` | Move `production` to a published version. |
| `DELETE` | `/api/runs/{run_id}/analysis-rule-versions/{id}` | Delete a live version subject to dependency guards. |
| `POST` | `/api/runs/{run_id}/analysis-rule-versions/{id}/restore` | Admin-only restore of a deleted version. |
| `DELETE` | `/api/runs/{run_id}/analysis-rule-versions/{id}/permanent` | Admin-only permanent deletion. |

## Analysis and document endpoints

All analysis and correction endpoints use the UI-session principal. The primary
analysis endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs/{run_id}/analyze` | Run analysis and persist results. Supports filters, metric selection, concurrency `1..20`, and `connection_id`. |
| `POST` | `/api/runs/{run_id}/analyze-stream` | Same operation with newline-delimited progress events. |
| `POST` | `/api/runs/{run_id}/analyze-preview` | Render the exact messages for one item without an LLM call. |
| `POST` | `/api/runs/{run_id}/analyze-test` | Analyze one to three items without saving; returns results and messages. |
| `GET` | `/api/runs/{run_id}/analysis-config` | Return project context, connection choices, catalogs, counts, and active rule version. |
| `GET` | `/api/runs/{run_id}/analysis-documents` | List project documents with run-specific selection state. |
| `POST` | `/api/runs/{run_id}/analysis-documents` | Extract, store, and select an uploaded document. |
| `PATCH` | `/api/runs/{run_id}/analysis-documents/{id}` | Select or deselect a project document for the run. |
| `DELETE` | `/api/runs/{run_id}/analysis-documents/{id}` | Remove a document from the project library. |
| `PATCH` | `/api/runs/{run_id}/analysis-context` | Save the working rule draft/version. |
| `POST` | `/api/runs/{run_id}/analysis-rules/infer` | Generate a draft ruleset from selected sources. |
| `GET` | `/api/runs/{run_id}/corrections` | Read approved correction records available as rule-writer evidence. |

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

Approved corrections are used by the rule-writer agent as evidence. They are not
inserted as few-shot examples into the per-item analyzer prompt. This separation
prevents a prior reviewer label from becoming an instruction or leaking snapshots
from another item into the current diagnosis.

## Database migrations

Run `alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head`
before starting a deployment. The branch adds the following revisions and merges
them into one upgrade head (`0034_draft_rule_activation`):

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
migrations, project access, CLI summaries, dashboard routes, metric-aware
breakdowns, prompt redaction/context projection, reasoning-model parsing, and
semantic aggregation. UI changes continue to use the design-language enforcement
test described in `AGENTS.md`.
