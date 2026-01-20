# Stage-Env Testing Guide

Comprehensive testing documentation for the stage-env testing system.

## Quick Start

```bash
# Setup (first time only)
./setup.sh

# Run all tests
./run_tests.sh

# Run specific test category
./run_tests.sh unit
./run_tests.sh integration
./run_tests.sh e2e
```

## Test Structure

```
tests/
├── unit/                  # Unit tests (187 tests)
│   ├── test_utils_*.py   # Utils module tests (96 tests)
│   ├── test_build_*.py   # Build module tests (21 tests)
│   ├── test_certs_*.py   # Certs module tests (7 tests)
│   ├── test_cli_*.py     # CLI module tests (13 tests)
│   └── ...
├── integration/           # Integration tests (19 tests)
│   ├── test_module_integration.py
│   ├── test_cli_monitoring_integration.py
│   └── ...
└── e2e/                   # End-to-end tests (33 tests)
    ├── test_network_lifecycle.py
    ├── test_configuration.py
    └── ...
```

## Test Categories

### Unit Tests (187 tests, <1s)
- **Purpose**: Test individual modules in isolation
- **Isolation**: Maximum (heavy mocking)
- **Speed**: Very fast (<100ms per test)
- **Coverage**: 100% of src/ modules

Run: `./run_tests.sh unit`

### Integration Tests (19 tests, ~5s)
- **Purpose**: Test module interactions
- **Isolation**: Minimal mocking
- **Speed**: Fast (<5s total)
- **Coverage**: Module integration points

Run: `./run_tests.sh integration`

### E2E Tests (33 tests, ~5-10min)
- **Purpose**: Test full system via public API
- **Isolation**: None (uses real scripts/clean.sh, scripts/run.sh)
- **Speed**: Slow (requires Docker, network setup)
- **Coverage**: Complete system lifecycle

Run: `./run_tests.sh e2e` (requires Docker)

## Running Tests

### Basic Commands

```bash
# All tests
pytest

# Specific category
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# Specific file
pytest tests/unit/test_utils_logger.py

# Specific test
pytest tests/unit/test_utils_logger.py::test_strip_ansi_codes

# With markers
pytest -m unit           # Unit tests only
pytest -m "not slow"     # Skip slow tests
pytest -m "not docker"   # Skip Docker-dependent tests
```

### Advanced Options

```bash
# Parallel execution (faster)
pytest -n auto

# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Show print statements
pytest -s

# Generate coverage report
pytest --cov=src --cov-report=html

# Debug mode
pytest --pdb --tb=long
```

## Test Fixtures

### Global Fixtures (tests/conftest.py)
- `stage_env_root`: Path to stage-env root
- `fixtures_dir`: Path to test fixtures

### Unit Test Fixtures (tests/unit/conftest.py)
- `mock_docker_client`: Mocked Docker client
- `mock_container_manager`: Mocked container manager

### E2E Test Fixtures (tests/e2e/conftest.py)
- `clean_environment`: Ensures clean state before test
- `running_network`: Provides running stage-env network
- `lifecycle`: StageEnvLifecycle helper instance

## Test Markers

```python
@pytest.mark.unit          # Unit test
@pytest.mark.integration   # Integration test
@pytest.mark.e2e           # E2E test
@pytest.mark.slow          # Slow test (skip in fast runs)
@pytest.mark.docker        # Requires Docker
@pytest.mark.network       # Requires network access
```

## CI/CD Integration

### GitHub Actions
Tests run automatically on:
- Push to main/develop
- Pull requests
- Changes to tests/stage-env/

See `.github/workflows/stage-env-tests.yml`

### Test Matrix
- Python 3.10, 3.11, 3.12
- Ubuntu latest
- Docker support for E2E

## Coverage

Current coverage: **~85%** (Unit + Integration)

```bash
# Generate coverage report
pytest --cov=src --cov-report=html

# View report
open .coverage/html/index.html
```

### Coverage Goals
- Overall: 90-95%
- Critical modules (config, docker_ctl, scenarios): 95%+
- Utility modules: 85%+

## Writing Tests

### Unit Test Template

```python
"""Unit tests for module_name."""

import pytest
from unittest.mock import MagicMock, patch

from src.module import MyClass


class TestMyClass:
    """Test MyClass functionality."""
    
    def test_basic_functionality(self):
        """Test basic operation."""
        obj = MyClass()
        result = obj.method()
        assert result == expected_value
    
    @patch('src.module.external_dependency')
    def test_with_mocking(self, mock_dep):
        """Test with mocked dependencies."""
        mock_dep.return_value = "mocked"
        obj = MyClass()
        result = obj.method_using_dep()
        assert result == "expected"
```

### E2E Test Template

```python
"""E2E tests for feature."""

import pytest


class TestFeature:
    """Test feature end-to-end."""
    
    def test_feature_works(self, running_network):
        """Test feature through public API."""
        # Use running_network fixture
        containers = running_network.get_running_containers()
        assert len(containers) > 0
```

## Troubleshooting

### Tests failing with "Docker not available"
```bash
# Check Docker is running
docker ps

# Start Docker if needed
sudo systemctl start docker
```

### Tests failing with "Module not found"
```bash
# Reinstall dependencies
./setup.sh
```

### E2E tests timing out
```bash
# Increase timeout
pytest tests/e2e/ --timeout=600
```

### Coverage not generated
```bash
# Install coverage tools
pip install pytest-cov coverage[toml]

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

## Performance

### Current Performance
- Unit tests: **0.66s** (187 tests)
- Integration tests: **~5s** (19 tests)
- E2E tests: **~5-10min** (33 tests, Docker-dependent)

### Optimization Tips
- Use `-n auto` for parallel execution
- Skip E2E tests during development: `pytest -m "not e2e"`
- Use `--lf` to rerun only failed tests
- Use `--ff` to run failures first

## Best Practices

1. **Keep tests fast**: Unit tests < 100ms, Integration < 5s
2. **Use appropriate mocking**: Heavy for unit, minimal for integration
3. **Clean up resources**: Use fixtures for setup/teardown
4. **Test edge cases**: Not just happy path
5. **Use descriptive names**: `test_method_raises_error_on_invalid_input`
6. **One assertion focus**: Each test should test one thing
7. **Avoid test interdependencies**: Tests should be independent
8. **Use parametrize**: For testing multiple inputs
9. **Document complex tests**: Add docstrings explaining "why"
10. **Keep tests maintainable**: Refactor when needed

## Contact & Support

For issues or questions:
- Check existing tests for examples
- Review this documentation
- Open an issue in the repository
