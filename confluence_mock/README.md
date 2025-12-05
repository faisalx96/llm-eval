# Mock Confluence Structure

This directory simulates a Confluence space for testing the publish feature.

## Structure

```
confluence_mock/
├── _config.json          # Space configuration (users, settings)
├── _space.json           # Space metadata
└── projects/             # Confluence folders (one per project)
    └── {project_name}/   # Project folder
        ├── _project.json # Project metadata
        └── {task_name}.md  # Task page (markdown)
```

## Page Format (Markdown)

Each task page is a markdown file with sections for published evaluation runs:

```markdown
# Task Name

**Project**: Project Name

---

## run-id-241204-1530

**Published**: 2024-12-04 15:30 by @username

### Description

Business description here explaining the purpose of this evaluation.

### Details

| Field | Value |
|-------|-------|
| Model | `gpt-4` |
| Dataset | `my-dataset` |
| Total Items | 100 |
| Success Rate | 95.0% (95/100) |
| Errors | 5 |
| Avg Latency | 1250ms |
| Branch | `feature/new-prompt` |
| Commit | `abc1234` |

### Metrics

  - **exact_match**: 87.0%
```
