# Multi-stage build for LLM-Eval Backend API
# Production-optimized Docker image with security best practices

# Build stage - install dependencies and build application
FROM python:3.11-slim as builder

# Set build arguments
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.3.0

# Add metadata labels
LABEL maintainer="faisalx96@yahoo.com"
LABEL org.opencontainers.image.title="LLM-Eval API"
LABEL org.opencontainers.image.description="UI-first LLM evaluation platform API"
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.revision=$VCS_REF
LABEL org.opencontainers.image.vendor="LLM-Eval"
LABEL org.opencontainers.image.url="https://github.com/faisalx96/llm-eval"
LABEL org.opencontainers.image.source="https://github.com/faisalx96/llm-eval"

# Install system dependencies required for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Create a non-root user for security
RUN groupadd -r llmeval && useradd -r -g llmeval llmeval

# Copy dependency files
COPY requirements.txt setup.py README.md ./
COPY llm_eval/__init__.py ./llm_eval/

# Create requirements.txt if it doesn't exist
RUN if [ ! -f requirements.txt ]; then \
    echo "langfuse>=2.0.0" > requirements.txt && \
    echo "pydantic>=2.0.0" >> requirements.txt && \
    echo "rich>=13.0.0" >> requirements.txt && \
    echo "aiohttp>=3.8.0" >> requirements.txt && \
    echo "python-dotenv>=0.19.0" >> requirements.txt && \
    echo "nest_asyncio>=1.5.0" >> requirements.txt && \
    echo "openpyxl>=3.0.0" >> requirements.txt && \
    echo "sqlalchemy>=2.0.0" >> requirements.txt && \
    echo "click>=8.0.0" >> requirements.txt && \
    echo "fastapi>=0.104.0" >> requirements.txt && \
    echo "uvicorn>=0.24.0" >> requirements.txt && \
    echo "websockets>=12.0" >> requirements.txt && \
    echo "gunicorn>=21.2.0" >> requirements.txt && \
    echo "psycopg2-binary>=2.9.0" >> requirements.txt && \
    echo "redis>=5.0.0" >> requirements.txt; \
    fi

# Install Python dependencies in user directory
RUN pip install --user --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage - minimal runtime image
FROM python:3.11-slim as production

# Set build arguments
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.3.0

# Add metadata labels
LABEL maintainer="faisalx96@yahoo.com"
LABEL org.opencontainers.image.title="LLM-Eval API"
LABEL org.opencontainers.image.description="UI-first LLM evaluation platform API"
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.revision=$VCS_REF

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r llmeval && useradd -r -g llmeval -u 1000 llmeval

# Set work directory
WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder --chown=llmeval:llmeval /root/.local /home/llmeval/.local

# Make sure scripts in .local are usable
ENV PATH=/home/llmeval/.local/bin:$PATH

# Copy application code
COPY --chown=llmeval:llmeval . .

# Install the application in development mode
RUN pip install --no-deps -e .

# Create necessary directories
RUN mkdir -p logs data && chown -R llmeval:llmeval logs data

# Switch to non-root user
USER llmeval

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH=/home/llmeval/.local/bin:$PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Default command - use gunicorn for production
CMD ["gunicorn", "llm_eval.api.main:app", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--timeout", "120", \
     "--keepalive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]