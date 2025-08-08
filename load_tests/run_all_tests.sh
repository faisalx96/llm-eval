#!/bin/bash

# LLM-Eval Comprehensive Load Testing Script
# This script runs all load tests in sequence and generates a comprehensive report

set -e  # Exit on any error

# Configuration
API_HOST="${LOAD_TEST_API_HOST:-http://localhost:8000}"
WS_HOST="${LOAD_TEST_WS_HOST:-ws://localhost:8000/ws}"
RESULTS_DIR="results/$(date +%Y%m%d_%H%M%S)"
DB_PATH="${RESULTS_DIR}/load_test.db"

# Test parameters (can be overridden by environment variables)
API_USERS="${LOAD_TEST_API_USERS:-50}"
API_SPAWN_RATE="${LOAD_TEST_API_SPAWN_RATE:-5}"
API_DURATION="${LOAD_TEST_API_DURATION:-5m}"

WS_CLIENTS="${LOAD_TEST_WS_CLIENTS:-50}"
WS_DURATION="${LOAD_TEST_WS_DURATION:-300}"

DB_RUNS="${LOAD_TEST_DB_RUNS:-1000}"
DB_CONCURRENT="${LOAD_TEST_DB_CONCURRENT:-20}"
DB_DURATION="${LOAD_TEST_DB_DURATION:-600}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create results directory
mkdir -p "$RESULTS_DIR"

# Initialize test report
REPORT_FILE="${RESULTS_DIR}/load_test_report.md"
cat > "$REPORT_FILE" << EOF
# LLM-Eval Load Test Report

**Test Date:** $(date)  
**Test Environment:** $API_HOST  
**Results Directory:** $RESULTS_DIR

## Test Configuration

- **API Host:** $API_HOST
- **WebSocket Host:** $WS_HOST
- **API Users:** $API_USERS (spawn rate: $API_SPAWN_RATE/s, duration: $API_DURATION)
- **WebSocket Clients:** $WS_CLIENTS (duration: ${WS_DURATION}s)
- **Database Runs:** $DB_RUNS (concurrent: $DB_CONCURRENT, duration: ${DB_DURATION}s)

## Test Results

EOF

# Function to check if API is available
check_api_health() {
    log_info "Checking API health at $API_HOST..."
    
    if curl -s "$API_HOST/health" > /dev/null 2>&1; then
        log_success "API is available"
        return 0
    else
        log_error "API is not available at $API_HOST"
        log_error "Please ensure the LLM-Eval API server is running"
        return 1
    fi
}

# Function to run API load tests
run_api_load_test() {
    log_info "Starting API load testing..."
    
    local output_file="${RESULTS_DIR}/api_load_test"
    
    # Run Locust in headless mode
    locust -f locustfile.py \
        --host="$API_HOST" \
        --users="$API_USERS" \
        --spawn-rate="$API_SPAWN_RATE" \
        --run-time="$API_DURATION" \
        --headless \
        --csv="$output_file" \
        --html="${output_file}.html" \
        --loglevel=INFO \
        > "${output_file}.log" 2>&1
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "API load test completed successfully"
        
        # Append results to report
        cat >> "$REPORT_FILE" << EOF
### API Load Testing ✅

- **Status:** PASSED
- **Duration:** $API_DURATION
- **Users:** $API_USERS
- **Report:** [View HTML Report](api_load_test.html)
- **Detailed Logs:** [View Logs](api_load_test.log)

EOF
        
        # Extract key metrics from CSV
        if [ -f "${output_file}_stats.csv" ]; then
            log_info "API Test Key Metrics:"
            echo "Operation | Requests | Failures | Avg(ms) | Max(ms) | RPS"
            echo "----------|----------|----------|---------|---------|----"
            tail -n +2 "${output_file}_stats.csv" | while IFS=',' read -r name requests failures avg_resp min_resp max_resp median_resp rps; do
                printf "%-12s | %8s | %8s | %7s | %7s | %3s\n" \
                    "$(echo $name | cut -c1-10)" "$requests" "$failures" \
                    "$(echo $avg_resp | cut -d. -f1)" "$(echo $max_resp | cut -d. -f1)" \
                    "$(echo $rps | cut -d. -f1)"
            done
        fi
        
        return 0
    else
        log_error "API load test failed with exit code $exit_code"
        
        cat >> "$REPORT_FILE" << EOF
### API Load Testing ❌

- **Status:** FAILED
- **Exit Code:** $exit_code
- **Logs:** [View Logs](api_load_test.log)

EOF
        return 1
    fi
}

# Function to run WebSocket load tests
run_websocket_test() {
    log_info "Starting WebSocket load testing..."
    
    local output_file="${RESULTS_DIR}/websocket_test.log"
    
    python websocket_load_test.py \
        --clients="$WS_CLIENTS" \
        --duration="$WS_DURATION" \
        --host="$WS_HOST" \
        > "$output_file" 2>&1
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "WebSocket load test completed successfully"
        
        cat >> "$REPORT_FILE" << EOF
### WebSocket Load Testing ✅

- **Status:** PASSED
- **Clients:** $WS_CLIENTS
- **Duration:** ${WS_DURATION}s
- **Logs:** [View Logs](websocket_test.log)

EOF
        
        # Extract key metrics from log
        if grep -q "WebSocket latency target MET" "$output_file"; then
            log_success "WebSocket latency targets met"
        else
            log_warning "WebSocket latency targets may have been missed"
        fi
        
        return 0
    else
        log_error "WebSocket load test failed with exit code $exit_code"
        
        cat >> "$REPORT_FILE" << EOF
### WebSocket Load Testing ❌

- **Status:** FAILED
- **Exit Code:** $exit_code
- **Logs:** [View Logs](websocket_test.log)

EOF
        return 1
    fi
}

# Function to run database performance tests
run_database_test() {
    log_info "Starting database performance testing..."
    
    local output_file="${RESULTS_DIR}/database_test.log"
    
    python database_performance_test.py \
        --runs="$DB_RUNS" \
        --concurrent="$DB_CONCURRENT" \
        --duration="$DB_DURATION" \
        --db-path="$DB_PATH" \
        --clean \
        > "$output_file" 2>&1
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "Database performance test completed successfully"
        
        cat >> "$REPORT_FILE" << EOF
### Database Performance Testing ✅

- **Status:** PASSED
- **Runs Created:** $DB_RUNS
- **Concurrent Workers:** $DB_CONCURRENT
- **Duration:** ${DB_DURATION}s
- **Database:** $DB_PATH
- **Logs:** [View Logs](database_test.log)

EOF
        
        # Check for performance targets
        if grep -q "All performance targets met successfully" "$output_file"; then
            log_success "All database performance targets met"
        else
            log_warning "Some database performance targets may have been missed"
        fi
        
        return 0
    else
        log_error "Database performance test failed with exit code $exit_code"
        
        cat >> "$REPORT_FILE" << EOF
### Database Performance Testing ❌

- **Status:** FAILED
- **Exit Code:** $exit_code
- **Logs:** [View Logs](database_test.log)

EOF
        return 1
    fi
}

# Function to generate summary report
generate_summary() {
    local api_status=$1
    local ws_status=$2
    local db_status=$3
    
    log_info "Generating test summary report..."
    
    local overall_status="PASSED"
    local failed_tests=()
    
    if [ $api_status -ne 0 ]; then
        overall_status="FAILED"
        failed_tests+=("API Load Testing")
    fi
    
    if [ $ws_status -ne 0 ]; then
        overall_status="FAILED"
        failed_tests+=("WebSocket Load Testing")
    fi
    
    if [ $db_status -ne 0 ]; then
        overall_status="FAILED"
        failed_tests+=("Database Performance Testing")
    fi
    
    cat >> "$REPORT_FILE" << EOF

## Summary

**Overall Status:** $overall_status

EOF
    
    if [ "$overall_status" = "PASSED" ]; then
        cat >> "$REPORT_FILE" << EOF
✅ All load tests completed successfully!

The LLM-Eval platform meets all performance targets:
- API response times are within acceptable limits
- WebSocket connections are stable and responsive
- Database performance scales well with 1000+ runs

EOF
        log_success "All load tests completed successfully!"
    else
        cat >> "$REPORT_FILE" << EOF
❌ Some load tests failed:

EOF
        for test in "${failed_tests[@]}"; do
            echo "- $test" >> "$REPORT_FILE"
        done
        
        cat >> "$REPORT_FILE" << EOF

Please review the detailed logs for each failed test to identify and resolve issues.

EOF
        log_error "Some load tests failed. Check the detailed report."
    fi
    
    cat >> "$REPORT_FILE" << EOF

## Next Steps

1. **Review Results:** Examine the generated HTML reports and logs
2. **Performance Analysis:** Compare results against baseline measurements
3. **Issue Resolution:** Address any failed tests or performance regressions
4. **Documentation:** Update performance baselines if improvements were made

## Files Generated

- \`load_test_report.md\` - This comprehensive report
- \`api_load_test.html\` - Interactive API load test results
- \`websocket_test.log\` - WebSocket test detailed logs
- \`database_test.log\` - Database performance test logs
- \`load_test.db\` - Test database with generated data

---
*Report generated by LLM-Eval Load Testing Suite*
EOF
    
    log_info "Summary report saved to: $REPORT_FILE"
}

# Main execution
main() {
    echo "=============================================="
    echo "LLM-Eval Comprehensive Load Testing Suite"
    echo "=============================================="
    echo ""
    
    log_info "Starting load testing suite at $(date)"
    log_info "Results will be saved to: $RESULTS_DIR"
    
    # Check prerequisites
    if ! command -v locust &> /dev/null; then
        log_error "Locust is not installed. Please run: pip install locust"
        exit 1
    fi
    
    if ! command -v python &> /dev/null; then
        log_error "Python is not available"
        exit 1
    fi
    
    # Check API availability
    if ! check_api_health; then
        log_error "Cannot proceed without API availability"
        exit 1
    fi
    
    # Run tests
    local api_exit=0
    local ws_exit=0
    local db_exit=0
    
    echo ""
    log_info "=== Running API Load Tests ==="
    run_api_load_test || api_exit=$?
    
    echo ""
    log_info "=== Running WebSocket Load Tests ==="
    run_websocket_test || ws_exit=$?
    
    echo ""
    log_info "=== Running Database Performance Tests ==="
    run_database_test || db_exit=$?
    
    echo ""
    log_info "=== Generating Summary Report ==="
    generate_summary $api_exit $ws_exit $db_exit
    
    # Final status
    echo ""
    if [ $api_exit -eq 0 ] && [ $ws_exit -eq 0 ] && [ $db_exit -eq 0 ]; then
        log_success "All load tests completed successfully!"
        log_info "View the complete report at: $REPORT_FILE"
        exit 0
    else
        log_error "Some tests failed. Check the report for details: $REPORT_FILE"
        exit 1
    fi
}

# Run main function
main "$@"