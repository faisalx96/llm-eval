# 🚀 LLM-Eval Production Deployment Guide

## Overview
This comprehensive guide covers deploying LLM-Eval in production environments using Docker and Kubernetes, with security best practices, monitoring, and automated deployment scripts.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Docker Deployment](#docker-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Configuration](#configuration)
- [Security](#security)
- [Monitoring & Logging](#monitoring--logging)
- [Backup & Recovery](#backup--recovery)
- [Troubleshooting](#troubleshooting)
- [Automated Scripts](#automated-scripts)

---

## Prerequisites

### System Requirements
- **Docker**: 20.10+ with Docker Compose v2
- **Kubernetes**: 1.24+ (for K8s deployment)
- **CPU**: 4 cores minimum, 8 cores recommended
- **Memory**: 8GB minimum, 16GB recommended
- **Storage**: 50GB minimum for production
- **Network**: HTTPS/TLS certificates for production

### Required Tools
```bash
# Docker deployment
docker --version          # 20.10+
docker-compose --version  # v2.0+

# Kubernetes deployment
kubectl version           # 1.24+
helm version             # 3.0+ (optional)

# Utilities
curl, git, openssl
```

### Required Credentials
```bash
# Core Services (Required)
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key-here
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key-here
LANGFUSE_HOST=https://cloud.langfuse.com

# Database & Cache
POSTGRES_PASSWORD=your-secure-db-password
REDIS_PASSWORD=your-secure-redis-password
SECRET_KEY=your-secure-app-secret-min-32-chars

# Production URLs
CORS_ORIGINS=https://your-domain.com
NEXT_PUBLIC_API_URL=https://api.your-domain.com

# Optional Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
```

## Quick Start

### Automated Deployment (Recommended)
```bash
# 1. Clone repository
git clone https://github.com/faisalx96/llm-eval.git
cd llm-eval

# 2. Setup environment
cp .env.example .env
# Edit .env with your credentials

# 3. Deploy with Docker (Development)
./scripts/deploy.sh docker dev

# 4. Deploy with Docker (Production)
./scripts/deploy.sh docker prod

# 5. Deploy with Kubernetes (Production)
./scripts/deploy.sh k8s prod

# 6. Run health checks
./scripts/health_check.sh docker  # or k8s

# Visit https://your-domain.com
```

### Manual Setup (Development)
```bash
# Local development without Docker
pip install -e .
pip install -e ".[dev]"
cd frontend && npm install && cd ..

# Start services
python -m llm_eval.api.main &  # API on :8000
cd frontend && npm run dev &   # Frontend on :3000
```

## Docker Deployment

### Architecture Overview
The Docker deployment includes:
- **API Server**: FastAPI backend with Gunicorn
- **Frontend**: Next.js application with standalone output
- **PostgreSQL**: Production database with performance tuning
- **Redis**: Cache and session storage
- **NGINX**: Reverse proxy and load balancer (production)
- **Monitoring**: Prometheus, Grafana, Loki (optional)

### Multi-Stage Dockerfile (Backend)
```dockerfile
# Multi-stage build for optimized production image
FROM python:3.11-slim as builder
# Build dependencies and application
RUN apt-get update && apt-get install -y build-essential curl git
WORKDIR /app
COPY requirements.txt setup.py ./
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim as production
# Production runtime with security hardening
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN groupadd -r llmeval && useradd -r -g llmeval -u 1000 llmeval
WORKDIR /app
COPY --from=builder /root/.local /home/llmeval/.local
COPY --chown=llmeval:llmeval . .
USER llmeval
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:8000/api/health
CMD ["gunicorn", "llm_eval.api.main:app", "--workers", "4", "--bind", "0.0.0.0:8000"]
```

### Development Setup
```bash
# Start development environment
docker-compose up -d

# View logs
docker-compose logs -f

# Access services:
# - Frontend: http://localhost:3000
# - API: http://localhost:8000
# - API Docs: http://localhost:8000/api/docs
# - PgAdmin: http://localhost:5050 (with --profile tools)
```

### Production Setup
```bash
# Production deployment with monitoring
export POSTGRES_PASSWORD="your-secure-password"
export REDIS_PASSWORD="your-redis-password"
export SECRET_KEY="your-secret-key-min-32-chars"
export LANGFUSE_SECRET_KEY="sk-lf-your-key"
export LANGFUSE_PUBLIC_KEY="pk-lf-your-key"

# Deploy production stack
docker-compose -f docker-compose.production.yml up -d

# Deploy with monitoring
docker-compose -f docker-compose.production.yml --profile monitoring up -d

# SSL/TLS certificates (Let's Encrypt)
docker run --rm -v $(pwd)/ssl:/etc/letsencrypt certbot/certbot \
  certonly --standalone -d your-domain.com
```

### Docker Compose Files

**Development** (`docker-compose.yml`):
- SQLite/PostgreSQL database
- Hot reload for development
- Debug logging enabled
- Development tools (PgAdmin, Redis Commander)

**Production** (`docker-compose.production.yml`):
- PostgreSQL with performance tuning
- Redis with persistence
- Multi-worker Gunicorn
- NGINX reverse proxy
- Security hardening
- Resource limits
- Health checks
- Monitoring stack (optional)

### Environment Configuration

**Development (.env)**:
```bash
# Core settings
LANGFUSE_SECRET_KEY=sk-lf-dev-key
LANGFUSE_PUBLIC_KEY=pk-lf-dev-key
SECRET_KEY=dev-secret-key-min-32-chars

# Database
POSTGRES_PASSWORD=dev_password_123
REDIS_PASSWORD=dev_redis_123

# URLs
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Production (.env.production)**:
```bash
# Core settings (use strong values)
LANGFUSE_SECRET_KEY=sk-lf-prod-key
LANGFUSE_PUBLIC_KEY=pk-lf-prod-key
SECRET_KEY=prod-secret-key-min-32-chars-very-secure

# Database
POSTGRES_PASSWORD=very-secure-db-password
REDIS_PASSWORD=very-secure-redis-password

# Production URLs
CORS_ORIGINS=https://your-domain.com,https://api.your-domain.com
NEXT_PUBLIC_API_URL=https://api.your-domain.com
TRUSTED_HOSTS=your-domain.com,api.your-domain.com

# Monitoring
SENTRY_DSN=https://xxx@sentry.io/xxx
GRAFANA_PASSWORD=admin-password
```

### Security Best Practices
- Non-root containers
- Multi-stage builds for minimal images
- Secrets management via Docker secrets
- Network isolation
- Resource limits
- Health checks
- Read-only file systems where possible

## Kubernetes Deployment

### Architecture Overview
The Kubernetes deployment provides:
- **High Availability**: Multiple replicas with anti-affinity
- **Auto-scaling**: HPA and VPA for dynamic scaling
- **Service Mesh**: Ingress with SSL termination
- **Storage**: Persistent volumes for data
- **Monitoring**: Prometheus and Grafana integration
- **Security**: RBAC, network policies, secrets management

### Cluster Requirements
```bash
# Minimum cluster specifications
# - 3 worker nodes (2 CPU, 4GB RAM each)
# - LoadBalancer service support
# - Persistent volume provisioner
# - Ingress controller (NGINX recommended)
# - cert-manager (for SSL certificates)
```

### Prerequisites Setup
```bash
# 1. Install required tools
kubectl version --client
helm version

# 2. Install NGINX Ingress Controller
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --set controller.replicaCount=2

# 3. Install cert-manager (for SSL)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# 4. Install metrics-server (for HPA)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Secrets Management
```bash
# Create secrets directory
mkdir -p secrets

# Generate secrets
echo "your-secure-postgres-password" > secrets/postgres_password.txt
echo "your-secure-app-secret-32-chars-min" > secrets/secret_key.txt
echo "sk-lf-your-langfuse-secret-key" > secrets/langfuse_secret_key.txt

# Create Kubernetes secrets
kubectl create secret generic llm-eval-secrets \
  --from-file=POSTGRES_PASSWORD=secrets/postgres_password.txt \
  --from-file=SECRET_KEY=secrets/secret_key.txt \
  --from-file=LANGFUSE_SECRET_KEY=secrets/langfuse_secret_key.txt \
  --namespace=llm-eval

# SSL certificates (Let's Encrypt)
kubectl create secret tls llm-eval-tls \
  --cert=ssl/cert.pem \
  --key=ssl/key.pem \
  --namespace=llm-eval
```

### Deployment Steps
```bash
# 1. Apply namespace and RBAC
kubectl apply -f k8s/namespace.yaml

# 2. Apply configuration
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml  # Update with your values first

# 3. Deploy database and cache
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml

# Wait for database to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n llm-eval --timeout=300s

# 4. Deploy application services
kubectl apply -f k8s/api.yaml
kubectl apply -f k8s/frontend.yaml

# Wait for deployments
kubectl wait --for=condition=available deployment/llm-eval-api -n llm-eval --timeout=300s

# 5. Deploy networking
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
```

### Resource Management
```yaml
# Production resource specifications
API Resources:
  requests: { cpu: 500m, memory: 1Gi }
  limits: { cpu: 2, memory: 4Gi }
  replicas: 3-10 (auto-scaling)

Frontend Resources:
  requests: { cpu: 100m, memory: 256Mi }
  limits: { cpu: 500m, memory: 1Gi }
  replicas: 2-6 (auto-scaling)

PostgreSQL Resources:
  requests: { cpu: 250m, memory: 512Mi }
  limits: { cpu: 1, memory: 2Gi }
  storage: 20Gi SSD

Redis Resources:
  requests: { cpu: 100m, memory: 256Mi }
  limits: { cpu: 500m, memory: 768Mi }
  storage: 2Gi SSD
```

### High Availability Features
```yaml
# Anti-affinity for pod distribution
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: llm-eval-api
        topologyKey: kubernetes.io/hostname

# Pod Disruption Budget
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: llm-eval-api-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: llm-eval-api

# Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-eval-api-hpa
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        averageUtilization: 70
```

### SSL/TLS and Ingress
```yaml
# Ingress with SSL termination and WebSocket support
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: llm-eval-ingress
  annotations:
    # SSL
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    
    # WebSocket support
    nginx.ingress.kubernetes.io/websocket-services: "llm-eval-api"
    nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
    
    # Security headers
    nginx.ingress.kubernetes.io/server-snippet: |
      add_header X-Frame-Options "SAMEORIGIN" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Strict-Transport-Security "max-age=31536000" always;
    
    # Rate limiting
    nginx.ingress.kubernetes.io/rate-limit: "1000"
spec:
  tls:
  - hosts: ["llm-eval.example.com", "api.llm-eval.example.com"]
    secretName: llm-eval-tls
  rules:
  - host: llm-eval.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service: { name: llm-eval-api, port: { number: 80 } }
      - path: /
        pathType: Prefix
        backend:
          service: { name: llm-eval-frontend, port: { number: 80 } }
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

## Automated Scripts

### Deployment Script
Comprehensive deployment automation:

```bash
# Usage: ./scripts/deploy.sh [docker|k8s] [dev|staging|prod]

# Features:
# - Prerequisite checking
# - Environment validation  
# - Image building (Docker)
# - Service deployment
# - Health verification
# - Rollback on failure

# Examples:
./scripts/deploy.sh docker dev       # Local development
./scripts/deploy.sh docker prod      # Docker production
./scripts/deploy.sh k8s staging      # Kubernetes staging
./scripts/deploy.sh k8s prod         # Kubernetes production
```

### Health Check Script
Post-deployment validation:

```bash
# Usage: ./scripts/health_check.sh [docker|k8s] [api_url] [frontend_url]

# Checks:
# - API health endpoint
# - Frontend accessibility
# - Database connectivity
# - Redis connectivity
# - WebSocket functionality
# - Performance baseline
# - Resource usage

# Examples:
./scripts/health_check.sh docker
./scripts/health_check.sh k8s https://api.example.com https://example.com
```

### Rollback Script
Quick recovery from failed deployments:

```bash
# Usage: ./scripts/rollback.sh [docker|k8s] [backup_tag]

# Features:
# - Automatic backup before rollback
# - Tag-specific rollback
# - Database restoration
# - Health verification
# - Rollback verification

# Examples:
./scripts/rollback.sh docker          # Rollback to previous
./scripts/rollback.sh k8s 0.2.5       # Rollback to specific version
./scripts/rollback.sh list             # List available backups
```

---

## Security

### Container Security
```bash
# Security best practices implemented:
# - Non-root containers
# - Read-only root filesystems
# - Minimal base images (Alpine/distroless)
# - Security context constraints
# - Network policies
# - Resource limits
# - Health checks

# Vulnerability scanning
docker scan llm-eval:latest

# Security audit
kubectl auth can-i --list --as=system:serviceaccount:llm-eval:llm-eval-api
```

### Secrets Management
```bash
# Kubernetes secrets (recommended)
kubectl create secret generic llm-eval-secrets \
  --from-literal=DATABASE_URL="postgresql://.." \
  --from-literal=SECRET_KEY=".." \
  --namespace=llm-eval

# External secret management (production)
# - AWS Secrets Manager
# - Azure Key Vault
# - HashiCorp Vault
# - External Secrets Operator
```

### Network Security
```yaml
# Network policies for traffic isolation
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: llm-eval-network-policy
  namespace: llm-eval
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: llm-eval
  policyTypes: ["Ingress", "Egress"]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443  # HTTPS only
```

---

## Monitoring & Logging

### Prometheus Metrics
```yaml
# Application metrics exposed
# - API request rates and latencies
# - Database connection pool usage
# - Redis cache hit/miss rates
# - WebSocket connection counts
# - Custom business metrics

# Prometheus configuration
scrape_configs:
- job_name: 'llm-eval-api'
  kubernetes_sd_configs:
  - role: pod
  relabel_configs:
  - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
    action: keep
    regex: true
```

### Grafana Dashboards
```bash
# Pre-built dashboards for:
# - Application overview
# - Database performance
# - API performance
# - Infrastructure metrics
# - Business metrics (evaluation runs, success rates)

# Import dashboard
grafana-cli --config /etc/grafana/grafana.ini admin import-dashboard dashboard.json
```

### Log Management
```yaml
# Centralized logging with Loki
# - Structured JSON logs
# - Log correlation by request ID
# - Error aggregation and alerting
# - Log retention policies

# Promtail configuration for log collection
server:
  http_listen_port: 9080
positions:
  filename: /tmp/positions.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
scrape_configs:
- job_name: kubernetes-pods
  kubernetes_sd_configs:
  - role: pod
```

### Alerting
```yaml
# Critical alerts
# - API response time > 2s
# - Error rate > 5%
# - Database connections > 90%
# - Pod crash loops
# - Disk usage > 80%

# AlertManager configuration
groups:
- name: llm-eval-alerts
  rules:
  - alert: APIHighLatency
    expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
    labels:
      severity: warning
    annotations:
      summary: "High API latency detected"
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
**Version:** 0.3.0  
**Status:** Production Ready

---

## Quick Reference

### Essential Commands

**Docker Development:**
```bash
./scripts/deploy.sh docker dev
./scripts/health_check.sh docker
docker-compose logs -f
```

**Docker Production:**
```bash
./scripts/deploy.sh docker prod
./scripts/health_check.sh docker
./scripts/rollback.sh docker
```

**Kubernetes Production:**
```bash
./scripts/deploy.sh k8s prod
./scripts/health_check.sh k8s
kubectl get pods -n llm-eval
kubectl logs -f deployment/llm-eval-api -n llm-eval
```

### Service URLs
- **API**: `https://api.your-domain.com`
- **Frontend**: `https://your-domain.com`
- **API Docs**: `https://api.your-domain.com/api/docs`
- **Health Check**: `https://api.your-domain.com/api/health`

### Support Resources
- **Repository**: https://github.com/faisalx96/llm-eval
- **Documentation**: /docs/
- **Issue Tracker**: GitHub Issues
- **Deployment Logs**: `./logs/deploy_*.log`

For additional support, run health checks and review logs before opening issues.