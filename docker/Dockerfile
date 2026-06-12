# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS python-base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip


FROM python-base AS dev

# Prime dependency resolution from package metadata so source edits do not
# force a full reinstall during dev rebuilds.
COPY packages/sdk/pyproject.toml /app/packages/sdk/pyproject.toml
COPY packages/platform/pyproject.toml /app/packages/platform/pyproject.toml
RUN mkdir -p /app/packages/sdk/qym /app/packages/platform/qym_platform
RUN touch /app/packages/sdk/qym/__init__.py /app/packages/platform/qym_platform/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e /app/packages/sdk -e /app/packages/platform

COPY packages/sdk /app/packages/sdk
COPY packages/platform /app/packages/platform
COPY insightor_eval.py /app/insightor_eval.py
COPY tools /app/tools

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]


FROM dev AS docs-gen

COPY examples /app/examples
COPY docs_portal /app/docs_portal

RUN python -m tools.docs


FROM node:22-slim AS docs-build

WORKDIR /src/docs_portal

COPY --from=docs-gen /app/docs_portal /src/docs_portal

RUN --mount=type=cache,target=/root/.npm \
    npm ci
RUN npm run build


FROM node:22-slim AS frontend-build

# Mirror the repo layout so vite's relative outDir
# (../qym_platform/_static/app) resolves to a predictable path.
WORKDIR /src/packages/platform/frontend

COPY packages/platform/frontend/package.json packages/platform/frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Selective copy (instead of the whole frontend dir) so a locally installed
# node_modules in the build context can never clobber the `npm ci` result
# (.dockerignore only excludes the repo-root node_modules/).
COPY packages/platform/frontend/index.html \
     packages/platform/frontend/export.html \
     packages/platform/frontend/vite.config.ts \
     packages/platform/frontend/vite.config.export.ts \
     packages/platform/frontend/tsconfig.json \
     packages/platform/frontend/tsconfig.node.json \
     ./
COPY packages/platform/frontend/src ./src
COPY packages/platform/frontend/e2e ./e2e

# build → _static/app (index.html + hashed assets/), then build:export →
# _static/app/export/export.html (must run AFTER build: emptyOutDir wipes app/).
RUN npm run build && npm run build:export


FROM python-base AS runtime-base

COPY packages/sdk /app/packages/sdk
COPY packages/platform /app/packages/platform

# Built SPA (gitignored locally, so never guaranteed in the build context).
COPY --from=frontend-build /src/packages/platform/qym_platform/_static/app /app/packages/platform/qym_platform/_static/app
COPY insightor_eval.py /app/insightor_eval.py
COPY examples /app/examples
COPY tools /app/tools

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/packages/sdk -e /app/packages/platform

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]


FROM runtime-base AS final-with-docs

COPY docs_portal /app/docs_portal

RUN python -m tools.docs

COPY --from=docs-build /src/docs_portal/build /app/docs_portal/build


FROM runtime-base AS final
