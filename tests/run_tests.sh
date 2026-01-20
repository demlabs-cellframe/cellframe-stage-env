#!/usr/bin/env bash
# ============================================================================
# Stage-Env Testing Suite - Test Runner
# ============================================================================
# Запускает тесты с различными конфигурациями
# Usage: ./run_tests.sh [command] [options]
#
# Commands:
#   all          - Run all tests (default)
#   unit         - Run unit tests only
#   integration  - Run integration tests only
#   e2e          - Run e2e tests only
#   coverage     - Run with coverage report
#   fast         - Run fast tests only (exclude slow)
#   parallel     - Run tests in parallel
#   watch        - Run tests in watch mode (re-run on changes)
#   ci           - Run in CI mode (no interactive, strict)
#
# Options:
#   -v, --verbose    Verbose output
#   -x, --exitfirst  Exit on first failure
#   -k EXPRESSION    Run tests matching expression
#   --pdb           Start debugger on failure
#   --no-cov        Disable coverage
#   -n NUM          Run tests in parallel (NUM workers)

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default options
COMMAND="${1:-all}"
VERBOSE=""
EXITFIRST=""
EXPRESSION=""
PDB=""
NO_COV=""
PARALLEL=""
EXTRA_ARGS=()

# Parse arguments
shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE="-vv"
            shift
            ;;
        -x|--exitfirst)
            EXITFIRST="-x"
            shift
            ;;
        -k)
            EXPRESSION="-k $2"
            shift 2
            ;;
        --pdb)
            PDB="--pdb"
            shift
            ;;
        --no-cov)
            NO_COV="--no-cov"
            shift
            ;;
        -n)
            PARALLEL="-n $2"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

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

print_header() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║           Stage-Env Testing Suite - Test Runner                     ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# Check if virtual environment is activated
check_venv() {
    if [ -z "$VIRTUAL_ENV" ]; then
        log_warning "Virtual environment not activated"
        
        if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
            log_info "Activating virtual environment..."
            source "$PROJECT_ROOT/.venv/bin/activate"
            log_success "Virtual environment activated"
        else
            log_error "Virtual environment not found. Run ./setup.sh first"
            exit 1
        fi
    fi
}

# Check pytest installation
check_pytest() {
    if ! command -v pytest &> /dev/null; then
        log_error "pytest not found. Run ./setup.sh first"
        exit 1
    fi
}

# Run tests
run_tests() {
    local test_path="$1"
    local markers="$2"
    local description="$3"
    
    log_info "$description"
    echo ""
    
    cd "$SCRIPT_DIR"
    
    # Build pytest command
    local cmd="pytest"
    
    # Add path
    [ -n "$test_path" ] && cmd="$cmd $test_path"
    
    # Add markers
    [ -n "$markers" ] && cmd="$cmd -m \"$markers\""
    
    # Add options
    [ -n "$VERBOSE" ] && cmd="$cmd $VERBOSE"
    [ -n "$EXITFIRST" ] && cmd="$cmd $EXITFIRST"
    [ -n "$EXPRESSION" ] && cmd="$cmd $EXPRESSION"
    [ -n "$PDB" ] && cmd="$cmd $PDB"
    [ -n "$NO_COV" ] && cmd="$cmd $NO_COV"
    [ -n "$PARALLEL" ] && cmd="$cmd $PARALLEL"
    
    # Add extra args
    for arg in "${EXTRA_ARGS[@]}"; do
        cmd="$cmd $arg"
    done
    
    # Execute
    log_info "Running: $cmd"
    echo ""
    
    if eval $cmd; then
        echo ""
        log_success "Tests passed!"
        return 0
    else
        echo ""
        log_error "Tests failed!"
        return 1
    fi
}

# Command handlers
cmd_all() {
    run_tests "" "" "Running all tests..."
}

cmd_unit() {
    run_tests "unit/" "unit" "Running unit tests..."
}

cmd_integration() {
    run_tests "integration/" "integration" "Running integration tests..."
}

cmd_e2e() {
    run_tests "e2e/" "e2e" "Running e2e tests..."
}

cmd_coverage() {
    log_info "Running tests with coverage report..."
    cd "$SCRIPT_DIR"
    
    pytest \
        --cov=../src \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-report=xml \
        $VERBOSE $EXITFIRST $EXPRESSION $PDB "${EXTRA_ARGS[@]}"
    
    if [ $? -eq 0 ]; then
        echo ""
        log_success "Coverage report generated!"
        log_info "HTML report: file://$SCRIPT_DIR/htmlcov/index.html"
        log_info "XML report: $SCRIPT_DIR/coverage.xml"
    fi
}

cmd_fast() {
    run_tests "" "not slow" "Running fast tests only..."
}

cmd_parallel() {
    log_info "Running tests in parallel..."
    
    # Auto-detect CPU count
    if command -v nproc &> /dev/null; then
        CPUS=$(nproc)
    else
        CPUS=4
    fi
    
    PARALLEL="-n $CPUS"
    cmd_all
}

cmd_watch() {
    log_info "Running tests in watch mode..."
    log_warning "Press Ctrl+C to stop"
    echo ""
    
    cd "$SCRIPT_DIR"
    pytest-watch -- $VERBOSE $EXITFIRST $EXPRESSION "${EXTRA_ARGS[@]}"
}

cmd_ci() {
    log_info "Running tests in CI mode..."
    
    cd "$SCRIPT_DIR"
    
    pytest \
        --strict-markers \
        --strict-config \
        -v \
        --tb=short \
        --cov=../src \
        --cov-report=xml \
        --cov-report=term \
        --junit-xml=junit.xml \
        --maxfail=5 \
        "${EXTRA_ARGS[@]}"
    
    if [ $? -eq 0 ]; then
        log_success "CI tests passed!"
    else
        log_error "CI tests failed!"
        exit 1
    fi
}

cmd_smoke() {
    run_tests "" "smoke" "Running smoke tests..."
}

cmd_debug() {
    log_info "Running tests in debug mode..."
    PDB="--pdb"
    EXITFIRST="-x"
    VERBOSE="-vv"
    cmd_all
}

cmd_clean() {
    log_info "Cleaning test artifacts..."
    
    cd "$SCRIPT_DIR"
    
    rm -rf .pytest_cache
    rm -rf htmlcov
    rm -rf .coverage
    rm -f coverage.xml
    rm -f junit.xml
    rm -f tests.log
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    
    log_success "Test artifacts cleaned"
}

cmd_list() {
    log_info "Listing available tests..."
    cd "$SCRIPT_DIR"
    pytest --collect-only -q
}

cmd_help() {
    cat << EOF
Stage-Env Testing Suite - Test Runner

Usage: ./run_tests.sh [command] [options]

Commands:
  all          Run all tests (default)
  unit         Run unit tests only
  integration  Run integration tests only
  e2e          Run e2e tests only
  coverage     Run with coverage report
  fast         Run fast tests only (exclude slow)
  parallel     Run tests in parallel
  watch        Run tests in watch mode
  ci           Run in CI mode
  smoke        Run smoke tests only
  debug        Run with debugger enabled
  clean        Clean test artifacts
  list         List all available tests
  help         Show this help

Options:
  -v, --verbose    Verbose output
  -x, --exitfirst  Exit on first failure
  -k EXPRESSION    Run tests matching expression
  --pdb           Start debugger on failure
  --no-cov        Disable coverage
  -n NUM          Run tests in parallel (NUM workers)

Examples:
  ./run_tests.sh unit -v              # Run unit tests verbosely
  ./run_tests.sh coverage             # Run with coverage
  ./run_tests.sh all -x --pdb         # Debug first failure
  ./run_tests.sh all -k "test_docker" # Run tests matching "docker"
  ./run_tests.sh parallel -n 8        # Run with 8 workers
  ./run_tests.sh ci                   # Run in CI mode

For more info: pytest --help
EOF
}

# Main execution
main() {
    print_header
    
    check_venv
    check_pytest
    
    case $COMMAND in
        all)
            cmd_all
            ;;
        unit)
            cmd_unit
            ;;
        integration)
            cmd_integration
            ;;
        e2e)
            cmd_e2e
            ;;
        coverage)
            cmd_coverage
            ;;
        fast)
            cmd_fast
            ;;
        parallel)
            cmd_parallel
            ;;
        watch)
            cmd_watch
            ;;
        ci)
            cmd_ci
            ;;
        smoke)
            cmd_smoke
            ;;
        debug)
            cmd_debug
            ;;
        clean)
            cmd_clean
            ;;
        list)
            cmd_list
            ;;
        help|--help|-h)
            cmd_help
            ;;
        *)
            log_error "Unknown command: $COMMAND"
            echo ""
            cmd_help
            exit 1
            ;;
    esac
}

# Run main
main
