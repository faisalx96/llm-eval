# Local Docker setup for LLM-Eval
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt setup.py README.md ./
COPY llm_eval ./llm_eval

# Install the application
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite
RUN mkdir -p /app/data /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the API server
CMD ["python", "-m", "llm_eval.api.main"]
