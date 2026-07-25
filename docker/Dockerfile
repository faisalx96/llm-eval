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
COPY packages/sdk/README.md /app/packages/sdk/README.md
COPY packages/sdk/qym/_version.py /app/packages/sdk/qym/_version.py
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


FROM python-base AS runtime-base

COPY packages/sdk /app/packages/sdk
COPY packages/platform /app/packages/platform
COPY insightor_eval.py /app/insightor_eval.py
COPY examples /app/examples
COPY tools /app/tools

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/packages/sdk -e /app/packages/platform

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]


FROM runtime-base AS final
