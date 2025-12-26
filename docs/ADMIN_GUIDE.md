# Admin Guide (MVP)

## Bootstrap first admin

1. Set `LLM_EVAL_ADMIN_BOOTSTRAP_TOKEN` on the platform.
2. Make a request with:
   - `X-Admin-Bootstrap: <token>`
   - `X-User-Email: <your email>`

This creates the first user as role `VP` (admin).

## Create users

Call:

- `POST /v1/admin/users` (requires current user role `VP`)

## Create API keys

In the UI auth context (proxy headers), call:

- `POST /v1/me/api-keys`

The response includes the API key **token** once. Store it securely.

## Import legacy local results

Run from repo root (after setting `LLM_EVAL_DATABASE_URL`):

```bash
python -m llm_eval_platform.tools.import_local_results --owner-email you@company.com --results-dir llm-eval_results
```


