# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS docs-gen

WORKDIR /src

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip

COPY packages/sdk /src/packages/sdk
COPY packages/platform /src/packages/platform
COPY examples /src/examples
COPY tools /src/tools
COPY docs_portal /src/docs_portal

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /src/packages/sdk -e /src/packages/platform

RUN python -m tools.docs

FROM node:22-slim AS docs-build

WORKDIR /src/docs_portal

COPY --from=docs-gen /src/docs_portal /src/docs_portal

RUN npm ci
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (psycopg2-binary doesn't require build deps)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip

# Copy both packages
COPY packages/sdk /app/packages/sdk
COPY packages/platform /app/packages/platform
COPY examples /app/examples
COPY tools /app/tools
COPY docs_portal /app/docs_portal

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/packages/sdk -e /app/packages/platform

RUN python -m tools.docs

COPY --from=docs-build /src/docs_portal/build /app/docs_portal/build

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
