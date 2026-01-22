#!/bin/bash
#
# Master test runner for all stage-env bash tests
#
# Usage:
#   ./run_all_tests.sh                # Run all tests
#   ./run_all_tests.sh functional     # Run only functional tests
#   ./run_all_tests.sh e2e            # Run only e2e tests
#   ./run_all_tests.sh --fast         # Skip slow tests

set -euo pipefail

# Get script directory
SCRIPT_DIR="$PWD/../scripts/"  #"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source helpers
source "$SCRIPT_DIR/helpers.sh"

# Parse arguments
RUN_FUNCTIONAL=false
RUN_E2E=false
SKIP_SLOW=false

if [ $# -eq 0 ]; then
    RUN_FUNCTIONAL=true
    RUN_E2E=true
else
    for arg in "$@"; do
        case $arg in
            functional)
                RUN_FUNCTIONAL=true
                ;;
            e2e)
                RUN_E2E=true
                ;;
            --fast)
                SKIP_SLOW=true
                export SKIP_SLOW_TESTS=1
                ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS] [SUITE]"
                echo ""
                echo "Suites:"
                echo "  functional   Run functional tests"
                echo "  e2e          Run e2e tests"
                echo "  (none)       Run all tests"
                echo ""
                echo "Options:"
                echo "  --fast       Skip slow tests"
                echo "  -h, --help   Show this help"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $arg"
                exit 1
                ;;
        esac
    done
fi

log_info "========================================="
log_info "Stage-Env Bash Test Suite"
log_info "========================================="

# Counters for all tests
TOTAL_PASSED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0

# Function to run a single test script
run_test_script() {
    local script="$1"
    local name=$(basename "$script" .sh)
    
    log_info ""
    log_info "Running: $name"
    log_info "-----------------------------------------"
    
    if bash "$script"; then
        log_success "✓ $name passed"
        return 0
    else
        log_error "✗ $name failed"
        return 1
    fi
}

# Run functional tests
if [ "$RUN_FUNCTIONAL" = true ]; then
    log_info ""
    log_info "========================================="
    log_info "Running Functional Tests"
    log_info "========================================="
    
    FUNCTIONAL_DIR="$SCRIPT_DIR/functional"
    
    if [ -d "$FUNCTIONAL_DIR" ]; then
        for test_script in "$FUNCTIONAL_DIR"/test_*.sh; do
            if [ -f "$test_script" ] && [ -x "$test_script" ]; then
                if run_test_script "$test_script"; then
                    ((TOTAL_PASSED++))
                else
                    ((TOTAL_FAILED++))
                fi
            fi
        done
    else
        log_warning "Functional tests directory not found: $FUNCTIONAL_DIR"
    fi
fi

# Run e2e tests
if [ "$RUN_E2E" = true ]; then
    if [ "$SKIP_SLOW" = true ]; then
        log_warning "Skipping E2E tests (--fast mode)"
    else
        log_info ""
        log_info "========================================="
        log_info "Running E2E Tests"
        log_info "========================================="
        
        E2E_DIR="$SCRIPT_DIR/e2e"
        
        if [ -d "$E2E_DIR" ]; then
            for test_script in "$E2E_DIR"/test_*.sh; do
                if [ -f "$test_script" ] && [ -x "$test_script" ]; then
                    if run_test_script "$test_script"; then
                        ((TOTAL_PASSED++))
                    else
                        ((TOTAL_FAILED++))
                    fi
                fi
            done
        else
            log_warning "E2E tests directory not found: $E2E_DIR"
        fi
    fi
fi

# Final summary
echo ""
echo "========================================="
echo "Overall Test Summary"
echo "========================================="
echo -e "${GREEN}Passed:  $TOTAL_PASSED test suites${NC}"
echo -e "${RED}Failed:  $TOTAL_FAILED test suites${NC}"
echo -e "${YELLOW}Skipped: $TOTAL_SKIPPED test suites${NC}"
echo "========================================="

if [ $TOTAL_FAILED -gt 0 ]; then
    log_error "Some tests failed!"
    exit 1
else
    log_success "All tests passed!"
    exit 0
fi
