# syntax=docker/dockerfile:1.7
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

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/packages/sdk -e /app/packages/platform

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
