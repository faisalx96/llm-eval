/**
 * Hand-written types for the live /v1 endpoints the shell consumes.
 * Shapes verified against the running backend (auth mode "none") on
 * 2026-06-11 via `curl http://localhost:8000/v1/me` and `/v1/projects`.
 *
 * TODO: replace with the generated client (`npm run codegen`) once the
 * /v1 surface stabilizes.
 */

/** Project summary as returned by GET /v1/projects and embedded in /v1/me. */
export interface Project {
  id: string
  name: string
  slug: string
  description: string
  is_active: boolean
  member_count: number
  run_count: number
  /** Caller's role within this project (e.g. "MANAGER"). */
  role: string
  /** ISO-8601 timestamp. */
  created_at: string
  /** ISO-8601 timestamp. */
  updated_at: string
}

/** GET /v1/projects */
export interface ProjectsResponse {
  projects: Project[]
}

/** GET /v1/me */
export interface Me {
  id: string
  email: string
  display_name: string
  title: string
  /** Global role, e.g. "ADMIN" | "MEMBER". */
  role: string
  /** Auth mode, e.g. "none" (dev auto-admin) | "oidc". */
  auth_type: string
  auth_provider: string | null
  needs_admin_bootstrap: boolean
  can_bootstrap_admin: boolean
  projects: Project[]
  default_project: Project | null
}

/** POST /v1/projects request body (slug auto-derived server-side when null). */
export interface CreateProjectRequest {
  name: string
  slug?: string | null
  description?: string
}
