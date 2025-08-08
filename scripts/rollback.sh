#!/bin/bash

# LLM-Eval Rollback Script
# Quick rollback mechanism for failed deployments
# Usage: ./scripts/rollback.sh [docker|k8s] [backup_tag]

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DEPLOYMENT_TYPE="${1:-docker}"
BACKUP_TAG="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
LOG_FILE="${PROJECT_ROOT}/logs/rollback_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="${PROJECT_ROOT}/backups"

# Ensure logs and backup directories exist
mkdir -p "${PROJECT_ROOT}/logs" "${BACKUP_DIR}"

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

# Function to create backup before rollback
create_backup() {
    log_info "Creating backup before rollback..."
    
    local backup_name="pre_rollback_$(date +%Y%m%d_%H%M%S)"
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        # Backup Docker volumes and configuration
        cd "${PROJECT_ROOT}"
        
        # Create backup directory
        mkdir -p "${BACKUP_DIR}/${backup_name}"
        
        # Backup database
        log_info "Backing up database..."
        if docker-compose exec -T postgres pg_dump -U llm_eval llm_eval > "${BACKUP_DIR}/${backup_name}/database.sql" 2>/dev/null; then
            log_success "Database backup created"
        else
            log_warning "Failed to backup database"
        fi
        
        # Backup application data
        if [[ -d "data" ]]; then
            cp -r data "${BACKUP_DIR}/${backup_name}/"
            log_success "Application data backed up"
        fi
        
        # Backup configuration
        cp docker-compose*.yml "${BACKUP_DIR}/${backup_name}/" 2>/dev/null || true
        cp .env* "${BACKUP_DIR}/${backup_name}/" 2>/dev/null || true
        
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Backup Kubernetes resources
        mkdir -p "${BACKUP_DIR}/${backup_name}/k8s"
        
        # Backup database
        log_info "Backing up database..."
        if kubectl exec -n llm-eval statefulset/postgres -- pg_dump -U llm_eval llm_eval > "${BACKUP_DIR}/${backup_name}/database.sql" 2>/dev/null; then
            log_success "Database backup created"
        else
            log_warning "Failed to backup database"
        fi
        
        # Backup Kubernetes manifests
        kubectl get all -n llm-eval -o yaml > "${BACKUP_DIR}/${backup_name}/k8s/all-resources.yaml" 2>/dev/null || true
        kubectl get configmaps -n llm-eval -o yaml > "${BACKUP_DIR}/${backup_name}/k8s/configmaps.yaml" 2>/dev/null || true
        kubectl get secrets -n llm-eval -o yaml > "${BACKUP_DIR}/${backup_name}/k8s/secrets.yaml" 2>/dev/null || true
    fi
    
    log_success "Backup created: ${backup_name}"
    echo "${backup_name}" > "${BACKUP_DIR}/latest_backup.txt"
}

# Function to rollback Docker deployment
rollback_docker() {
    log_info "Rolling back Docker deployment..."
    
    cd "${PROJECT_ROOT}"
    
    # Stop current services
    log_info "Stopping current services..."
    docker-compose down --remove-orphans
    
    if [[ -n "${BACKUP_TAG}" ]]; then
        # Rollback to specific tag
        log_info "Rolling back to tag: ${BACKUP_TAG}"
        
        # Update docker-compose to use backup tag
        if [[ -f "docker-compose.yml" ]]; then
            sed -i.bak "s/llm-eval:latest/llm-eval:${BACKUP_TAG}/g" docker-compose.yml
            sed -i.bak "s/llm-eval-frontend:latest/llm-eval-frontend:${BACKUP_TAG}/g" docker-compose.yml
        fi
        
        # Pull backup images
        docker pull "llm-eval:${BACKUP_TAG}" || log_error "Failed to pull llm-eval:${BACKUP_TAG}"
        docker pull "llm-eval-frontend:${BACKUP_TAG}" || log_error "Failed to pull llm-eval-frontend:${BACKUP_TAG}"
        
    else
        # Rollback to previous backup
        local latest_backup
        if [[ -f "${BACKUP_DIR}/latest_backup.txt" ]]; then
            latest_backup=$(cat "${BACKUP_DIR}/latest_backup.txt")
            log_info "Rolling back to latest backup: ${latest_backup}"
            
            # Restore configuration if available
            if [[ -d "${BACKUP_DIR}/${latest_backup}" ]]; then
                cp "${BACKUP_DIR}/${latest_backup}"/docker-compose*.yml . 2>/dev/null || true
                cp "${BACKUP_DIR}/${latest_backup}"/.env* . 2>/dev/null || true
                
                # Restore application data
                if [[ -d "${BACKUP_DIR}/${latest_backup}/data" ]]; then
                    rm -rf data
                    cp -r "${BACKUP_DIR}/${latest_backup}/data" .
                    log_success "Application data restored"
                fi
            fi
        else
            log_warning "No backup found, using current configuration"
        fi
    fi
    
    # Start services
    log_info "Starting services..."
    docker-compose up -d
    
    # Wait for services
    sleep 30
    
    # Verify rollback
    verify_rollback_docker
}

# Function to rollback Kubernetes deployment
rollback_k8s() {
    log_info "Rolling back Kubernetes deployment..."
    
    if [[ -n "${BACKUP_TAG}" ]]; then
        # Rollback to specific tag
        log_info "Rolling back to tag: ${BACKUP_TAG}"
        
        # Update deployment images
        kubectl set image deployment/llm-eval-api api="llm-eval:${BACKUP_TAG}" -n llm-eval
        kubectl set image deployment/llm-eval-frontend frontend="llm-eval-frontend:${BACKUP_TAG}" -n llm-eval
        
        # Wait for rollout
        kubectl rollout status deployment/llm-eval-api -n llm-eval --timeout=300s
        kubectl rollout status deployment/llm-eval-frontend -n llm-eval --timeout=300s
        
    else
        # Use Kubernetes rollback feature
        log_info "Using Kubernetes native rollback..."
        
        # Rollback API deployment
        kubectl rollout undo deployment/llm-eval-api -n llm-eval
        kubectl rollout status deployment/llm-eval-api -n llm-eval --timeout=300s
        
        # Rollback frontend deployment
        kubectl rollout undo deployment/llm-eval-frontend -n llm-eval
        kubectl rollout status deployment/llm-eval-frontend -n llm-eval --timeout=300s
    fi
    
    # Verify rollback
    verify_rollback_k8s
}

# Function to restore database
restore_database() {
    local backup_file="${1:-}"
    
    if [[ -z "${backup_file}" ]]; then
        local latest_backup
        if [[ -f "${BACKUP_DIR}/latest_backup.txt" ]]; then
            latest_backup=$(cat "${BACKUP_DIR}/latest_backup.txt")
            backup_file="${BACKUP_DIR}/${latest_backup}/database.sql"
        else
            log_warning "No database backup found to restore"
            return
        fi
    fi
    
    if [[ ! -f "${backup_file}" ]]; then
        log_warning "Database backup file not found: ${backup_file}"
        return
    fi
    
    log_info "Restoring database from: ${backup_file}"
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        # Restore via Docker
        if docker-compose exec -T postgres psql -U llm_eval -d llm_eval < "${backup_file}"; then
            log_success "Database restored successfully"
        else
            log_error "Failed to restore database"
        fi
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Restore via Kubernetes
        if kubectl exec -i -n llm-eval statefulset/postgres -- psql -U llm_eval -d llm_eval < "${backup_file}"; then
            log_success "Database restored successfully"
        else
            log_error "Failed to restore database"
        fi
    fi
}

# Function to verify Docker rollback
verify_rollback_docker() {
    log_info "Verifying Docker rollback..."
    
    # Check if services are running
    local services=("postgres" "redis" "api" "frontend")
    local all_healthy=true
    
    for service in "${services[@]}"; do
        if docker-compose ps "${service}" 2>/dev/null | grep -q "Up"; then
            log_success "Service '${service}' is running"
        else
            log_error "Service '${service}' is not running"
            all_healthy=false
        fi
    done
    
    # Check API health
    sleep 10  # Give services time to start
    for i in {1..30}; do
        if curl -f http://localhost:8000/api/health &> /dev/null; then
            log_success "API health check passed"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "API health check failed after rollback"
            all_healthy=false
        fi
        sleep 2
    done
    
    # Check frontend
    for i in {1..30}; do
        if curl -f http://localhost:3000 &> /dev/null; then
            log_success "Frontend health check passed"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "Frontend health check failed after rollback"
            all_healthy=false
        fi
        sleep 2
    done
    
    if [[ "${all_healthy}" == true ]]; then
        log_success "Rollback verification passed"
    else
        log_error "Rollback verification failed"
    fi
}

# Function to verify Kubernetes rollback
verify_rollback_k8s() {
    log_info "Verifying Kubernetes rollback..."
    
    # Check deployment status
    local deployments=("llm-eval-api" "llm-eval-frontend")
    local all_healthy=true
    
    for deployment in "${deployments[@]}"; do
        if kubectl get deployment "${deployment}" -n llm-eval &> /dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get deployment "${deployment}" -n llm-eval -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired_replicas
            desired_replicas=$(kubectl get deployment "${deployment}" -n llm-eval -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
            
            if [[ "${ready_replicas}" == "${desired_replicas}" ]] && [[ "${ready_replicas}" -gt 0 ]]; then
                log_success "Deployment '${deployment}' is healthy after rollback"
            else
                log_error "Deployment '${deployment}' is not healthy after rollback"
                all_healthy=false
            fi
        fi
    done
    
    # Test service endpoints
    local api_service_ip
    api_service_ip=$(kubectl get svc llm-eval-api -n llm-eval -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -n "${api_service_ip}" ]]; then
        if curl -f "http://${api_service_ip}/api/health" &> /dev/null; then
            log_success "API service is responding after rollback"
        else
            log_warning "API service not responding (may need time to propagate)"
        fi
    fi
    
    if [[ "${all_healthy}" == true ]]; then
        log_success "Rollback verification passed"
    else
        log_error "Rollback verification failed"
    fi
}

# Function to list available backups
list_backups() {
    log_info "Available backups:"
    
    if [[ -d "${BACKUP_DIR}" ]]; then
        for backup in "${BACKUP_DIR}"/*/; do
            if [[ -d "${backup}" ]]; then
                local backup_name
                backup_name=$(basename "${backup}")
                local backup_date
                backup_date=$(date -d "${backup_name//_/ }" 2>/dev/null || echo "Unknown")
                echo "  ${backup_name} (${backup_date})"
            fi
        done
    else
        log_warning "No backup directory found"
    fi
    
    # List Docker image tags
    if command -v docker &> /dev/null; then
        log_info "Available Docker image tags:"
        docker images llm-eval --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}" 2>/dev/null || true
        docker images llm-eval-frontend --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}" 2>/dev/null || true
    fi
}

# Function to display usage
usage() {
    echo "Usage: $0 [docker|k8s] [backup_tag]"
    echo ""
    echo "Arguments:"
    echo "  docker|k8s     Deployment type (default: docker)"
    echo "  backup_tag     Specific tag/version to rollback to (optional)"
    echo ""
    echo "Commands:"
    echo "  $0 list        List available backups"
    echo ""
    echo "Examples:"
    echo "  $0 docker                    # Rollback to previous version"
    echo "  $0 docker 0.2.5             # Rollback to specific tag"
    echo "  $0 k8s                       # Kubernetes rollback"
    echo "  $0 list                      # List available backups"
}

# Main execution
main() {
    echo -e "${GREEN}LLM-Eval Rollback Script${NC}"
    echo ""
    
    # Handle special commands
    if [[ "${DEPLOYMENT_TYPE}" == "list" ]]; then
        list_backups
        exit 0
    fi
    
    # Validate arguments
    if [[ ! "${DEPLOYMENT_TYPE}" =~ ^(docker|k8s)$ ]]; then
        log_error "Invalid deployment type: ${DEPLOYMENT_TYPE}"
        usage
        exit 1
    fi
    
    log_info "Starting rollback process..."
    log_info "Deployment type: ${DEPLOYMENT_TYPE}"
    if [[ -n "${BACKUP_TAG}" ]]; then
        log_info "Target version: ${BACKUP_TAG}"
    fi
    
    # Confirm rollback
    echo -e "${YELLOW}WARNING: This will rollback your deployment. Continue? (y/N)${NC}"
    read -r -n 1 confirm
    echo ""
    if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
        log_info "Rollback cancelled by user"
        exit 0
    fi
    
    # Create backup before rollback
    create_backup
    
    # Perform rollback
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        rollback_docker
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        rollback_k8s
    fi
    
    log_success "Rollback completed!"
    log_info "Log file: ${LOG_FILE}"
    
    # Optional: offer to restore database
    echo -e "${YELLOW}Do you want to restore the database from backup? (y/N)${NC}"
    read -r -n 1 restore_db
    echo ""
    if [[ "${restore_db}" =~ ^[Yy]$ ]]; then
        restore_database
    fi
    
    echo -e "${GREEN}Rollback process completed!${NC}"
    echo "Run the health check script to verify the rollback:"
    echo "  ./scripts/health_check.sh ${DEPLOYMENT_TYPE}"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi