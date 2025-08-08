#!/bin/bash

# LLM-Eval Health Check Script
# Comprehensive post-deployment validation
# Usage: ./scripts/health_check.sh [docker|k8s] [api_url] [frontend_url]

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DEPLOYMENT_TYPE="${1:-docker}"
API_URL="${2:-http://localhost:8000}"
FRONTEND_URL="${3:-http://localhost:3000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
LOG_FILE="${PROJECT_ROOT}/logs/health_check_$(date +%Y%m%d_%H%M%S).log"

# Health check results
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

# Ensure logs directory exists
mkdir -p "${PROJECT_ROOT}/logs"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "${LOG_FILE}"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "${LOG_FILE}"
    ((PASSED_CHECKS++))
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "${LOG_FILE}"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "${LOG_FILE}"
    ((FAILED_CHECKS++))
}

increment_total() {
    ((TOTAL_CHECKS++))
}

# Function to check API health endpoint
check_api_health() {
    log_info "Checking API health endpoint..."
    increment_total
    
    local response
    local http_code
    
    if response=$(curl -s -w "%{http_code}" "${API_URL}/api/health" --max-time 10); then
        http_code="${response: -3}"
        response_body="${response%???}"
        
        if [[ "${http_code}" == "200" ]]; then
            log_success "API health endpoint is responding (HTTP 200)"
            
            # Check response content
            if echo "${response_body}" | grep -q '"status":"healthy"'; then
                log_success "API reports healthy status"
            elif echo "${response_body}" | grep -q '"status":"degraded"'; then
                log_warning "API reports degraded status: ${response_body}"
            else
                log_error "API health response format unexpected: ${response_body}"
            fi
        else
            log_error "API health endpoint returned HTTP ${http_code}: ${response_body}"
        fi
    else
        log_error "Failed to reach API health endpoint at ${API_URL}/api/health"
    fi
}

# Function to check API documentation
check_api_docs() {
    log_info "Checking API documentation..."
    increment_total
    
    local http_code
    if http_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/api/docs" --max-time 10); then
        if [[ "${http_code}" == "200" ]]; then
            log_success "API documentation is accessible"
        else
            log_error "API documentation returned HTTP ${http_code}"
        fi
    else
        log_error "Failed to reach API documentation at ${API_URL}/api/docs"
    fi
}

# Function to check API endpoints
check_api_endpoints() {
    log_info "Checking API endpoints..."
    
    # Check runs endpoint
    increment_total
    local http_code
    if http_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/api/runs" --max-time 10); then
        if [[ "${http_code}" == "200" ]]; then
            log_success "Runs endpoint is accessible"
        else
            log_error "Runs endpoint returned HTTP ${http_code}"
        fi
    else
        log_error "Failed to reach runs endpoint"
    fi
    
    # Check OpenAPI spec
    increment_total
    if http_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/api/openapi.json" --max-time 10); then
        if [[ "${http_code}" == "200" ]]; then
            log_success "OpenAPI specification is accessible"
        else
            log_error "OpenAPI specification returned HTTP ${http_code}"
        fi
    else
        log_error "Failed to reach OpenAPI specification"
    fi
}

# Function to check frontend
check_frontend() {
    log_info "Checking frontend..."
    increment_total
    
    local http_code
    if http_code=$(curl -s -o /dev/null -w "%{http_code}" "${FRONTEND_URL}" --max-time 10); then
        if [[ "${http_code}" == "200" ]]; then
            log_success "Frontend is accessible"
        else
            log_error "Frontend returned HTTP ${http_code}"
        fi
    else
        log_error "Failed to reach frontend at ${FRONTEND_URL}"
    fi
}

# Function to check WebSocket connectivity
check_websocket() {
    log_info "Checking WebSocket connectivity..."
    increment_total
    
    # Use wscat if available, otherwise skip
    if command -v wscat &> /dev/null; then
        local ws_url
        ws_url="${API_URL/http/ws}/ws/health"
        
        if timeout 5 wscat -c "${ws_url}" --close &> /dev/null; then
            log_success "WebSocket connection is working"
        else
            log_error "WebSocket connection failed"
        fi
    else
        log_warning "wscat not available, skipping WebSocket test (install with: npm install -g wscat)"
    fi
}

# Function to check Docker services
check_docker_services() {
    log_info "Checking Docker services..."
    
    cd "${PROJECT_ROOT}"
    
    # Check if services are running
    local services=("postgres" "redis" "api" "frontend")
    
    for service in "${services[@]}"; do
        increment_total
        if docker-compose ps "${service}" 2>/dev/null | grep -q "Up"; then
            log_success "Docker service '${service}' is running"
        else
            log_error "Docker service '${service}' is not running"
        fi
    done
    
    # Check service logs for errors
    log_info "Checking service logs for recent errors..."
    if docker-compose logs --tail=50 api 2>/dev/null | grep -i "error\|exception\|failed" | head -5; then
        log_warning "Recent errors found in API logs"
    fi
}

# Function to check Kubernetes services
check_k8s_services() {
    log_info "Checking Kubernetes services..."
    
    # Check namespace
    increment_total
    if kubectl get namespace llm-eval &> /dev/null; then
        log_success "Namespace 'llm-eval' exists"
    else
        log_error "Namespace 'llm-eval' not found"
        return
    fi
    
    # Check deployments
    local deployments=("llm-eval-api" "llm-eval-frontend" "postgres" "redis")
    
    for deployment in "${deployments[@]}"; do
        increment_total
        if kubectl get deployment "${deployment}" -n llm-eval &> /dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get deployment "${deployment}" -n llm-eval -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired_replicas
            desired_replicas=$(kubectl get deployment "${deployment}" -n llm-eval -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
            
            if [[ "${ready_replicas}" == "${desired_replicas}" ]] && [[ "${ready_replicas}" -gt 0 ]]; then
                log_success "Deployment '${deployment}' is ready (${ready_replicas}/${desired_replicas})"
            else
                log_error "Deployment '${deployment}' is not ready (${ready_replicas}/${desired_replicas})"
            fi
        elif kubectl get statefulset "${deployment}" -n llm-eval &> /dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get statefulset "${deployment}" -n llm-eval -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            
            if [[ "${ready_replicas}" -gt 0 ]]; then
                log_success "StatefulSet '${deployment}' is ready"
            else
                log_error "StatefulSet '${deployment}' is not ready"
            fi
        else
            log_error "Deployment/StatefulSet '${deployment}' not found"
        fi
    done
    
    # Check services
    increment_total
    if kubectl get svc -n llm-eval | grep -q "llm-eval-api"; then
        log_success "API service is available"
    else
        log_error "API service not found"
    fi
    
    increment_total
    if kubectl get svc -n llm-eval | grep -q "llm-eval-frontend"; then
        log_success "Frontend service is available"
    else
        log_error "Frontend service not found"
    fi
    
    # Check ingress
    increment_total
    if kubectl get ingress -n llm-eval &> /dev/null; then
        log_success "Ingress is configured"
    else
        log_warning "No ingress found (may be intentional)"
    fi
}

# Function to check database connectivity
check_database() {
    log_info "Checking database connectivity..."
    increment_total
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        # Try to connect to PostgreSQL via Docker
        if docker-compose exec -T postgres psql -U llm_eval -d llm_eval -c "SELECT 1;" &> /dev/null; then
            log_success "Database connection is working"
        else
            log_error "Database connection failed"
        fi
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Try to connect via kubectl
        if kubectl exec -n llm-eval statefulset/postgres -- psql -U llm_eval -d llm_eval -c "SELECT 1;" &> /dev/null; then
            log_success "Database connection is working"
        else
            log_error "Database connection failed"
        fi
    fi
}

# Function to check Redis connectivity
check_redis() {
    log_info "Checking Redis connectivity..."
    increment_total
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        # Try to ping Redis via Docker
        if docker-compose exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
            log_success "Redis connection is working"
        else
            log_error "Redis connection failed"
        fi
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Try to connect via kubectl
        if kubectl exec -n llm-eval deployment/redis -- redis-cli ping 2>/dev/null | grep -q "PONG"; then
            log_success "Redis connection is working"
        else
            log_error "Redis connection failed"
        fi
    fi
}

# Function to check resource usage
check_resources() {
    log_info "Checking resource usage..."
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        # Check Docker resource usage
        log_info "Docker container resource usage:"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || log_warning "Could not get Docker stats"
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        # Check Kubernetes resource usage
        log_info "Kubernetes pod resource usage:"
        kubectl top pods -n llm-eval 2>/dev/null || log_warning "Could not get pod metrics (metrics-server may not be installed)"
    fi
}

# Function to run performance test
run_performance_test() {
    log_info "Running basic performance test..."
    increment_total
    
    # Simple load test using curl
    local start_time
    local end_time
    local duration
    
    start_time=$(date +%s)
    
    # Make 10 concurrent requests
    local success_count=0
    for i in {1..10}; do
        if curl -s "${API_URL}/api/health" --max-time 5 > /dev/null; then
            ((success_count++))
        fi &
    done
    wait
    
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    
    if [[ ${success_count} -ge 8 ]]; then
        log_success "Performance test passed (${success_count}/10 requests succeeded in ${duration}s)"
    else
        log_error "Performance test failed (${success_count}/10 requests succeeded in ${duration}s)"
    fi
}

# Function to generate health report
generate_report() {
    echo ""
    echo -e "${BLUE}=== Health Check Summary ===${NC}"
    echo -e "Total checks: ${TOTAL_CHECKS}"
    echo -e "${GREEN}Passed: ${PASSED_CHECKS}${NC}"
    echo -e "${RED}Failed: ${FAILED_CHECKS}${NC}"
    echo ""
    
    local success_rate
    if [[ ${TOTAL_CHECKS} -gt 0 ]]; then
        success_rate=$(( PASSED_CHECKS * 100 / TOTAL_CHECKS ))
        echo -e "Success rate: ${success_rate}%"
    fi
    
    echo -e "Log file: ${LOG_FILE}"
    echo ""
    
    if [[ ${FAILED_CHECKS} -eq 0 ]]; then
        echo -e "${GREEN}✅ All health checks passed!${NC}"
        return 0
    elif [[ ${success_rate} -ge 80 ]]; then
        echo -e "${YELLOW}⚠️  Some health checks failed, but system is mostly healthy${NC}"
        return 0
    else
        echo -e "${RED}❌ Multiple health checks failed - system may not be functioning properly${NC}"
        return 1
    fi
}

# Function to display usage
usage() {
    echo "Usage: $0 [docker|k8s] [api_url] [frontend_url]"
    echo ""
    echo "Arguments:"
    echo "  docker|k8s     Deployment type (default: docker)"
    echo "  api_url        API URL (default: http://localhost:8000)"
    echo "  frontend_url   Frontend URL (default: http://localhost:3000)"
    echo ""
    echo "Examples:"
    echo "  $0 docker"
    echo "  $0 k8s https://api.llm-eval.com https://llm-eval.com"
}

# Main execution
main() {
    echo -e "${GREEN}LLM-Eval Health Check${NC}"
    echo -e "Deployment: ${BLUE}${DEPLOYMENT_TYPE}${NC}"
    echo -e "API URL: ${BLUE}${API_URL}${NC}"
    echo -e "Frontend URL: ${BLUE}${FRONTEND_URL}${NC}"
    echo ""
    
    # Validate arguments
    if [[ ! "${DEPLOYMENT_TYPE}" =~ ^(docker|k8s)$ ]]; then
        log_error "Invalid deployment type: ${DEPLOYMENT_TYPE}"
        usage
        exit 1
    fi
    
    # Run health checks
    check_api_health
    check_api_docs
    check_api_endpoints
    check_frontend
    check_websocket
    
    if [[ "${DEPLOYMENT_TYPE}" == "docker" ]]; then
        check_docker_services
    elif [[ "${DEPLOYMENT_TYPE}" == "k8s" ]]; then
        check_k8s_services
    fi
    
    check_database
    check_redis
    check_resources
    run_performance_test
    
    # Generate final report
    generate_report
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi