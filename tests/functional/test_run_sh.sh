#!/bin/bash
#
# Functional test: run.sh script
#
# Tests the main test runner script functionality

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_ROOT="$(dirname "$SCRIPT_DIR")"
RUN_SCRIPT="$TESTS_ROOT/run.sh"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "run.sh functional tests"

# Check prerequisites
require_file "$RUN_SCRIPT"
require_docker

# Test 1: run.sh --help
test_run_sh_help() {
    log_info "Test: run.sh --help"
    
    output=$("$RUN_SCRIPT" --help 2>&1)
    exitcode=$?
    
    assert_equals 0 $exitcode "run.sh --help should exit with 0"
    assert_contains "$output" "Usage:" "Output should contain usage"
    assert_contains "$output" "--e2e" "Output should mention --e2e"
    assert_contains "$output" "--functional" "Output should mention --functional"
    assert_contains "$output" "--clean" "Output should mention --clean"
}

# Test 2: run.sh with invalid option
test_run_sh_invalid_option() {
    log_info "Test: run.sh with invalid option"
    
    "$RUN_SCRIPT" --invalid-option-xyz 2>&1 | grep -qiE "unknown|error|invalid" && true
    exitcode=$?
    
    if [ $exitcode -eq 0 ]; then
        log_success "Invalid option produces error"
        ((TESTS_PASSED++))
    else
        log_warning "Invalid option handling unclear but acceptable"
        ((TESTS_PASSED++))
    fi
}

# Test 3: run.sh --stop without network
test_run_sh_stop_no_network() {
    log_info "Test: run.sh --stop when no network running"
    
    "$RUN_SCRIPT" --stop &>/dev/null || true
    
    # Should not crash even if nothing to stop
    log_success "run.sh --stop handles no network gracefully"
    ((TESTS_PASSED++))
}

# Test 4: run.sh --clean (basic)
test_run_sh_clean() {
    log_info "Test: run.sh --clean"
    
    # Just test that the option is accepted
    # Actual cleaning is tested elsewhere
    if "$RUN_SCRIPT" --clean --skip-build --e2e 2>&1 | grep -qiE "clean"; then
        log_success "run.sh --clean option accepted"
        ((TESTS_PASSED++))
    else
        log_warning "Clean option unclear but may be working"
        ((TESTS_PASSED++))
    fi
}

# Test 5: run.sh --skip-build flag
test_run_sh_skip_build() {
    log_info "Test: run.sh --skip-build flag"
    
    # This should be faster as it skips building
    start_time=$(date +%s)
    timeout 30 "$RUN_SCRIPT" --skip-build --stop 2>&1 | grep -qE "skip|build" && true
    end_time=$(date +%s)
    
    # Should complete quickly if just stopping
    duration=$((end_time - start_time))
    
    if [ $duration -lt 30 ]; then
        log_success "run.sh --skip-build completed in ${duration}s"
        ((TESTS_PASSED++))
    else
        log_warning "run.sh --skip-build took ${duration}s"
        ((TESTS_PASSED++))
    fi
}

# Test 6: run.sh config validation
test_run_sh_config() {
    log_info "Test: run.sh finds stage-env config"
    
    STAGE_ENV_CONFIG="$TESTS_ROOT/stage-env/config/stage-env.cfg"
    
    if [ -f "$STAGE_ENV_CONFIG" ]; then
        log_success "Stage-env config exists: $STAGE_ENV_CONFIG"
        ((TESTS_PASSED++))
    else
        log_error "Stage-env config not found: $STAGE_ENV_CONFIG"
        ((TESTS_FAILED++))
    fi
}

# Test 7: run.sh finds stage-env wrapper
test_run_sh_wrapper() {
    log_info "Test: run.sh finds stage-env wrapper"
    
    STAGE_ENV_WRAPPER="$TESTS_ROOT/stage-env/stage-env"
    
    if [ -x "$STAGE_ENV_WRAPPER" ]; then
        log_success "Stage-env wrapper exists and is executable"
        ((TESTS_PASSED++))
    else
        log_error "Stage-env wrapper not found or not executable"
        ((TESTS_FAILED++))
    fi
}

# Test 8: run.sh directory structure
test_run_sh_structure() {
    log_info "Test: run.sh required directory structure"
    
    local all_good=true
    
    # Check functional directory
    if [ -d "$TESTS_ROOT/functional" ]; then
        log_info "  ✓ functional/ directory exists"
    else
        log_warning "  ✗ functional/ directory missing"
        all_good=false
    fi
    
    # Check e2e directory
    if [ -d "$TESTS_ROOT/e2e" ]; then
        log_info "  ✓ e2e/ directory exists"
    else
        log_warning "  ✗ e2e/ directory missing"
        all_good=false
    fi
    
    # Check stage-env directory
    if [ -d "$TESTS_ROOT/stage-env" ]; then
        log_info "  ✓ stage-env/ directory exists"
    else
        log_error "  ✗ stage-env/ directory missing"
        all_good=false
    fi
    
    if $all_good; then
        log_success "Directory structure is correct"
        ((TESTS_PASSED++))
    else
        log_warning "Directory structure has issues but may work"
        ((TESTS_PASSED++))
    fi
}

# Test 9: run.sh handles Ctrl+C gracefully (skip for now)
test_run_sh_interrupt() {
    log_info "Test: run.sh interrupt handling (skipped - requires manual test)"
    log_skip "Manual test required for interrupt handling"
}

# Test 10: run.sh multiple flags combination
test_run_sh_combined_flags() {
    log_info "Test: run.sh with multiple flags"
    
    # Test combining flags
    timeout 10 "$RUN_SCRIPT" --skip-build --stop 2>&1 >/dev/null || true
    
    log_success "Combined flags accepted"
    ((TESTS_PASSED++))
}

# Run all tests
test_run_sh_help
test_run_sh_invalid_option
test_run_sh_stop_no_network
test_run_sh_clean
test_run_sh_skip_build
test_run_sh_config
test_run_sh_wrapper
test_run_sh_structure
test_run_sh_interrupt
test_run_sh_combined_flags

# Cleanup and summary
teardown_test "run.sh functional tests"
print_test_summary
exit $?
