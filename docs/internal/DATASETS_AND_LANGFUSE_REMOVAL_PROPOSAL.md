# First-Class Datasets And Langfuse Removal

> **Status (2026-07-04): in-progress proposal — not fully implemented.** Langfuse
> metadata still flows through `qym_platform/api/ingest.py` and `api/runs.py`, and
> `.env.template` still lists LANGFUSE_* variables. Treat this as a plan, not as
> documentation of current behavior.

## Summary

qym should make datasets a native platform concept and remove Langfuse from the SDK runtime path. Today Langfuse is used for two separate concerns:

- dataset storage and dataset item lookup when `Evaluator(dataset="name")` receives a string
- trace export, score export, and dataset-run item linking when Langfuse credentials are present

The replacement should split these concerns cleanly:

- qym platform owns datasets, dataset versions, and dataset item identity
- qym SDK loads datasets from local files or the qym platform
- qym SDK/platform tracing remains OpenTelemetry/OpenInference based, with spans streamed to the qym platform through the existing event stream
- Langfuse imports become a one-time migration path, not a runtime dependency

## Goals

- Remove `langfuse` from `packages/sdk/pyproject.toml` required dependencies.
- Preserve the common user workflow: `Evaluator(..., dataset="qa-v1", metrics=[...])`.
- Add platform-backed dataset CRUD, versioning, upload, download, and item listing.
- Make dataset management a first-class platform UX: browsing, editing, labels, production promotion, rollback, lineage, and item-level run history.
- Keep CSV/local datasets working offline.
- Keep item identity stable across local CSV, imported datasets, platform datasets, run comparisons, and re-runs.
- Replace Langfuse trace/deep-link metadata with qym platform trace URLs and stored spans.
- Keep the migration incremental enough that existing run ingestion and dashboards keep working.

## Non-Goals

- Rebuild every Langfuse feature. qym needs evaluation datasets, runs, scores, and traces, not prompt management or observability dashboards outside evaluation review.
- Require platform connectivity for all evaluations. Local CSV/JSONL evaluation should continue to work.
- Keep transparent Langfuse compatibility forever. A migration window is fine; permanent runtime coupling is not.

## Current State

SDK:

- `packages/sdk/qym/core/dataset.py` has `LangfuseDataset` and `CsvDataset`.
- `Evaluator(dataset=str)` means "load this named dataset from Langfuse".
- `Evaluator` initializes Langfuse when credentials exist, then uses it for dataset loading, `create_score`, `dataset_run_items.create`, and URL construction.
- `CsvDataset` already has stable generated IDs via `build_identity_fingerprint`.
- `multi_runner.py` preloads unique string datasets through Langfuse.
- CLI supports `--dataset` for Langfuse and `--dataset-csv` for local CSV.

Platform:

- The platform persists `runs`, `run_items`, `run_item_scores`, attempts, events, spans, and trace aggregates.
- The platform does not have first-class dataset tables yet.
- Run ingestion already stores per-item input, expected output, metadata, output, scores, trace IDs, and trace URLs.

## Proposed Architecture

### Dataset Model

Add first-class platform tables:

```text
datasets
  id
  project_id
  name
  slug
  description
  tags JSON
  created_by_user_id
  created_at
  updated_at
  deleted_at
  unique(project_id, slug)

dataset_versions
  id
  dataset_id
  version
  description
  status             -- draft, published, archived
  source_type        -- csv, jsonl, api, imported_langfuse, generated
  source_uri
  parent_version_id  -- lineage for copied/edited/rolled-back versions
  base_version_id    -- original ancestor for diff/lineage grouping
  schema JSON       -- declared/observed columns and mapping
  labels JSON        -- user labels such as smoke, regression, arabic, pii
  item_count
  content_hash
  created_by_user_id
  published_by_user_id
  created_at
  published_at
  is_default
  unique(dataset_id, version)

dataset_items
  id
  dataset_version_id
  item_id           -- user-provided or generated stable ID
  index
  input JSON
  expected_output JSON
  metadata JSON
  labels JSON
  fingerprint
  created_at
  updated_at
  unique(dataset_version_id, item_id)
  index(dataset_version_id, fingerprint)
```

Additional tables:

```text
dataset_aliases
  id
  dataset_id
  alias             -- production, staging, baseline, etc.
  dataset_version_id
  updated_by_user_id
  updated_at
  unique(dataset_id, alias)

dataset_item_revisions
  id
  dataset_item_id
  dataset_version_id
  revision_number
  change_type       -- created, updated, deleted, restored
  before JSON
  after JSON
  actor_user_id
  created_at

dataset_version_changes
  id
  dataset_version_id
  parent_version_id
  change_summary JSON
  created_at

dataset_import_jobs
  id
  dataset_id
  status
  source_type
  source_metadata JSON
  error
  created_at
  completed_at
```

`runs` should gain nullable references:

```text
runs.dataset_id
runs.dataset_version_id
run_items.dataset_item_pk
```

Keep `runs.dataset` as the denormalized display label for compatibility and filtering.

Aliases are how qym represents "production". A dataset has immutable published versions, and aliases are mutable pointers. Promoting, rolling back, or changing "production" updates `dataset_aliases`, not old versions or old runs. Runs should store the resolved `dataset_version_id` at creation time, so historical evaluations remain reproducible even after production moves.

### Item Identity

Use the existing fingerprint approach as the cross-source rule:

- if an item has a non-empty explicit ID, preserve it
- otherwise generate `ds_<fingerprint>__NNNN`
- fingerprint input is `input`, `expected_output`, and immutable metadata fields
- positional fallback IDs remain only for legacy checkpoints/runs

This lets compare alignment continue to work for CSV, platform datasets, and imported historical datasets.

### SDK Dataset Abstraction

Introduce a small protocol and make all dataset implementations conform:

```python
class DatasetItem(Protocol):
    id: str
    input: Any
    expected_output: Any
    metadata: dict[str, Any]

class Dataset(Protocol):
    name: str
    version: str | None
    id: str | None
    def get_items(self) -> list[DatasetItem]: ...
```

Concrete SDK datasets:

- `CsvDataset`: keep current behavior, rename item IDs from `csv_...` to source-neutral `ds_...` only in a major version or leave as-is for compatibility.
- `JsonlDataset`: add native JSONL support for structured inputs without CSV escaping pain.
- `InMemoryDataset`: useful for tests and generated evals.
- `QymDataset`: loads a named platform dataset/version through qym platform APIs.

String resolution should change:

```python
Evaluator(dataset="qa-v1")
```

Resolution order:

1. if the string is an existing local path, load by extension (`.csv`, `.jsonl`, `.json`)
2. otherwise resolve as a qym platform dataset name/slug when `QYM_BASE_URL` and `QYM_API_KEY` are configured
3. otherwise raise a qym-native dataset error explaining how to use `CsvDataset`, `--dataset-file`, or platform config

This preserves the ergonomic API while removing Langfuse as the implicit backend.

### Platform API

Add dataset endpoints under `/v1/datasets`:

```http
GET    /v1/datasets
POST   /v1/datasets
GET    /v1/datasets/{dataset_id_or_slug}
PATCH  /v1/datasets/{dataset_id_or_slug}
DELETE /v1/datasets/{dataset_id_or_slug}

GET    /v1/datasets/{dataset_id_or_slug}/versions
POST   /v1/datasets/{dataset_id_or_slug}/versions
GET    /v1/datasets/{dataset_id_or_slug}/versions/{version}
POST   /v1/datasets/{dataset_id_or_slug}/versions/{version}:publish
POST   /v1/datasets/{dataset_id_or_slug}/aliases/{alias}
GET    /v1/datasets/{dataset_id_or_slug}/lineage

GET    /v1/datasets/{dataset_id_or_slug}/versions/{version}/items
POST   /v1/datasets/{dataset_id_or_slug}/versions/{version}/items:bulk
PATCH  /v1/datasets/{dataset_id_or_slug}/versions/{version}/items/{item_id}
DELETE /v1/datasets/{dataset_id_or_slug}/versions/{version}/items/{item_id}
GET    /v1/datasets/{dataset_id_or_slug}/versions/{version}/items/{item_id}/runs
GET    /v1/datasets/{dataset_id_or_slug}/versions/{version}:compare?base=v1
POST   /v1/datasets:upload
GET    /v1/datasets/{dataset_id_or_slug}/versions/{version}:download
```

`items` responses should paginate but also support SDK bulk loading:

```json
{
  "dataset": {"id": "...", "name": "qa", "slug": "qa"},
  "version": {"id": "...", "version": "v1", "item_count": 100},
  "items": [
    {
      "item_id": "ds_abc__0001",
      "input": {"question": "..."},
      "expected_output": "answer",
      "metadata": {"topic": "geo"}
    }
  ],
  "next_cursor": null
}
```

Run creation should accept optional `dataset_id`, `dataset_version_id`, and `dataset_alias`. Event ingestion can continue to work with denormalized item snapshots, but when a run is backed by a platform dataset the run item rows should store the canonical dataset item ID and dataset item primary key.

### Platform UI/UX

Dataset management should be a peer to Runs, Charts, Models, Reviews, and Settings in the platform navigation. This is not a hidden admin tool; it is where evaluation owners curate the test set that drives model quality decisions.

Core screens:

- Dataset catalog: searchable table/grid of datasets with production version, latest version, item count, labels, last run, last editor, and health indicators such as items changed since production.
- Dataset detail: header with name, description, tags, production alias, default version, latest published version, and primary actions: upload, create draft, promote, rollback, compare versions, download.
- Versions tab: version list with status, aliases, labels, item count, content hash, creator, publish time, parent version, and run count.
- Lineage tab: graph or compact timeline showing imports, copies, edits, promotions, rollbacks, and derived versions.
- Items tab: dense item table with filterable labels, metadata columns, item ID, fingerprint, input preview, expected output preview, last modified, and run usage count.
- Item detail drawer/page: full JSON editor for input, expected output, metadata, and labels; validation errors; revision history; and "Runs using this item".
- Runs tab: all runs that used the dataset or selected version, with filters for model, task, status, metric, and time.

Important UX behaviors:

- Production is visible everywhere: catalog row, dataset header, version badges, run creation picker, and run detail metadata.
- Rollback is a pointer move: selecting an older version and choosing "Set production" changes the `production` alias after confirmation and records audit metadata.
- Editing a published or production version never mutates historical data silently. The UI should offer "Create draft from this version" and then apply edits in that draft.
- Draft versions can be edited in-place until published. Publishing freezes the version and computes final `content_hash`.
- Item edits should be form-first for common fields and JSON-capable for advanced users. Invalid JSON, missing required input fields, duplicate item IDs, and schema drift should be caught before publish.
- Labels should exist at both version and item level. Version labels support workflow and release taxonomy; item labels support filtering, slices, and targeted regressions.
- Every item should have a "Runs" panel that lists all run items linked by `dataset_item_pk` or stable item ID/fingerprint fallback. Clicking a run opens the run detail focused on that item and its trace.
- Version compare should show added, removed, changed, and unchanged items, with per-item diffs for input, expected output, metadata, and labels.
- The run creation UI should let users choose `dataset`, then `production`/specific version, and show item count plus labels before launching/copying the CLI command.
- Dataset screens should reuse the existing operational dashboard style: compact tables, predictable filters, sticky headers, drawers for details, and no marketing-style empty states.

Minimum UI acceptance criteria:

- A user can upload a CSV/JSONL dataset, label it, publish v1, mark it as production, run an evaluation against production, open any item, and see that run listed under the item.
- A user can create a draft from production, edit an item, publish v2, promote v2 to production, and still see that old runs used v1.
- A user can roll production back from v2 to v1 without duplicating or mutating either version.
- A user can compare v1 and v2 and understand exactly which items changed.

### CLI

Add a `qym dataset` noun:

```bash
qym dataset list --json
qym dataset get qa --json
qym dataset upload --name qa --file examples/datasets/qa.csv \
  --input-col question --expected-col expected --metadata-cols topic,difficulty
qym dataset version list qa --json
qym dataset version create qa --from production --version v2 --json
qym dataset version publish qa v2 --json
qym dataset alias set qa production v2 --json
qym dataset item list qa --version v1 --limit 50 --json
qym dataset item runs qa <item_id> --version production --json
qym dataset download qa --version v1 --output qa.jsonl
```

Update run commands:

```bash
qym run create --dataset qa --dataset-version v1 ...
qym run create --dataset qa --dataset-alias production ...
qym run create --dataset-file examples/datasets/qa.csv ...
```

Deprecate `--dataset-csv` in favor of `--dataset-file`, but keep it as an alias for at least one release.

### Tracing Replacement

Remove all Langfuse trace behavior from `Evaluator`:

- delete Langfuse client initialization and credentials from `EvaluatorConfig`
- remove `self.client.create_score(...)`
- remove Langfuse dataset-run item linking
- remove Langfuse URL construction and `langfuse_*` result metadata
- update docs/examples that accept `trace_id` to describe qym/OpenTelemetry trace IDs instead of Langfuse trace IDs

Keep and lean on the existing qym tracing path:

- OpenInference instrumentors create spans
- `QymSpanProcessor` streams spans as `span_completed`
- platform stores spans and trace aggregates
- run item rows carry `trace_id`
- `trace_url` should point to the qym platform run item trace viewer, not Langfuse

The SDK can build trace URLs only when platform streaming is active:

```text
{platform_url}/projects/{project_slug}/runs/{run_id}?item_id={item_id}&trace_id={trace_id}
```

If platform streaming is not configured, traces remain local span IDs in result artifacts without remote links.

### Migration Path

1. Add qym platform dataset storage and SDK `QymDataset`.
2. Change new docs/examples to platform datasets or local files.
3. Add import tooling:
   - preferred: import from exported JSON/CSV
   - optional helper script can read Langfuse only when the user has installed Langfuse separately; it must not be a package dependency
4. Make `Evaluator(dataset=str)` resolve platform datasets instead of Langfuse.
5. Remove Langfuse dependency and code paths.
6. Keep legacy result metadata display tolerant of existing `langfuse_url`, `langfuse_dataset_id`, and `langfuse_run_id` so old run artifacts do not break.

### Backward Compatibility

Breaking behavior:

- `dataset="name"` no longer means Langfuse.
- Langfuse credential environment variables no longer activate tracing.
- `trace_url` no longer points to Langfuse.

Compatibility measures:

- clear error messages when a named dataset cannot be resolved
- `--dataset-csv` alias remains
- old run artifacts and imported runs remain readable
- docs include a "Migrating From Langfuse Datasets" page

### Security And Access Control

Datasets are project-scoped like runs.

API scopes:

- `datasets:read`
- `datasets:write`
- `datasets:delete`
- existing `runs:write` can reference only datasets in the API key project

Dataset upload must apply the same JSON sanitization rules as run ingestion. CSV parsing should retain current strict schema errors and avoid silent coercion beyond JSON-like cells.

### Implementation Plan

Phase 1: dataset foundation

- Add SQLAlchemy models and Alembic migration for `datasets`, `dataset_versions`, and `dataset_items`.
- Add SQLAlchemy models and Alembic migration for aliases, item revisions, version lineage, and run item dataset references.
- Add API schemas and endpoints for list/get/upload/item pagination, aliases, publish, lineage, compare, item edit, and item runs.
- Add platform tests for project isolation and upload validation.

Phase 2: platform UI foundation

- Add dataset routes/pages to the platform navigation.
- Build catalog, dataset detail, versions, items, item detail, and run usage views.
- Build upload, create draft, edit item, publish, promote production, rollback, and compare flows.
- Add UI tests or browser checks for the minimum acceptance criteria above.

Phase 3: SDK dataset client

- Add `QymDataset`, `JsonlDataset`, `InMemoryDataset`, and dataset protocol/types.
- Add platform client methods for dataset lookup and item pagination.
- Update `Evaluator(dataset=str)` and `MultiModelRunner` preload logic to use qym platform datasets.
- Add tests for string resolution, local path resolution, missing platform config, and multi-run dataset caching.

Phase 4: CLI and docs

- Add `qym dataset ...` commands.
- Add `--dataset-version`, `--dataset-alias`, and `--dataset-file`; keep `--dataset-csv` alias.
- Update examples to use local CSV/JSONL or qym dataset upload.
- Update README, SDK guide, and generated docs content.

Phase 5: Langfuse removal

- Remove `LangfuseDataset`, Langfuse config fields, Langfuse client init, score creation, dataset-run linking, and URL builders.
- Remove `langfuse>=3.0.0` from required dependencies.
- Rename user-facing docs and comments from "Langfuse trace ID" to "qym trace ID" or "OpenTelemetry trace ID".
- Delete or quarantine Langfuse benchmark scripts from normal tests.

Phase 6: migration tooling

- Add `qym dataset import --file exported.jsonl --name ...`.
- Document a Langfuse export shape and mapping.
- Provide a best-effort standalone script under `tools/` for users who still have Langfuse installed locally, but keep it outside package dependencies.

### Testing Strategy

SDK unit tests:

- CSV compatibility and stable IDs
- JSONL loading
- `QymDataset` pagination and error handling with mocked platform API
- `Evaluator(dataset=str)` resolution branches
- no import-time dependency on `langfuse`

Platform tests:

- dataset CRUD and upload
- dataset version immutability
- draft edit and publish behavior
- production alias promotion and rollback
- version lineage and compare output
- item run history lookup
- item ID uniqueness and generated fingerprints
- project access isolation
- run creation with `dataset_version_id`

Integration tests:

- upload CSV through CLI, run evaluation by dataset name, verify run items reference stable item IDs
- create v2 from production, edit one item, publish, promote, run again, and verify v1/v2 run history remains distinct
- run without platform using local CSV/JSONL
- run with platform streaming and verify spans, scores, and trace links are qym-native

### Open Questions

- Should dataset versions be immutable after creation? Recommendation: yes. Corrections should create a new version.
- Should draft versions be mutable? Recommendation: yes, but only until publish.
- Should `dataset="name"` require platform config, or should it also search a configured local dataset registry? Recommendation: platform first; add local registry later if needed.
- Should old `csv_...` generated IDs be retained forever? Recommendation: keep current `CsvDataset` IDs until a major version; use `ds_...` for new platform/generated datasets.
- Should dataset upload infer input/expected columns automatically? Recommendation: require explicit mapping unless columns are exactly `input` and `expected_output`.

## Recommended Direction

Build platform datasets as the canonical replacement and remove Langfuse fully from the SDK. Do not treat this as a tracing-provider swap. qym already has its own run ingestion, span storage, trace aggregation, and dashboard surface; adding native datasets completes the ownership boundary and removes the most fragile external dependency from the core evaluation loop.
