#!/bin/bash

# LLM-Eval Automated Deployment Script
# Supports Docker Compose and Kubernetes deployments
# Usage: ./scripts/deploy.sh [docker|k8s] [dev|staging|prod]

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DEPLOYMENT_TYPE="${1:-docker}"
ENVIRONMENT="${2:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
LOG_FILE="${PROJECT_ROOT}/logs/deploy_$(date +%Y%m%d_%H%M%S).log"

# Ensure logs directory exists
mkdir -p "${PROJECT_ROOT}/logs"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "${LOG_FILE}"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "${LOG_FILE}"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "${LOG_FILE}"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "${LOG_FILE}"
}

# Function to check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        if ! command -v docker &> /dev/null; then
            log_error "Docker is not installed"
            exit 1
        fi
        
        if ! command -v docker-compose &> /dev/null; then
            log_error "Docker Compose is not installed"
            exit 1
        fi
        
        # Check if Docker is running
        if ! docker info &> /dev/null; then
            log_error "Docker daemon is not running"
            exit 1
        fi
        
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        if ! command -v kubectl &> /dev/null; then
            log_error "kubectl is not installed"
            exit 1
        fi
        
        if ! command -v helm &> /dev/null; then
            log_warning "Helm is not installed (optional)"
        fi
        
        # Check cluster connectivity
        if ! kubectl cluster-info &> /dev/null; then
            log_error "Cannot connect to Kubernetes cluster"
            exit 1
        fi
    fi
    
    log_success "Prerequisites check passed"
}

# Function to validate environment files
validate_environment() {
    log_info "Validating environment configuration..."
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        if [[ "${ENVIRONMENT}" == "prod" ]]; then
            ENV_FILE="${PROJECT_ROOT}/.env.production"
        else
            ENV_FILE="${PROJECT_ROOT}/.env"
        fi
        
        if [[ ! -f "${ENV_FILE}" ]]; then
            log_error "Environment file ${ENV_FILE} not found"
            log_info "Please create the environment file with required variables"
            exit 1
        fi
        
        # Check for required environment variables
        REQUIRED_VARS=("LANGFUSE_SECRET_KEY" "LANGFUSE_PUBLIC_KEY" "SECRET_KEY")
        for var in "${REQUIRED_VARS[@]}"; do
            if ! grep -q "^${var}=" "${ENV_FILE}"; then
                log_error "Required environment variable ${var} not found in ${ENV_FILE}"
                exit 1
            fi
        done
        
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Check if secrets exist
        if ! kubectl get secret llm-eval-secrets -n llm-eval &> /dev/null; then
            log_error "Kubernetes secret 'llm-eval-secrets' not found"
            log_info "Please create secrets using: kubectl apply -f k8s/secrets.yaml"
            exit 1
        fi
    fi
    
    log_success "Environment validation passed"
}

# Function to build Docker images
build_images() {
    log_info "Building Docker images..."
    
    cd "${PROJECT_ROOT}"
    
    # Build arguments
    BUILD_ARGS=(
        "--build-arg" "BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        "--build-arg" "VCS_REF=$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
        "--build-arg" "VERSION=0.3.0"
    )
    
    # Build backend image
    log_info "Building backend API image..."
    docker build "${BUILD_ARGS[@]}" -t llm-eval:latest -t llm-eval:0.3.0 .
    
    # Build frontend image
    log_info "Building frontend image..."
    cd frontend
    docker build "${BUILD_ARGS[@]}" -t llm-eval-frontend:latest -t llm-eval-frontend:0.3.0 .
    cd ..
    
    log_success "Docker images built successfully"
}

# Function to deploy with Docker Compose
deploy_docker() {
    log_info "Deploying with Docker Compose (${ENVIRONMENT})..."
    
    cd "${PROJECT_ROOT}"
    
    if [[ "${ENVIRONMENT}" == "prod" ]]; then
        COMPOSE_FILE="docker-compose.production.yml"
        ENV_FILE=".env.production"
    else
        COMPOSE_FILE="docker-compose.yml"
        ENV_FILE=".env"
    fi
    
    # Create necessary directories
    mkdir -p logs data backups ssl secrets
    
    # Stop existing services
    log_info "Stopping existing services..."
    docker-compose -f "${COMPOSE_FILE}" down --remove-orphans || true
    
    # Pull latest images if not building locally
    if [[ "${ENVIRONMENT}" == "prod" ]]; then
        log_info "Pulling latest production images..."
        docker-compose -f "${COMPOSE_FILE}" pull || true
    fi
    
    # Start services
    log_info "Starting services..."
    docker-compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d
    
    # Wait for services to be ready
    log_info "Waiting for services to be ready..."
    sleep 30
    
    # Check service health
    check_docker_health
    
    log_success "Docker deployment completed successfully"
    
    # Display service URLs
    display_docker_urls
}

# Function to deploy to Kubernetes
deploy_k8s() {
    log_info "Deploying to Kubernetes (${ENVIRONMENT})..."
    
    cd "${PROJECT_ROOT}"
    
    # Apply namespace first
    log_info "Creating namespace and RBAC..."
    kubectl apply -f k8s/namespace.yaml
    
    # Apply ConfigMaps and Secrets
    log_info "Applying configuration..."
    kubectl apply -f k8s/configmap.yaml
    kubectl apply -f k8s/secrets.yaml
    
    # Deploy database and cache
    log_info "Deploying PostgreSQL..."
    kubectl apply -f k8s/postgres.yaml
    
    log_info "Deploying Redis..."
    kubectl apply -f k8s/redis.yaml
    
    # Wait for database to be ready
    log_info "Waiting for database to be ready..."
    kubectl wait --for=condition=ready pod -l app=postgres -n llm-eval --timeout=300s
    
    log_info "Waiting for Redis to be ready..."
    kubectl wait --for=condition=ready pod -l app=redis -n llm-eval --timeout=300s
    
    # Deploy application services
    log_info "Deploying API..."
    kubectl apply -f k8s/api.yaml
    
    log_info "Deploying Frontend..."
    kubectl apply -f k8s/frontend.yaml
    
    # Deploy ingress and autoscaling
    log_info "Deploying Ingress..."
    kubectl apply -f k8s/ingress.yaml
    
    log_info "Deploying HPA..."
    kubectl apply -f k8s/hpa.yaml
    
    # Wait for deployments
    log_info "Waiting for API deployment..."
    kubectl wait --for=condition=available deployment/llm-eval-api -n llm-eval --timeout=300s
    
    log_info "Waiting for Frontend deployment..."
    kubectl wait --for=condition=available deployment/llm-eval-frontend -n llm-eval --timeout=300s
    
    # Check pod health
    check_k8s_health
    
    log_success "Kubernetes deployment completed successfully"
    
    # Display service information
    display_k8s_info
}

# Function to check Docker service health
check_docker_health() {
    log_info "Checking Docker service health..."
    
    # Check API health
    for i in {1..30}; do
        if curl -f http://localhost:8000/api/health &> /dev/null; then
            log_success "API is healthy"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "API health check failed"
            docker-compose logs api
            exit 1
        fi
        sleep 2
    done
    
    # Check frontend
    for i in {1..30}; do
        if curl -f http://localhost:3000 &> /dev/null; then
            log_success "Frontend is healthy"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "Frontend health check failed"
            docker-compose logs frontend
            exit 1
        fi
        sleep 2
    done
}

# Function to check Kubernetes service health
check_k8s_health() {
    log_info "Checking Kubernetes service health..."
    
    # Get service endpoints
    API_SERVICE=$(kubectl get svc llm-eval-api -n llm-eval -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    FRONTEND_SERVICE=$(kubectl get svc llm-eval-frontend -n llm-eval -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    # Check pod status
    kubectl get pods -n llm-eval
    
    # Verify all pods are running
    if kubectl get pods -n llm-eval --field-selector=status.phase!=Running --no-headers | grep -q .; then
        log_warning "Some pods are not running"
        kubectl describe pods -n llm-eval | grep -A 5 "Events:"
    else
        log_success "All pods are running"
    fi
}

# Function to display Docker service URLs
display_docker_urls() {
    echo ""
    log_success "=== Deployment Complete ==="
    echo -e "${BLUE}API:${NC} http://localhost:8000"
    echo -e "${BLUE}Frontend:${NC} http://localhost:3000"
    echo -e "${BLUE}API Documentation:${NC} http://localhost:8000/api/docs"
    
    if docker-compose ps pgadmin &> /dev/null; then
        echo -e "${BLUE}PgAdmin:${NC} http://localhost:5050"
    fi
    
    if docker-compose ps redis-commander &> /dev/null; then
        echo -e "${BLUE}Redis Commander:${NC} http://localhost:8081"
    fi
    
    echo ""
    echo -e "${YELLOW}Logs:${NC} docker-compose logs -f"
    echo -e "${YELLOW}Stop:${NC} docker-compose down"
    echo ""
}

# Function to display Kubernetes service information
display_k8s_info() {
    echo ""
    log_success "=== Deployment Complete ==="
    
    # Get service information
    kubectl get svc -n llm-eval
    echo ""
    
    # Get ingress information
    kubectl get ingress -n llm-eval
    echo ""
    
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  View pods: ${BLUE}kubectl get pods -n llm-eval${NC}"
    echo -e "  View logs: ${BLUE}kubectl logs -f deployment/llm-eval-api -n llm-eval${NC}"
    echo -e "  Port forward API: ${BLUE}kubectl port-forward svc/llm-eval-api 8000:80 -n llm-eval${NC}"
    echo -e "  Port forward Frontend: ${BLUE}kubectl port-forward svc/llm-eval-frontend 3000:80 -n llm-eval${NC}"
    echo ""
}

# Function to cleanup on failure
cleanup_on_failure() {
    log_error "Deployment failed. Cleaning up..."
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        docker-compose down --remove-orphans || true
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        kubectl delete namespace llm-eval --ignore-not-found=true || true
    fi
}

# Function to display usage
usage() {
    echo "Usage: $0 [docker|k8s] [dev|staging|prod]"
    echo ""
    echo "Arguments:"
    echo "  docker|k8s    Deployment type (default: docker)"
    echo "  dev|staging|prod  Environment (default: dev)"
    echo ""
    echo "Examples:"
    echo "  $0 docker dev       # Docker Compose development"
    echo "  $0 docker prod      # Docker Compose production"
    echo "  $0 k8s staging      # Kubernetes staging"
    echo "  $0 k8s prod         # Kubernetes production"
}

# Main execution
main() {
    echo -e "${GREEN}LLM-Eval Deployment Script${NC}"
    echo -e "Deployment: ${BLUE}${DEPLOYMENT_TYPE}${NC}, Environment: ${BLUE}${ENVIRONMENT}${NC}"
    echo ""
    
    # Validate arguments
    if [[ ! "${DEPLOYMENT_TYPE}" =~ ^(docker|k8s)$ ]]; then
        log_error "Invalid deployment type: ${DEPLOYMENT_TYPE}"
        usage
        exit 1
    fi
    
    if [[ ! "${ENVIRONMENT}" =~ ^(dev|staging|prod)$ ]]; then
        log_error "Invalid environment: ${ENVIRONMENT}"
        usage
        exit 1
    fi
    
    # Set trap for cleanup on failure
    trap cleanup_on_failure ERR
    
    # Run deployment steps
    check_prerequisites
    validate_environment
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        build_images
        deploy_docker
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # For K8s, images should be built and pushed to registry
        # build_images  # Uncomment if building locally
        deploy_k8s
    fi
    
    log_success "Deployment completed successfully!"
    log_info "Log file: ${LOG_FILE}"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi