#!/usr/bin/env bash
# ============================================================================
# Stage-Env Testing Suite - Setup Script
# ============================================================================
# Устанавливает все зависимости и настраивает окружение для тестирования
# Usage: ./setup.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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

print_header() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║           Stage-Env Testing Suite - Setup Script                    ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# Check Python version
check_python() {
    log_info "Checking Python version..."
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found. Please install Python 3.8+"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log_success "Python $PYTHON_VERSION found"
    
    # Check minimum version (3.8+)
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        log_error "Python 3.8+ required, found $PYTHON_VERSION"
        exit 1
    fi
}

# Check if virtual environment exists
check_venv() {
    log_info "Checking virtual environment..."
    
    if [ -d "$PROJECT_ROOT/.venv" ]; then
        log_success "Virtual environment found at $PROJECT_ROOT/.venv"
        return 0
    else
        log_warning "Virtual environment not found"
        return 1
    fi
}

# Create virtual environment
create_venv() {
    log_info "Creating virtual environment..."
    cd "$PROJECT_ROOT"
    python3 -m venv .venv
    log_success "Virtual environment created at $PROJECT_ROOT/.venv"
}

# Activate virtual environment
activate_venv() {
    log_info "Activating virtual environment..."
    
    if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
        source "$PROJECT_ROOT/.venv/bin/activate"
        log_success "Virtual environment activated"
    else
        log_error "Failed to activate virtual environment"
        exit 1
    fi
}

# Install dependencies
install_dependencies() {
    log_info "Installing dependencies..."
    
    cd "$PROJECT_ROOT"
    
    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip setuptools wheel
    
    # Install runtime dependencies
    if [ -f "requirements.txt" ]; then
        log_info "Installing runtime dependencies from requirements.txt..."
        pip install -r requirements.txt
    else
        log_warning "requirements.txt not found"
    fi
    
    # Install development dependencies
    if [ -f "requirements-dev.txt" ]; then
        log_info "Installing development dependencies from requirements-dev.txt..."
        pip install -r requirements-dev.txt
    else
        log_warning "requirements-dev.txt not found"
    fi
    
    log_success "Dependencies installed"
}

# Verify installation
verify_installation() {
    log_info "Verifying installation..."
    
    # Check pytest
    if ! python -c "import pytest" 2>/dev/null; then
        log_error "pytest not installed correctly"
        return 1
    fi
    log_success "pytest installed"
    
    # Check pytest plugins
    local plugins=("pytest_cov" "pytest_asyncio" "pytest_mock" "pytest_timeout" "xdist")
    for plugin in "${plugins[@]}"; do
        if python -c "import $plugin" 2>/dev/null; then
            log_success "pytest-${plugin//_/-} installed"
        else
            log_warning "pytest-${plugin//_/-} not found (optional)"
        fi
    done
    
    # Check docker
    if python -c "import docker" 2>/dev/null; then
        log_success "docker SDK installed"
    else
        log_error "docker SDK not installed"
        return 1
    fi
    
    return 0
}

# Check pytest configuration
check_pytest_config() {
    log_info "Checking pytest configuration..."
    
    cd "$SCRIPT_DIR"
    
    if [ ! -f "pytest.ini" ]; then
        log_error "pytest.ini not found"
        return 1
    fi
    log_success "pytest.ini found"
    
    if [ ! -f "../.coveragerc" ]; then
        log_warning ".coveragerc not found (optional)"
    else
        log_success ".coveragerc found"
    fi
    
    return 0
}

# List available tests
list_tests() {
    log_info "Collecting tests..."
    
    cd "$SCRIPT_DIR"
    
    if pytest --collect-only -q 2>/dev/null; then
        log_success "Test collection successful"
    else
        log_warning "No tests collected or collection failed"
    fi
}

# Create helper scripts
create_helper_scripts() {
    log_info "Creating helper scripts..."
    
    # Note: run_tests.sh will be created separately
    
    log_success "Helper scripts ready"
}

# Print summary
print_summary() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║                    Setup Complete!                                   ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "📋 Next Steps:"
    echo ""
    echo "  1. Activate virtual environment:"
    echo "     source .venv/bin/activate"
    echo ""
    echo "  2. Run tests:"
    echo "     ./tests/run_tests.sh"
    echo ""
    echo "  3. Run specific test types:"
    echo "     ./tests/run_tests.sh unit       # Unit tests only"
    echo "     ./tests/run_tests.sh integration # Integration tests"
    echo "     ./tests/run_tests.sh coverage   # With coverage report"
    echo ""
    echo "  4. View coverage report:"
    echo "     open tests/htmlcov/index.html"
    echo ""
}

# Main execution
main() {
    print_header
    
    check_python
    
    if ! check_venv; then
        create_venv
    fi
    
    activate_venv
    install_dependencies
    
    if ! verify_installation; then
        log_error "Installation verification failed"
        exit 1
    fi
    
    check_pytest_config
    list_tests
    create_helper_scripts
    
    print_summary
    
    log_success "Setup completed successfully!"
}

# Run main
main "$@"
