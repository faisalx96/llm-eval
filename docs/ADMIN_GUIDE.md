# Admin Guide

## Bootstrap First Admin

1. Set `QYM_ADMIN_BOOTSTRAP_TOKEN` on the platform.
2. Make a request with:
   - `X-Admin-Bootstrap: <token>`
   - `X-User-Email: <your email>`

This creates the first user with role `ADMIN`.

## Admin UI

Navigate to `/admin` (visible in header for ADMIN users) to access:

### Users Management
- View all users
- Create new users with email, display name, role, and team assignment
- Edit existing users (change role, team, active status)

### Organization Structure
- View the org tree (Sector → Department → Team)
- Create new org units (Sectors, Departments, Teams)
- Assign team managers (MANAGER role users)
- Rebuild org closure table (for authorization calculations)

### Platform Settings
- **GM/VP Approved-Only Visibility**: When enabled, GM and VP users can only see runs that have been approved
- **Manager Visibility Scope**: Toggle between subtree (all teams under their management) and direct (only their team)

## Organization Hierarchy

The platform uses a three-level hierarchy:
- **Sector** (top-level, e.g., "Technology Sector")
- **Department** (belongs to a Sector, e.g., "AI/ML Department")
- **Team** (belongs to a Department, e.g., "Training Team")

Each user belongs to exactly one Team. Team managers can approve/reject runs from their team members.

## API Endpoints

### User Management
- `GET /v1/admin/users` - List all users
- `POST /v1/admin/users` - Create a new user
- `PUT /v1/admin/users/{user_id}` - Update a user

### Org Unit Management
- `GET /v1/admin/org/tree` - Get full org tree
- `GET /v1/admin/org/teams` - List all teams
- `POST /v1/admin/org/units` - Create org unit
- `PATCH /v1/admin/org/units/{id}` - Update org unit
- `DELETE /v1/admin/org/units/{id}` - Delete org unit
- `PUT /v1/admin/org/teams/{id}/manager` - Assign team manager
- `POST /v1/admin/org/rebuild-closure` - Rebuild closure table

### Settings
- `GET /v1/admin/settings` - Get all settings
- `PUT /v1/admin/settings` - Update settings

## Create API Keys

In the UI auth context (proxy headers), call:

- `POST /v1/me/api-keys`

The response includes the API key **token** once. Store it securely.

## Import Legacy Local Results

Run from repo root (after setting `QYM_DATABASE_URL`):

```bash
python -m qym_platform.tools.import_local_results --owner-email you@company.com --results-dir qym_results
```

Note: This imports CSV/JSON results into the platform database. The raw files are parsed and ingested; raw artifacts are NOT stored persistently.


