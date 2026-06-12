# @qym/frontend

React 18 + TypeScript + Vite SPA for the qym platform. Replaces the legacy
vanilla-JS dashboard in `qym_platform/_static/dashboard`.

## Dev workflow

Two processes:

```sh
# 1. backend (repo root / platform package)
uvicorn qym_platform.app:app --reload --port 8000

# 2. frontend (this directory)
npm install
npm run dev          # Vite dev server on http://localhost:5173
```

The Vite dev server proxies all backend-owned prefixes (`/api`, `/v1`,
`/login`, `/auth`, `/static`, `/ui`, `/docs`, `/healthz`, `/openapi.json`) to
`http://localhost:8000`. The proxy also **rewrites the `Origin` and `Referer`
headers** to the backend origin, because the backend enforces a same-origin
guard on write requests (`changeOrigin` alone only fixes `Host`).

## Build

```sh
npm run build          # tsc -b + vite build → ../qym_platform/_static/app/
npm run build:export   # single-file export bundle → ../qym_platform/_static/app/export/export.html
```

Run `build:export` **after** `build` — the main build empties `_static/app`.

Asset URL strategy: filenames are content-hashed, and JS-referenced assets are
resolved at runtime as `window.__QYM_ROOT_PATH__ + '/app-assets/<file>'` (see
`experimental.renderBuiltUrl` in `vite.config.ts`). The backend injects
`window.__QYM_ROOT_PATH__` when serving `index.html`; `index.html` itself uses
relative URLs.

## Tests

```sh
npm run lint        # eslint (flat config: typescript-eslint, jsx-a11y, react-hooks, no-unsanitized)
npm run test        # vitest (jsdom)
npm run test:watch
npm run e2e         # playwright against http://localhost:8000 (build + start uvicorn first)
```

## API types codegen

With uvicorn running on :8000:

```sh
npm run codegen     # openapi-typescript → src/api/generated.d.ts
```

## Layout

- `src/router.tsx` — route table (placeholders per feature area in `src/features/*/Placeholder.tsx`)
- `src/api/client.ts` — typed fetch wrapper (root-path aware, throws `ApiError` with FastAPI `detail`)
- `src/styles/tokens.css` — design tokens ported from the legacy dashboard, with WCAG AA contrast fixes for `--text-muted` / `--text-dim` (ratios documented inline)
- `src/styles/global.css` — resets + global `:focus-visible` ring
