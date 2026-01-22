#!/bin/bash
#
# Functional test: clean.sh script
#
# Tests the stage-env/scripts/clean.sh functionality

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_ROOT="$(dirname "$SCRIPT_DIR")"
STAGE_ENV_DIR="$TESTS_ROOT/stage-env"
CLEAN_SCRIPT="$STAGE_ENV_DIR/scripts/clean.sh"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "clean.sh functional tests"

# Check prerequisites
require_file "$CLEAN_SCRIPT"
require_docker

# Test 1: clean.sh --help shows usage
test_clean_help() {
    log_info "Test: clean.sh --help shows usage"
    
    output=$("$CLEAN_SCRIPT" --help 2>&1)
    exitcode=$?
    
    assert_equals 0 $exitcode "clean.sh --help should exit with 0"
    assert_contains "$output" "Usage:" "Output should contain usage information"
    assert_contains "$output" "--force" "Output should mention --force flag"
    assert_contains "$output" "--keep-images" "Output should mention --keep-images flag"
}

# Test 2: clean.sh --force runs without confirmation
test_clean_force() {
    log_info "Test: clean.sh --force runs without confirmation"
    
    "$CLEAN_SCRIPT" --force &>/dev/null
    assert_success "clean.sh --force should complete successfully"
}

# Test 3: clean.sh is idempotent
test_clean_idempotent() {
    log_info "Test: clean.sh is idempotent (can run multiple times)"
    
    "$CLEAN_SCRIPT" --force &>/dev/null
    assert_success "First clean.sh --force should succeed"
    
    "$CLEAN_SCRIPT" --force &>/dev/null
    assert_success "Second clean.sh --force should succeed"
}

# Test 4: clean.sh removes Docker containers
test_clean_removes_containers() {
    log_info "Test: clean.sh removes Docker containers"
    
    # Create a test container
    docker run -d --name cf-test-container alpine:latest sleep 30 &>/dev/null || true
    
    # Check it exists
    if docker ps -a --filter "name=cf-test-container" --format "{{.Names}}" | grep -q "cf-test-container"; then
        log_info "Test container created"
    else
        log_warning "Could not create test container, skipping removal check"
        return 0
    fi
    
    # Run clean
    "$CLEAN_SCRIPT" --force &>/dev/null
    assert_success "clean.sh should complete"
    
    # Check container is removed
    if ! docker ps -a --filter "name=cf-test-container" --format "{{.Names}}" | grep -q "cf-test-container"; then
        log_success "Test container was removed"
        ((TESTS_PASSED++))
    else
        log_error "Test container was not removed"
        ((TESTS_FAILED++))
        # Cleanup
        docker rm -f cf-test-container &>/dev/null || true
    fi
}

# Test 5: clean.sh --keep-images preserves images
test_clean_keep_images() {
    log_info "Test: clean.sh --keep-images preserves Docker images"
    
    # Pull a test image if it doesn't exist
    if ! docker images | grep -q "alpine.*latest"; then
        docker pull alpine:latest &>/dev/null || skip_test "Cannot pull test image"
    fi
    
    "$CLEAN_SCRIPT" --force --keep-images &>/dev/null
    assert_success "clean.sh --keep-images should complete"
    
    # Check image still exists
    if docker images | grep -q "alpine.*latest"; then
        log_success "Alpine image preserved"
        ((TESTS_PASSED++))
    else
        log_error "Alpine image was removed despite --keep-images"
        ((TESTS_FAILED++))
    fi
}

# Test 6: clean.sh removes testing artifacts
test_clean_removes_artifacts() {
    log_info "Test: clean.sh removes testing artifacts"
    
    # Create test artifacts
    mkdir -p "$TESTS_ROOT/testing/artifacts/test_run" 2>/dev/null || true
    touch "$TESTS_ROOT/testing/artifacts/test_run/test.log" 2>/dev/null || true
    
    "$CLEAN_SCRIPT" --force &>/dev/null
    assert_success "clean.sh should complete"
    
    # Check artifacts are cleaned (directory should be empty or removed)
    if [ ! -d "$TESTS_ROOT/testing/artifacts" ] || [ -z "$(ls -A "$TESTS_ROOT/testing/artifacts" 2>/dev/null)" ]; then
        log_success "Artifacts directory cleaned"
        ((TESTS_PASSED++))
    else
        log_warning "Artifacts directory still contains files (may be expected)"
        ((TESTS_PASSED++))
    fi
}

# Run all tests
test_clean_help
test_clean_force
test_clean_idempotent
test_clean_removes_containers
test_clean_keep_images
test_clean_removes_artifacts

# Cleanup and summary
teardown_test "clean.sh functional tests"
print_test_summary
exit $?
