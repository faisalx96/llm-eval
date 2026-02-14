FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (psycopg2-binary doesn't require build deps)
RUN pip install --no-cache-dir --upgrade pip

# Copy both packages
COPY packages/sdk /app/packages/sdk
COPY packages/platform /app/packages/platform

RUN pip install --no-cache-dir /app/packages/sdk /app/packages/platform

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
