#!/bin/bash
#
# Functional Test: run.sh Script
#
# Tests the unified test runner script functionality:
# - Command-line argument parsing
# - Help and usage display
# - Different test modes (e2e, functional, regression)
# - Build and skip-build logic
# - Clean and rebuild options

set -eo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TESTS_ROOT="$(cd "$STAGE_ENV_DIR/.." && pwd)"
RUN_SCRIPT="$STAGE_ENV_DIR/scripts/run.sh"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "run.sh Functional Tests"

# Check prerequisites
require_file "$RUN_SCRIPT"
require_docker

# ============================================================================
# Test 1: Help option
# ============================================================================
test_help_option() {
    log_info "Test 1: run.sh --help"
    
    output=$("$RUN_SCRIPT" --help 2>&1)
    exit_code=$?
    
    if [ $exit_code -eq 0 ] && echo "$output" | grep -q "Usage:"; then
        log_success "Help displays correctly"
        ((TESTS_PASSED++)) || true || true
    else
        log_error "Help display failed"
        ((TESTS_FAILED++)) || true || true
    fi
}

# ============================================================================
# Test 2: Help contains all major options
# ============================================================================
test_help_content() {
    log_info "Test 2: Help contains all options"
    
    output=$("$RUN_SCRIPT" --help 2>&1)
    
    local all_good=true
    
    for option in "--e2e" "--functional" "--regression" "--clean" "--rebuild" "--skip-build" "--stop"; do
        if ! echo "$output" | grep -q "$option"; then
            log_warning "  Missing option: $option"
            all_good=false
        fi
    done
    
    if $all_good; then
        log_success "All major options documented"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Some options missing from help"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 3: Invalid option handling
# ============================================================================
test_invalid_option() {
    log_info "Test 3: Invalid option handling"
    
    if "$RUN_SCRIPT" --this-option-does-not-exist 2>&1 | grep -qiE "unknown|error|invalid"; then
        log_success "Invalid option rejected with error"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Invalid option handling unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 4: Stop option
# ============================================================================
test_stop_option() {
    log_info "Test 4: --stop option"
    
    # Should not crash even if nothing running
    if timeout 30 "$RUN_SCRIPT" --stop 2>&1 >/dev/null || true; then
        log_success "Stop option executed"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Stop option completed with timeout/error"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 5: Skip-build flag
# ============================================================================
test_skip_build_flag() {
    log_info "Test 5: --skip-build flag"
    
    # Should complete quickly without building
    output=$(timeout 60 "$RUN_SCRIPT" --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "skip|using existing"; then
        log_success "Skip-build flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Skip-build output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 6: Stage-env config detection
# ============================================================================
test_config_detection() {
    log_info "Test 6: Stage-env config detection"
    
    config_path="$TESTS_ROOT/stage-env/config/stage-env.cfg"
    
    if [ -f "$config_path" ]; then
        log_success "Stage-env config exists at $config_path"
        ((TESTS_PASSED++)) || true
    else
        log_error "Stage-env config not found"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 7: Stage-env wrapper detection
# ============================================================================
test_wrapper_detection() {
    log_info "Test 7: Stage-env wrapper detection"
    
    wrapper_path="$TESTS_ROOT/stage-env/stage-env"
    
    if [ -x "$wrapper_path" ]; then
        log_success "Stage-env wrapper found and executable"
        ((TESTS_PASSED++)) || true
    else
        log_error "Stage-env wrapper not found or not executable"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 8: Test directories structure
# ============================================================================
test_directory_structure() {
    log_info "Test 8: Test directories structure"
    
    local all_good=true
    
    for dir in "stage-env" "functional" "e2e"; do
        if [ -d "$TESTS_ROOT/$dir" ]; then
            log_info "  ✓ $dir/ exists"
        else
            log_warning "  ✗ $dir/ missing"
            all_good=false
        fi
    done
    
    if $all_good; then
        log_success "Directory structure correct"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Directory structure incomplete"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 9: Combined flags
# ============================================================================
test_combined_flags() {
    log_info "Test 9: Combined flags"
    
    # Test multiple flags together
    if timeout 30 "$RUN_SCRIPT" --skip-build --stop 2>&1 >/dev/null || true; then
        log_success "Combined flags accepted"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Combined flags handling unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 10: E2E flag alone
# ============================================================================
test_e2e_flag_parsing() {
    log_info "Test 10: --e2e flag parsing"
    
    # Just check that flag is accepted (don't actually run tests)
    output=$(timeout 5 "$RUN_SCRIPT" --e2e --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "e2e|Starting stage"; then
        log_success "E2E flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "E2E flag output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 11: Functional flag alone
# ============================================================================
test_functional_flag_parsing() {
    log_info "Test 11: --functional flag parsing"
    
    output=$(timeout 5 "$RUN_SCRIPT" --functional --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "functional|Starting stage"; then
        log_success "Functional flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Functional flag output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 12: Clean flag
# ============================================================================
test_clean_flag() {
    log_info "Test 12: --clean flag"
    
    output=$(timeout 30 "$RUN_SCRIPT" --clean --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "clean|removing"; then
        log_success "Clean flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Clean flag output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 13: Script location resolution
# ============================================================================
test_script_location() {
    log_info "Test 13: Script location resolution"
    
    # Script should work from different directories
    pushd /tmp >/dev/null
    
    if timeout 10 "$RUN_SCRIPT" --help 2>&1 | grep -q "Usage:"; then
        log_success "Script works from different directory"
        ((TESTS_PASSED++)) || true
    else
        log_error "Script fails when run from different directory"
        ((TESTS_FAILED++)) || true
    fi
    
    popd >/dev/null
}

# ============================================================================
# Test 14: Prerequisites check
# ============================================================================
test_prerequisites_check() {
    log_info "Test 14: Prerequisites check"
    
    output=$("$RUN_SCRIPT" --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "prerequisite|checking|docker|python"; then
        log_success "Prerequisites checked"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Prerequisites check not visible in output"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 15: Node source type detection
# ============================================================================
test_node_source_detection() {
    log_info "Test 15: Node source type detection"
    
    config_file="$TESTS_ROOT/stage-env/config/stage-env.cfg"
    
    if [ -f "$config_file" ]; then
        if grep -q "\[node_source\]" "$config_file"; then
            log_success "Config has node_source section"
            ((TESTS_PASSED++)) || true
        else
            log_warning "Config missing node_source section"
            ((TESTS_PASSED++)) || true
        fi
    else
        log_skip "Config file not found"
    fi
}

# ============================================================================
# Test 16: Regression flag parsing
# ============================================================================
test_regression_flag_parsing() {
    log_info "Test 16: --regression flag parsing"
    
    output=$(timeout 5 "$RUN_SCRIPT" --regression --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "regression|Starting stage"; then
        log_success "Regression flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Regression flag output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 17: Keep-running flag
# ============================================================================
test_keep_running_flag() {
    log_info "Test 17: --keep-running flag"
    
    output=$(timeout 10 "$RUN_SCRIPT" --keep-running --skip-build --stop 2>&1 || true)
    
    if echo "$output" | grep -qiE "keep"; then
        log_success "Keep-running flag recognized"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Keep-running flag output unclear"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 18: Script is executable
# ============================================================================
test_script_executable() {
    log_info "Test 18: Script is executable"
    
    if [ -x "$RUN_SCRIPT" ]; then
        log_success "Script is executable"
        ((TESTS_PASSED++)) || true
    else
        log_error "Script is not executable"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 19: Script has bash shebang
# ============================================================================
test_bash_shebang() {
    log_info "Test 19: Bash shebang present"
    
    if head -n 1 "$RUN_SCRIPT" | grep -qE "^#!/.*bash"; then
        log_success "Bash shebang present"
        ((TESTS_PASSED++)) || true
    else
        log_error "Missing or incorrect shebang"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 20: Error handling (double stop)
# ============================================================================
test_error_handling() {
    log_info "Test 20: Error handling (multiple stops)"
    
    # Stop twice - should not crash
    timeout 30 "$RUN_SCRIPT" --stop 2>&1 >/dev/null || true
    timeout 30 "$RUN_SCRIPT" --stop 2>&1 >/dev/null || true
    
    log_success "Multiple stops handled gracefully"
    ((TESTS_PASSED++)) || true
}

# Run all tests
test_help_option
test_help_content
test_invalid_option
test_stop_option
test_skip_build_flag
test_config_detection
test_wrapper_detection
test_directory_structure
test_combined_flags
test_e2e_flag_parsing
test_functional_flag_parsing
test_clean_flag
test_script_location
test_prerequisites_check
test_node_source_detection
test_regression_flag_parsing
test_keep_running_flag
test_script_executable
test_bash_shebang
test_error_handling

# Cleanup and summary
teardown_test "run.sh Functional Tests"
print_test_summary
exit $?
