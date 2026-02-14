# Platform User Guide

The qym platform is the deployed web app that stores runs centrally and hosts the live run dashboard.

## Access Model

The platform identifies users via reverse-proxy headers:
- `X-User-Email` (preferred) or `X-Email`

First admin bootstrap:
1. Set `QYM_ADMIN_BOOTSTRAP_TOKEN`
2. Send `X-Admin-Bootstrap: <token>` + `X-User-Email: you@company.com` on your first request

## Organization & Roles

### Organizational Hierarchy
Users are organized into a three-level hierarchy:
- **Sector** → **Department** → **Team**

Each user belongs to exactly one Team, which determines their visibility and approval authority.

### Roles
- **EMPLOYEE**: Standard user role
  - Sees own runs only
  - Can submit runs for approval
- **MANAGER**: Team manager role
  - Sees runs from their managed team(s)
  - Can approve/reject submitted runs from team members
- **GM**: General Manager role
  - Sees approved runs only (configurable)
  - Cannot approve/reject
- **VP**: Vice President role
  - Sees approved runs only (configurable)
  - Cannot approve/reject
- **ADMIN**: Platform administrator
  - Full access to all runs and settings
  - Can manage users, org structure, and platform settings

### Visibility Rules (Admin Configurable)
- **GM/VP Approved-Only**: When enabled, GM and VP users can only see runs that have been approved
- **Manager Visibility Scope**: Controls whether managers see all runs in their org subtree or just their direct team

## Using the Dashboard

### Main Dashboard
- Open `http://<platform>/` to view runs
- Click a run ID to open the run details UI (`/run/<run_id>`)
- Use the **Status** filter to show `DRAFT/SUBMITTED/APPROVED/REJECTED/...`
- Compare multiple runs using the comparison view

### Profile Page
- View your profile and organization info at `/profile`
- Manage API keys for SDK integration

### Admin Panel (ADMIN role only)
- Access at `/admin`
- Manage users, organization structure, and platform settings
- See [Admin Guide](ADMIN_GUIDE.md) for details

## Uploading Eval Runs

### From the SDK (Live Streaming - Recommended)
Run your evaluation with an API key:
```bash
export QYM_API_KEY=your-api-key
qym --task-file my_task.py --task-function my_func --dataset my-dataset --metrics exact_match
```

The platform URL is configured internally (override with `QYM_PLATFORM_URL` for development).

**Note**: The local UI server has been deprecated. All live run viewing is through the platform dashboard.

### Upload a Saved Results File
Use the CLI:
```bash
qym submit --file results.csv --task my_task --dataset my-dataset
```

Or the API:
```bash
curl -X POST http://<platform>/v1/runs:upload \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@results.csv" \
  -F "task=my_task" \
  -F "dataset=my-dataset"
```

**Note**: Uploaded files are parsed and ingested into the database. Raw uploaded files are NOT stored persistently.

## Run Workflow

1. **DRAFT**: Run is created but not submitted
2. **SUBMITTED**: User submits run for approval
3. **APPROVED**: Manager approves the run (visible to GM/VP)
4. **REJECTED**: Manager rejects the run

## Opening the Dashboard

From the CLI:
```bash
qym dashboard
```

This opens the platform dashboard in your browser.


