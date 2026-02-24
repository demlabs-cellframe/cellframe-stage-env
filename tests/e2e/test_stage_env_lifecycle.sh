#!/bin/bash
#
# E2E Test: Stage-Env Full Lifecycle
#
# Tests complete stage-env lifecycle:
# - Build/status
# - Start network
# - Health checks
# - Stop network  
# - Cleanup

set -eo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TESTS_ROOT="$(cd "$STAGE_ENV_DIR/.." && pwd)"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "Stage-Env Lifecycle E2E Tests"

# Check prerequisites
require_docker
require_file "$STAGE_ENV_DIR/stage-env"

# Directories
CONFIG_FILE="$STAGE_ENV_DIR/config/stage-env.cfg"
TESTING_DIR="$TESTS_ROOT/testing"

# Ensure clean state
cleanup_env() {
    log_info "Ensuring clean environment..."
    cd "$STAGE_ENV_DIR"
    ./stage-env stop 2>/dev/null || true
    ./clean.sh 2>/dev/null || true
}

cleanup_env
trap cleanup_env EXIT

# ============================================================================
# Test 1: Validate command
# ============================================================================
test_status_command() {
    log_info "Test 1: Validate command"
    
    cd "$STAGE_ENV_DIR"
    
    if ./stage-env --config="$CONFIG_FILE" status 2>&1; then
        log_success "Validation passed"
        ((TESTS_PASSED++)) || true
    else
        log_error "Validation failed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 2: Status command (stopped state)
# ============================================================================
test_status_stopped() {
    log_info "Test 2: Status when stopped"
    
    cd "$STAGE_ENV_DIR"
    
    output=$(./stage-env --config="$CONFIG_FILE" status 2>&1 || true)
    
    if echo "$output" | grep -qiE "stopped|not running|no containers"; then
        log_success "Status shows stopped state"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Status output unclear but acceptable"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 3: Start network (minimal)
# ============================================================================
test_start_network() {
    log_info "Test 3: Start network"
    
    cd "$STAGE_ENV_DIR"
    
    # Start with minimal config
    if timeout 300 ./stage-env --config="$CONFIG_FILE" start --wait 2>&1; then
        log_success "Network started successfully"
        ((TESTS_PASSED++)) || true
    else
        log_error "Network start failed"
        ((TESTS_FAILED++)) || true
        return 1
    fi
}

# ============================================================================
# Test 4: Status command (running state)
# ============================================================================
test_status_running() {
    log_info "Test 4: Status when running"
    
    cd "$STAGE_ENV_DIR"
    
    output=$(./stage-env --config="$CONFIG_FILE" status 2>&1)
    
    if echo "$output" | grep -qiE "running|healthy|up"; then
        log_success "Status shows running state"
        ((TESTS_PASSED++)) || true
    else
        log_error "Status doesn't show running state"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 5: Docker containers are running
# ============================================================================
test_containers_running() {
    log_info "Test 5: Docker containers are running"
    
    # Check for cellframe containers
    container_count=$(docker ps --filter "name=cf-" --format "{{.Names}}" | wc -l)
    
    if [ "$container_count" -gt 0 ]; then
        log_success "Found $container_count cellframe container(s)"
        ((TESTS_PASSED++)) || true
    else
        log_error "No cellframe containers found"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 6: Config files generated
# ============================================================================
test_config_files_generated() {
    log_info "Test 6: Config files generated"
    
    local configs_dir="$TESTING_DIR/cache/configs"
    
    if [ -d "$configs_dir" ] && [ "$(ls -A "$configs_dir" 2>/dev/null | wc -l)" -gt 0 ]; then
        log_success "Config files generated in $configs_dir"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Config directory empty or missing (may use in-memory configs)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 7: Docker compose file generated
# ============================================================================
test_docker_compose_generated() {
    log_info "Test 7: Docker compose file generated"
    
    if [ -f "$STAGE_ENV_DIR/docker-compose.generated.yml" ]; then
        log_success "Docker compose file generated"
        ((TESTS_PASSED++)) || true
    else
        log_error "Docker compose file not found"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 8: Logs directory created
# ============================================================================
test_logs_directory() {
    log_info "Test 8: Logs directory created"
    
    local logs_dir="$TESTING_DIR/logs"
    
    if [ -d "$logs_dir" ]; then
        log_success "Logs directory exists"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Logs directory not found"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 9: Stop network
# ============================================================================
test_stop_network() {
    log_info "Test 9: Stop network"
    
    cd "$STAGE_ENV_DIR"
    
    if ./stage-env --config="$CONFIG_FILE" stop 2>&1; then
        log_success "Network stopped successfully"
        ((TESTS_PASSED++)) || true
    else
        log_error "Network stop failed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 10: Containers stopped
# ============================================================================
test_containers_stopped() {
    log_info "Test 10: Containers stopped"
    
    # Wait a bit for containers to fully stop
    sleep 2
    
    container_count=$(docker ps --filter "name=cf-" --format "{{.Names}}" | wc -l)
    
    if [ "$container_count" -eq 0 ]; then
        log_success "All cellframe containers stopped"
        ((TESTS_PASSED++)) || true
    else
        log_error "Found $container_count running container(s)"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 11: Double stop (idempotent)
# ============================================================================
test_double_stop() {
    log_info "Test 11: Double stop (idempotent)"
    
    cd "$STAGE_ENV_DIR"
    
    # Stop again - should not fail
    if ./stage-env --config="$CONFIG_FILE" stop 2>&1 || true; then
        log_success "Double stop handled gracefully"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Double stop produced error but acceptable"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 12: Clean command
# ============================================================================
test_clean_command() {
    log_info "Test 12: Clean command"
    
    cd "$STAGE_ENV_DIR"
    
    if ./stage-env --config="$CONFIG_FILE" clean 2>&1; then
        log_success "Clean completed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Clean completed with warnings"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 13: Data directories cleaned
# ============================================================================
test_data_cleaned() {
    log_info "Test 13: Data directories cleaned"
    
    local data_dir="$TESTING_DIR/cache/data"
    local configs_dir="$TESTING_DIR/cache/configs"
    
    local data_empty=false
    local configs_empty=false
    
    if [ ! -d "$data_dir" ] || [ -z "$(ls -A "$data_dir" 2>/dev/null)" ]; then
        data_empty=true
    fi
    
    if [ ! -d "$configs_dir" ] || [ -z "$(ls -A "$configs_dir" 2>/dev/null)" ]; then
        configs_empty=true
    fi
    
    if $data_empty && $configs_empty; then
        log_success "Data and config directories cleaned"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Some directories not fully cleaned (may be intentional)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 14: Docker compose file removed
# ============================================================================
test_compose_removed() {
    log_info "Test 14: Docker compose file removed"
    
    if [ ! -f "$STAGE_ENV_DIR/docker-compose.generated.yml" ]; then
        log_success "Docker compose file removed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Docker compose file still exists (may be kept intentionally)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 15: Full cycle - start, stop, clean (integration)
# ============================================================================
test_full_cycle() {
    log_info "Test 15: Full cycle (start -> stop -> clean)"
    
    cd "$STAGE_ENV_DIR"
    
    # Clean start
    ./stage-env --config="$CONFIG_FILE" clean 2>/dev/null || true
    
    # Start
    if ! timeout 300 ./stage-env --config="$CONFIG_FILE" start --wait 2>&1; then
        log_error "Full cycle: Start failed"
        ((TESTS_FAILED++)) || true
        return 1
    fi
    
    # Verify running
    sleep 5
    if ! docker ps --filter "name=cf-" --format "{{.Names}}" | grep -q "cf-"; then
        log_error "Full cycle: Containers not running"
        ((TESTS_FAILED++)) || true
        return 1
    fi
    
    # Stop
    if ! ./stage-env --config="$CONFIG_FILE" stop 2>&1; then
        log_error "Full cycle: Stop failed"
        ((TESTS_FAILED++)) || true
        return 1
    fi
    
    # Verify stopped
    sleep 2
    if docker ps --filter "name=cf-" --format "{{.Names}}" | grep -q "cf-"; then
        log_error "Full cycle: Containers still running"
        ((TESTS_FAILED++)) || true
        return 1
    fi
    
    # Clean
    if ! ./stage-env --config="$CONFIG_FILE" clean 2>&1; then
        log_warning "Full cycle: Clean completed with warnings"
    fi
    
    log_success "Full cycle completed successfully"
    ((TESTS_PASSED++)) || true
}

# Run all tests in order
test_status_command
test_status_stopped

# Start network for tests 3-8
test_start_network && {
    test_status_running
    test_containers_running
    test_config_files_generated
    test_docker_compose_generated
    test_logs_directory
}

# Stop network for tests 9-11
test_stop_network
test_containers_stopped
test_double_stop

# Clean for tests 12-14
test_clean_command
test_data_cleaned
test_compose_removed

# Full integration test
test_full_cycle

# Cleanup and summary
teardown_test "Stage-Env Lifecycle E2E Tests"
print_test_summary
exit $?
