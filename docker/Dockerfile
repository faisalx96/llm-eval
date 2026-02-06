FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (psycopg2-binary doesn't require build deps)
RUN pip install --no-cache-dir --upgrade pip

# Copy only what we need (faster builds; smaller cache bust surface).
COPY setup.py README.md /app/
COPY qym /app/qym
COPY llm_eval_platform /app/llm_eval_platform
COPY docker /app/docker

RUN pip install --no-cache-dir ".[platform]"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

