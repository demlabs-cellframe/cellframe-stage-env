#!/bin/bash
#
# Common helper functions for stage-env bash tests
#

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
}

# Assertion functions
assert_success() {
    local exit_code=$?
    local message="${1:-Command failed}"
    
    if [ $exit_code -eq 0 ]; then
        log_success "$message"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message (exit code: $exit_code)"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_failure() {
    local exit_code=$?
    local message="${1:-Command should have failed but succeeded}"
    
    if [ $exit_code -ne 0 ]; then
        log_success "$message"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="${3:-Values not equal}"
    
    if [ "$expected" = "$actual" ]; then
        log_success "$message"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: expected '$expected', got '$actual'"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-String not found}"
    
    if echo "$haystack" | grep -q "$needle"; then
        log_success "$message"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: '$needle' not found in output"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-String should not be found}"
    
    if ! echo "$haystack" | grep -q "$needle"; then
        log_success "$message"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: '$needle' found in output but should not be"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    local message="${2:-File does not exist}"
    
    if [ -f "$file" ]; then
        log_success "$message: $file"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: $file"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_file_not_exists() {
    local file="$1"
    local message="${2:-File should not exist}"
    
    if [ ! -f "$file" ]; then
        log_success "$message: $file"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: $file exists but should not"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_dir_exists() {
    local dir="$1"
    local message="${2:-Directory does not exist}"
    
    if [ -d "$dir" ]; then
        log_success "$message: $dir"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$message: $dir"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Wait functions
wait_for_condition() {
    local condition="$1"
    local timeout="${2:-30}"
    local interval="${3:-1}"
    local message="${4:-Waiting for condition}"
    
    log_info "$message (timeout: ${timeout}s)"
    
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if eval "$condition"; then
            log_success "Condition met after ${elapsed}s"
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done
    
    log_error "Timeout waiting for condition after ${timeout}s"
    return 1
}

wait_for_file() {
    local file="$1"
    local timeout="${2:-30}"
    
    wait_for_condition "[ -f '$file' ]" "$timeout" 1 "Waiting for file: $file"
}

wait_for_port() {
    local port="$1"
    local timeout="${2:-30}"
    
    wait_for_condition "nc -z localhost $port 2>/dev/null" "$timeout" 1 "Waiting for port: $port"
}

# Utility functions
run_with_timeout() {
    local timeout="$1"
    shift
    local cmd="$@"
    
    timeout "$timeout" bash -c "$cmd"
    return $?
}

get_timestamp() {
    date +"%Y-%m-%d %H:%M:%S"
}

# Test lifecycle functions
setup_test() {
    local test_name="$1"
    log_info "========================================="
    log_info "Starting test: $test_name"
    log_info "========================================="
}

teardown_test() {
    local test_name="$1"
    log_info "========================================="
    log_info "Finished test: $test_name"
    log_info "========================================="
}

cleanup_test_env() {
    log_info "Cleaning up test environment..."
    
    # Stop stage-env if running
    if [ -f "./stage-env" ]; then
        ./stage-env stop --force 2>/dev/null || true
    fi
    
    # Clean Docker containers
    docker ps -a --filter "name=cf-" -q | xargs -r docker rm -f 2>/dev/null || true
    
    # Remove test artifacts
    rm -rf ./testing/artifacts/test_* 2>/dev/null || true
    
    log_success "Cleanup complete"
}

# Summary functions
print_test_summary() {
    echo ""
    echo "========================================="
    echo "Test Summary"
    echo "========================================="
    echo -e "${GREEN}Passed:  $TESTS_PASSED${NC}"
    echo -e "${RED}Failed:  $TESTS_FAILED${NC}"
    echo -e "${YELLOW}Skipped: $TESTS_SKIPPED${NC}"
    echo "========================================="
    echo "Total:   $((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))"
    echo "========================================="
    
    if [ $TESTS_FAILED -gt 0 ]; then
        return 1
    else
        return 0
    fi
}

# Skip test function
skip_test() {
    local reason="$1"
    log_skip "$reason"
    ((TESTS_SKIPPED++))
    exit 0
}

# Require functions
require_command() {
    local cmd="$1"
    if ! command -v "$cmd" &> /dev/null; then
        skip_test "Required command not found: $cmd"
    fi
}

require_docker() {
    require_command docker
    if ! docker ps &> /dev/null; then
        skip_test "Docker is not running or not accessible"
    fi
}

require_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        skip_test "Required file not found: $file"
    fi
}

# Export functions
export -f log_info log_success log_error log_warning log_skip
export -f assert_success assert_failure assert_equals assert_contains assert_not_contains
export -f assert_file_exists assert_file_not_exists assert_dir_exists
export -f wait_for_condition wait_for_file wait_for_port
export -f run_with_timeout get_timestamp
export -f setup_test teardown_test cleanup_test_env
export -f print_test_summary skip_test
export -f require_command require_docker require_file
