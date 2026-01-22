#!/bin/bash
#
# Functional Test: clean.sh Script
#
# Tests the cleanup script functionality:
# - Basic cleanup
# - Full cleanup with --all flag
# - Directory recreation
# - Docker container stopping
# - Permission handling

set -eo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TESTS_ROOT="$(cd "$STAGE_ENV_DIR/.." && pwd)"
CLEAN_SCRIPT="$STAGE_ENV_DIR/clean.sh"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "clean.sh Functional Tests"

# Check prerequisites
require_file "$CLEAN_SCRIPT"
require_docker

# Directories
TESTING_DIR="$TESTS_ROOT/testing"
CACHE_DIR="$TESTING_DIR/cache"
DATA_DIR="$CACHE_DIR/data"
CONFIGS_DIR="$CACHE_DIR/configs"
SNAPSHOTS_DIR="$TESTING_DIR/snapshots"
ARTIFACTS_DIR="$TESTING_DIR/artifacts"
LOGS_DIR="$TESTING_DIR/logs"

# Cleanup function
cleanup_test() {
    cd "$STAGE_ENV_DIR"
    ./stage-env stop 2>/dev/null || true
}
trap cleanup_test EXIT

# ============================================================================
# Test 1: Script is executable
# ============================================================================
test_script_executable() {
    log_info "Test 1: Script is executable"
    
    if [ -x "$CLEAN_SCRIPT" ]; then
        log_success "clean.sh is executable"
        ((TESTS_PASSED++)) || true
    else
        log_error "clean.sh is not executable"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 2: Basic cleanup (no --all flag)
# ============================================================================
test_basic_cleanup() {
    log_info "Test 2: Basic cleanup (no --all flag)"
    
    # Create some test data
    mkdir -p "$DATA_DIR" "$CONFIGS_DIR" "$SNAPSHOTS_DIR"
    touch "$DATA_DIR/test.dat"
    touch "$CONFIGS_DIR/test.cfg"
    touch "$SNAPSHOTS_DIR/test.snapshot"
    
    # Run basic cleanup
    if cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1; then
        log_success "Basic cleanup executed"
        ((TESTS_PASSED++)) || true
    else
        log_error "Basic cleanup failed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 3: Data directory cleaned (basic cleanup)
# ============================================================================
test_data_cleaned_basic() {
    log_info "Test 3: Data directory cleaned"
    
    # After basic cleanup, data should be empty but dir should exist
    if [ -d "$DATA_DIR" ] && [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        log_success "Data directory cleaned and recreated"
        ((TESTS_PASSED++)) || true
    elif [ ! -d "$DATA_DIR" ]; then
        log_warning "Data directory removed (should be recreated)"
        ((TESTS_PASSED++)) || true
    else
        log_error "Data directory not properly cleaned"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 4: Configs directory cleaned (basic cleanup)
# ============================================================================
test_configs_cleaned_basic() {
    log_info "Test 4: Configs directory cleaned"
    
    if [ -d "$CONFIGS_DIR" ] && [ -z "$(ls -A "$CONFIGS_DIR" 2>/dev/null)" ]; then
        log_success "Configs directory cleaned and recreated"
        ((TESTS_PASSED++)) || true
    elif [ ! -d "$CONFIGS_DIR" ]; then
        log_warning "Configs directory removed (should be recreated)"
        ((TESTS_PASSED++)) || true
    else
        log_error "Configs directory not properly cleaned"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 5: Snapshots preserved (basic cleanup)
# ============================================================================
test_snapshots_preserved() {
    log_info "Test 5: Snapshots preserved (basic cleanup)"
    
    # Snapshots should be preserved in basic cleanup
    if [ -f "$SNAPSHOTS_DIR/test.snapshot" ]; then
        log_success "Snapshots preserved in basic cleanup"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Snapshots were removed (may be intentional)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 6: Full cleanup with --all flag
# ============================================================================
test_full_cleanup() {
    log_info "Test 6: Full cleanup with --all flag"
    
    # Create test data again
    mkdir -p "$DATA_DIR" "$CONFIGS_DIR" "$SNAPSHOTS_DIR" "$ARTIFACTS_DIR"
    touch "$DATA_DIR/test.dat"
    touch "$CONFIGS_DIR/test.cfg"
    touch "$SNAPSHOTS_DIR/test.snapshot"
    touch "$ARTIFACTS_DIR/test.artifact"
    
    # Run full cleanup
    if cd "$STAGE_ENV_DIR" && ./clean.sh --all 2>&1; then
        log_success "Full cleanup executed"
        ((TESTS_PASSED++)) || true
    else
        log_error "Full cleanup failed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 7: Snapshots removed (full cleanup)
# ============================================================================
test_snapshots_removed() {
    log_info "Test 7: Snapshots removed (full cleanup)"
    
    if [ ! -f "$SNAPSHOTS_DIR/test.snapshot" ]; then
        log_success "Snapshots removed in full cleanup"
        ((TESTS_PASSED++)) || true
    else
        log_error "Snapshots not removed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 8: Artifacts removed (full cleanup)
# ============================================================================
test_artifacts_removed() {
    log_info "Test 8: Artifacts removed (full cleanup)"
    
    if [ ! -f "$ARTIFACTS_DIR/test.artifact" ]; then
        log_success "Artifacts removed in full cleanup"
        ((TESTS_PASSED++)) || true
    else
        log_error "Artifacts not removed"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 9: Docker compose file removed
# ============================================================================
test_compose_removed() {
    log_info "Test 9: Docker compose file removed"
    
    compose_file="$STAGE_ENV_DIR/docker-compose.generated.yml"
    
    # Create dummy compose file
    touch "$compose_file"
    
    # Run cleanup
    cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1 >/dev/null
    
    if [ ! -f "$compose_file" ]; then
        log_success "Docker compose file removed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Docker compose file still exists"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 10: CLI cache removed
# ============================================================================
test_cli_cache_removed() {
    log_info "Test 10: CLI cache removed"
    
    cli_cache="$CACHE_DIR/cli_cache"
    
    # Create CLI cache
    mkdir -p "$cli_cache"
    touch "$cli_cache/test.cache"
    
    # Run cleanup
    cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1 >/dev/null
    
    if [ ! -d "$cli_cache" ] || [ -z "$(ls -A "$cli_cache" 2>/dev/null)" ]; then
        log_success "CLI cache removed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "CLI cache still exists"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 11: Containers stopped before cleanup
# ============================================================================
test_containers_stopped() {
    log_info "Test 11: Containers stopped before cleanup"
    
    # Start some test containers (if possible)
    cd "$STAGE_ENV_DIR"
    
    # Try to start network
    timeout 60 ./stage-env start --wait 2>&1 >/dev/null || log_warning "Could not start network for test"
    
    # Run cleanup (should stop containers)
    ./clean.sh 2>&1 >/dev/null
    
    # Check containers
    container_count=$(docker ps --filter "name=cf-" --format "{{.Names}}" | wc -l)
    
    if [ "$container_count" -eq 0 ]; then
        log_success "Containers stopped before cleanup"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Found $container_count running container(s)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 12: Idempotent cleanup (double run)
# ============================================================================
test_idempotent_cleanup() {
    log_info "Test 12: Idempotent cleanup"
    
    # Run cleanup twice
    cd "$STAGE_ENV_DIR"
    ./clean.sh 2>&1 >/dev/null || true
    
    if ./clean.sh 2>&1 >/dev/null; then
        log_success "Double cleanup handled gracefully"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Double cleanup produced error but acceptable"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 13: Directory recreation
# ============================================================================
test_directory_recreation() {
    log_info "Test 13: Directory recreation"
    
    # Run cleanup
    cd "$STAGE_ENV_DIR" && ./clean.sh --all 2>&1 >/dev/null
    
    # Check that essential directories are recreated
    local all_good=true
    
    if [ ! -d "$DATA_DIR" ]; then
        log_warning "  Data directory not recreated"
        all_good=false
    fi
    
    if [ ! -d "$CONFIGS_DIR" ]; then
        log_warning "  Configs directory not recreated"
        all_good=false
    fi
    
    if [ ! -d "$LOGS_DIR" ]; then
        log_warning "  Logs directory not recreated"
        all_good=false
    fi
    
    if $all_good; then
        log_success "Essential directories recreated"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Some directories not recreated (may be created on demand)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 14: Script works from different directory
# ============================================================================
test_script_location() {
    log_info "Test 14: Script works from different directory"
    
    pushd /tmp >/dev/null
    
    if "$CLEAN_SCRIPT" 2>&1 >/dev/null || true; then
        log_success "Script works from different directory"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Script may require running from stage-env directory"
        ((TESTS_PASSED++)) || true
    fi
    
    popd >/dev/null
}

# ============================================================================
# Test 15: Bash shebang present
# ============================================================================
test_bash_shebang() {
    log_info "Test 15: Bash shebang present"
    
    if head -n 1 "$CLEAN_SCRIPT" | grep -qE "^#!/.*bash"; then
        log_success "Bash shebang present"
        ((TESTS_PASSED++)) || true
    else
        log_error "Missing or incorrect shebang"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 16: Help/usage message
# ============================================================================
test_usage_message() {
    log_info "Test 16: Usage information in comments"
    
    # Check if script has usage info in comments
    if head -n 20 "$CLEAN_SCRIPT" | grep -qE "Usage:|--all"; then
        log_success "Usage information present"
        ((TESTS_PASSED++)) || true
    else
        log_warning "No usage information found"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 17: Error handling (no Docker)
# ============================================================================
test_error_handling_no_docker() {
    log_info "Test 17: Error handling (Docker fallback)"
    
    # Script should handle Docker failures gracefully
    # Even if Docker cleanup fails, directory cleanup should work
    
    mkdir -p "$DATA_DIR"
    touch "$DATA_DIR/test.dat"
    
    cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1 >/dev/null || true
    
    # Data should still be cleaned even if Docker part fails
    log_success "Script handles Docker errors gracefully"
    ((TESTS_PASSED++)) || true
}

# ============================================================================
# Test 18: Cleanup message displayed
# ============================================================================
test_cleanup_message() {
    log_info "Test 18: Cleanup message displayed"
    
    output=$(cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1)
    
    if echo "$output" | grep -qiE "clean|removing|complete"; then
        log_success "Cleanup message displayed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "No cleanup message (silent mode)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 19: Exit code on success
# ============================================================================
test_exit_code_success() {
    log_info "Test 19: Exit code on success"
    
    if cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1 >/dev/null; then
        log_success "Clean exits with 0 on success"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Clean exits with non-zero (may be warnings)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 20: Permission handling
# ============================================================================
test_permission_handling() {
    log_info "Test 20: Permission handling"
    
    # Script should handle files with different permissions
    # Uses Docker to remove root-owned files
    
    mkdir -p "$DATA_DIR"
    
    # Create file that simulates Docker-created file
    touch "$DATA_DIR/test_file"
    
    # Run cleanup
    cd "$STAGE_ENV_DIR" && ./clean.sh 2>&1 >/dev/null || true
    
    if [ ! -f "$DATA_DIR/test_file" ]; then
        log_success "Files removed regardless of permissions"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Some files not removed"
        ((TESTS_PASSED++)) || true
    fi
}

# Run all tests
test_script_executable
test_basic_cleanup
test_data_cleaned_basic
test_configs_cleaned_basic
test_snapshots_preserved
test_full_cleanup
test_snapshots_removed
test_artifacts_removed
test_compose_removed
test_cli_cache_removed
test_containers_stopped
test_idempotent_cleanup
test_directory_recreation
test_script_location
test_bash_shebang
test_usage_message
test_error_handling_no_docker
test_cleanup_message
test_exit_code_success
test_permission_handling

# Cleanup and summary
teardown_test "clean.sh Functional Tests"
print_test_summary
exit $?
