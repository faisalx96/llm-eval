# 🚀 LLM-Eval Deployment Guide

## Overview
This guide covers deploying LLM-Eval in various environments, from local development to production Kubernetes clusters.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [Production Deployment](#production-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements
- **Python**: 3.8+ (3.10 recommended)
- **Node.js**: 18+ (for frontend)
- **Database**: SQLite (dev) or PostgreSQL 13+ (production)
- **Memory**: 4GB minimum, 8GB recommended
- **Storage**: 10GB minimum for database and logs

### Required Credentials
```bash
# Langfuse (Required)
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_HOST=https://cloud.langfuse.com

# Database (Production only)
DATABASE_URL=postgresql://user:pass@host:5432/llm_eval

# Optional Services
REDIS_URL=redis://localhost:6379
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

---

## Local Development

### Quick Start
```bash
# 1. Clone repository
git clone https://github.com/your-org/llm-eval.git
cd llm-eval

# 2. Install Python dependencies
pip install -e .
pip install -e ".[dev]"

# 3. Install frontend dependencies
cd frontend
npm install
cd ..

# 4. Set environment variables
cp .env.example .env
# Edit .env with your credentials

# 5. Start services
# Terminal 1: API Server
python -m llm_eval.api.main

# Terminal 2: Frontend
cd frontend && npm run dev

# Visit http://localhost:3000
```

### Development Configuration
```python
# config/development.py
DEBUG = True
DATABASE_URL = "sqlite:///llm_eval_runs.db"
CORS_ORIGINS = ["http://localhost:3000"]
LOG_LEVEL = "DEBUG"
```

---

## Docker Deployment

### Single Container Setup
```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Install package
RUN pip install -e .

# Expose ports
EXPOSE 8000

# Run API server
CMD ["uvicorn", "llm_eval.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose (Recommended)
```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:13
    environment:
      POSTGRES_DB: llm_eval
      POSTGRES_USER: llm_eval
      POSTGRES_PASSWORD: secure_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  api:
    build: 
      context: .
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://llm_eval:secure_password@postgres:5432/llm_eval
      REDIS_URL: redis://redis:6379
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
      LANGFUSE_HOST: ${LANGFUSE_HOST}
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    volumes:
      - ./logs:/app/logs

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    environment:
      NEXT_PUBLIC_API_URL: http://api:8000
    ports:
      - "3000:3000"
    depends_on:
      - api

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - api
      - frontend

volumes:
  postgres_data:
```

### Build and Run
```bash
# Build containers
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## Production Deployment

### Production Dockerfile
```dockerfile
# Dockerfile.prod
FROM python:3.10-slim as builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.10-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY . .
RUN pip install --no-deps -e .

# Security: Run as non-root user
RUN useradd -m -u 1000 llmeval && chown -R llmeval:llmeval /app
USER llmeval

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/health/ || exit 1

EXPOSE 8000

# Production server with workers
CMD ["gunicorn", "llm_eval.api.main:app", \
     "-w", "4", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

### Environment Configuration
```bash
# .env.production
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_RELOAD=false

# Database
DATABASE_URL=postgresql://user:pass@db.example.com:5432/llm_eval
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

# Redis Cache
REDIS_URL=redis://redis.example.com:6379/0
REDIS_MAX_CONNECTIONS=50

# Security
SECRET_KEY=your-secret-key-min-32-chars
ALLOWED_HOSTS=api.example.com,www.example.com
CORS_ORIGINS=https://app.example.com

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
LOG_LEVEL=INFO

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=100
```

### NGINX Configuration
```nginx
# nginx.conf
upstream api {
    server api:8000;
}

upstream frontend {
    server frontend:3000;
}

server {
    listen 80;
    server_name example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # API routes
    location /api {
        proxy_pass http://api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Frontend routes
    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Kubernetes Deployment

### Namespace and ConfigMap
```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: llm-eval

---
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: llm-eval-config
  namespace: llm-eval
data:
  API_HOST: "0.0.0.0"
  API_PORT: "8000"
  LOG_LEVEL: "INFO"
  CORS_ORIGINS: "https://llm-eval.example.com"
```

### Secrets
```yaml
# k8s/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: llm-eval-secrets
  namespace: llm-eval
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:pass@postgres:5432/llm_eval"
  LANGFUSE_SECRET_KEY: "your-secret-key"
  LANGFUSE_PUBLIC_KEY: "your-public-key"
  SECRET_KEY: "your-app-secret-key"
```

### API Deployment
```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-eval-api
  namespace: llm-eval
spec:
  replicas: 3
  selector:
    matchLabels:
      app: llm-eval-api
  template:
    metadata:
      labels:
        app: llm-eval-api
    spec:
      containers:
      - name: api
        image: llm-eval:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: llm-eval-config
        - secretRef:
            name: llm-eval-secrets
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /api/health/
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/health/
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

### Service and Ingress
```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: llm-eval-api
  namespace: llm-eval
spec:
  selector:
    app: llm-eval-api
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP

---
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: llm-eval-ingress
  namespace: llm-eval
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    nginx.ingress.kubernetes.io/websocket-services: llm-eval-api
spec:
  tls:
  - hosts:
    - api.llm-eval.example.com
    secretName: llm-eval-tls
  rules:
  - host: api.llm-eval.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: llm-eval-api
            port:
              number: 80
```

### Horizontal Pod Autoscaler
```yaml
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-eval-api-hpa
  namespace: llm-eval
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: llm-eval-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Deploy to Kubernetes
```bash
# Apply configurations
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml

# Check status
kubectl get pods -n llm-eval
kubectl get svc -n llm-eval
kubectl get ingress -n llm-eval

# View logs
kubectl logs -f deployment/llm-eval-api -n llm-eval

# Scale manually
kubectl scale deployment llm-eval-api --replicas=5 -n llm-eval
```

---

## Configuration

### Database Setup
```sql
-- PostgreSQL initialization
CREATE DATABASE llm_eval;
CREATE USER llm_eval WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE llm_eval TO llm_eval;

-- Performance tuning
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
ALTER SYSTEM SET random_page_cost = 1.1;
```

### Redis Configuration
```conf
# redis.conf
maxmemory 512mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

### Application Settings
```python
# config/production.py
import os
from urllib.parse import urlparse

class Config:
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL')
    DATABASE_POOL_SIZE = int(os.getenv('DATABASE_POOL_SIZE', 20))
    DATABASE_POOL_RECYCLE = 3600
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL')
    CACHE_TTL = 3600  # 1 hour
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY')
    BCRYPT_LOG_ROUNDS = 13
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = "100/minute"
    
    # Monitoring
    SENTRY_DSN = os.getenv('SENTRY_DSN')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
```

---

## Monitoring

### Health Checks
```python
# llm_eval/api/endpoints/health.py
@router.get("/health/")
async def health_check():
    checks = {
        "api": "healthy",
        "database": check_database(),
        "redis": check_redis(),
        "langfuse": check_langfuse()
    }
    
    status_code = 200 if all(
        v == "healthy" for v in checks.values()
    ) else 503
    
    return JSONResponse(
        content={"status": "healthy" if status_code == 200 else "degraded", "checks": checks},
        status_code=status_code
    )
```

### Prometheus Metrics
```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'llm-eval'
    static_configs:
      - targets: ['api:8000']
    metrics_path: '/metrics'
```

### Logging
```python
# logging_config.py
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        },
        'json': {
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/llm_eval.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'json',
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'file']
    }
}
```

---

## Troubleshooting

### Common Issues

#### Database Connection Errors
```bash
# Check PostgreSQL is running
docker-compose ps postgres
docker-compose logs postgres

# Test connection
psql -h localhost -U llm_eval -d llm_eval

# Reset database
docker-compose exec api python -m llm_eval.storage.migrate --reset
```

#### API Not Responding
```bash
# Check API logs
docker-compose logs api
kubectl logs -f deployment/llm-eval-api -n llm-eval

# Restart API
docker-compose restart api
kubectl rollout restart deployment/llm-eval-api -n llm-eval

# Check resource usage
docker stats
kubectl top pods -n llm-eval
```

#### Frontend Build Issues
```bash
# Clear cache and rebuild
cd frontend
rm -rf .next node_modules
npm install
npm run build

# Check for port conflicts
lsof -i :3000
kill -9 <PID>
```

#### WebSocket Connection Failed
```nginx
# Ensure NGINX has WebSocket support
location /ws {
    proxy_pass http://api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
}
```

### Performance Tuning

#### Database Optimization
```sql
-- Add indexes
CREATE INDEX idx_runs_created_at ON evaluation_runs(created_at DESC);
CREATE INDEX idx_runs_project_id ON evaluation_runs(project_id);
CREATE INDEX idx_items_run_id ON evaluation_items(run_id);

-- Vacuum and analyze
VACUUM ANALYZE evaluation_runs;
VACUUM ANALYZE evaluation_items;
```

#### API Optimization
```python
# Use connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
    pool_recycle=3600
)

# Enable query caching
@cache.memoize(timeout=300)
def get_run_stats(run_id):
    # Expensive query here
    pass
```

---

## Security Checklist

- [ ] Use HTTPS in production
- [ ] Set strong SECRET_KEY
- [ ] Enable CORS properly
- [ ] Use environment variables for secrets
- [ ] Run containers as non-root user
- [ ] Keep dependencies updated
- [ ] Enable rate limiting
- [ ] Set up firewall rules
- [ ] Regular security audits
- [ ] Backup database regularly

---

## Backup and Recovery

### Database Backup
```bash
# Manual backup
pg_dump -h localhost -U llm_eval llm_eval > backup_$(date +%Y%m%d).sql

# Automated backup script
#!/bin/bash
BACKUP_DIR="/backups"
DB_NAME="llm_eval"
DATE=$(date +%Y%m%d_%H%M%S)

pg_dump -h $DB_HOST -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/backup_$DATE.sql.gz

# Keep only last 7 days
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +7 -delete
```

### Restore Database
```bash
# Restore from backup
gunzip < backup_20240101.sql.gz | psql -h localhost -U llm_eval llm_eval

# Point-in-time recovery
pg_restore -h localhost -U llm_eval -d llm_eval backup.dump
```

---

## Support

For deployment issues:
1. Check logs: `docker-compose logs` or `kubectl logs`
2. Review configuration in `.env` files
3. Consult troubleshooting section
4. Open issue on GitHub with deployment logs

---

**Last Updated:** January 2025  
**Version:** 0.2.5  
**Status:** Production Ready