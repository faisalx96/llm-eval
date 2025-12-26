FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (psycopg2-binary doesn't require build deps)
RUN pip install --no-cache-dir --upgrade pip

COPY . /app

RUN pip install --no-cache-dir ".[platform]"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

