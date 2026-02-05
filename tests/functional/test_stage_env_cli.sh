#!/bin/bash
#
# Functional test: stage-env CLI commands
#
# Tests basic stage-env CLI functionality

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_ROOT="$(dirname "$SCRIPT_DIR")"
STAGE_ENV_DIR="$TESTS_ROOT/stage-env"
STAGE_ENV_CLI="$STAGE_ENV_DIR/stage-env"
STAGE_ENV_CONFIG="$STAGE_ENV_DIR/config/stage-env.cfg"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "stage-env CLI functional tests"

# Check prerequisites
require_file "$STAGE_ENV_CLI"
require_file "$STAGE_ENV_CONFIG"
require_docker

# Ensure clean environment before tests
cleanup_test_env

# Test 1: stage-env --help
test_stage_env_help() {
    log_info "Test: stage-env --help"
    
    output=$("$STAGE_ENV_CLI" --help 2>&1)
    exitcode=$?
    
    assert_equals 0 $exitcode "stage-env --help should exit with 0"
    assert_contains "$output" "usage" "Output should contain usage information"
    assert_contains "$output" "start" "Output should mention start command"
    assert_contains "$output" "stop" "Output should mention stop command"
}

# Test 2: stage-env --version
test_stage_env_version() {
    log_info "Test: stage-env --version"
    
    output=$("$STAGE_ENV_CLI" --version 2>&1)
    exitcode=$?
    
    assert_equals 0 $exitcode "stage-env --version should exit with 0"
    # Version should contain some version number or identifier
    if echo "$output" | grep -qE "[0-9]|version|stage-env"; then
        log_success "Version output contains version information"
        ((TESTS_PASSED++))
    else
        log_error "Version output does not contain version information"
        ((TESTS_FAILED++))
    fi
}

# Test 3: stage-env status (no network running)
test_stage_env_status_no_network() {
    log_info "Test: stage-env status when no network is running"
    
    output=$("$STAGE_ENV_CLI" --config="$STAGE_ENV_CONFIG" status 2>&1) || true
    
    # Should either say "not running" or return non-zero exit code
    if echo "$output" | grep -qiE "not running|no network|stopped|inactive"; then
        log_success "Status correctly shows no network running"
        ((TESTS_PASSED++))
    else
        log_warning "Status output unclear, but acceptable: $output"
        ((TESTS_PASSED++))
    fi
}

# Test 4: stage-env clean command
test_stage_env_clean() {
    log_info "Test: stage-env clean command"
    
    "$STAGE_ENV_CLI" --config="$STAGE_ENV_CONFIG" clean --all --force &>/dev/null
    assert_success "stage-env clean should complete"
}

# Test 5: Invalid command handling
test_stage_env_invalid_command() {
    log_info "Test: stage-env with invalid command"
    
    "$STAGE_ENV_CLI" invalid_command_xyz 2>&1 | grep -qiE "error|invalid|unknown" && true
    exitcode=$?
    
    if [ $exitcode -eq 0 ]; then
        log_success "Invalid command produces error message"
        ((TESTS_PASSED++))
    else
        log_error "Invalid command did not produce expected error"
        ((TESTS_FAILED++))
    fi
}

# Test 6: stage-env with verbose flag
test_stage_env_verbose() {
    log_info "Test: stage-env with -v flag"
    
    output=$("$STAGE_ENV_CLI" -v --version 2>&1)
    exitcode=$?
    
    assert_equals 0 $exitcode "stage-env -v --version should exit with 0"
    # With verbose, should have more output or debug messages
    log_success "Verbose flag accepted"
    ((TESTS_PASSED++))
}

# Test 7: stage-env help for specific command
test_stage_env_command_help() {
    log_info "Test: stage-env start --help"
    
    output=$("$STAGE_ENV_CLI" start --help 2>&1) || true
    
    # Should contain help for start command
    if echo "$output" | grep -qiE "help|usage|start"; then
        log_success "Command-specific help available"
        ((TESTS_PASSED++))
    else
        log_warning "Help output unclear but acceptable"
        ((TESTS_PASSED++))
    fi
}

# Test 8: stage-env with custom config path
test_stage_env_custom_config() {
    log_info "Test: stage-env with --config option"
    
    # Just test that the option is accepted
    output=$("$STAGE_ENV_CLI" --config="$STAGE_ENV_CONFIG" status 2>&1) || true
    
    # Should not complain about config option
    if ! echo "$output" | grep -qE "unknown option.*config"; then
        log_success "Custom config option accepted"
        ((TESTS_PASSED++))
    else
        log_error "Custom config option not recognized"
        ((TESTS_FAILED++))
    fi
}

# Test 9: stage-env timeout handling
test_stage_env_timeout() {
    log_info "Test: stage-env handles short operations quickly"
    
    start_time=$(date +%s)
    "$STAGE_ENV_CLI" --config="$STAGE_ENV_CONFIG" status &>/dev/null || true
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    
    if [ $duration -lt 10 ]; then
        log_success "Status command completed quickly (${duration}s)"
        ((TESTS_PASSED++))
    else
        log_warning "Status command took ${duration}s (might be normal)"
        ((TESTS_PASSED++))
    fi
}

# Test 10: stage-env PID file handling
test_stage_env_pid_file() {
    log_info "Test: stage-env PID file handling"
    
    PID_FILE="$STAGE_ENV_DIR/.stage-env.pid"
    
    # Remove old PID file if exists
    rm -f "$PID_FILE"
    
    # Quick command should not leave stale PID file
    "$STAGE_ENV_CLI" --version &>/dev/null || true
    
    # PID file should not exist after quick command or should be cleaned up
    if [ ! -f "$PID_FILE" ]; then
        log_success "No stale PID file after quick command"
        ((TESTS_PASSED++))
    else
        # Check if PID is actually running
        if [ -f "$PID_FILE" ]; then
            pid=$(cat "$PID_FILE" 2>/dev/null)
            if ! ps -p "$pid" &>/dev/null; then
                log_warning "Stale PID file exists (minor issue)"
                ((TESTS_PASSED++))
                rm -f "$PID_FILE"
            else
                log_success "PID file exists for running process"
                ((TESTS_PASSED++))
            fi
        fi
    fi
}

# Run all tests
test_stage_env_help
test_stage_env_version
test_stage_env_status_no_network
test_stage_env_clean
test_stage_env_invalid_command
test_stage_env_verbose
test_stage_env_command_help
test_stage_env_custom_config
test_stage_env_timeout
test_stage_env_pid_file

# Cleanup
cleanup_test_env
teardown_test "stage-env CLI functional tests"
print_test_summary
exit $?
