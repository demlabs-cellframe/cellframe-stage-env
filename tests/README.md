# Stage Environment Tests

This directory contains the testing framework for `stage-env`.

## Structure

*   `integration/`: Integration tests that simulate end-to-end scenarios (using mocked Docker).
    *   `scenarios/`: YAML test definitions.
        *   `base/`: Basic functionality tests.
        *   `common/`: Reusable test components (checks, setup, etc.).
        *   `examples/`: Example scenarios.
*   `unit/`: Unit tests for Python logic (executor, generator, parser).
*   `regression/`: Regression tests for specific bugs.
*   `fixtures/`: Shared test data and mocks.

## Running Tests

To run all tests:
```bash
# From tests/stage-env/tests/
pytest
```

To run only unit tests:
```bash
pytest -m unit
```

To run only integration tests:
```bash
pytest -m integration
```

## Adding Tests

1.  **Unit Tests**: Add new test files to `unit/` starting with `test_`.
2.  **Integration Tests**: Add new YAML scenarios to `integration/scenarios/` and optionally add a Python runner in `integration/` if custom logic is needed.
3.  **Regression Tests**: See `regression/README.md`.

## mocking

Tests use `unittest.mock` to simulate Docker interactions. Real Docker containers are NOT started during these tests.
Global fixtures are defined in `conftest.py` and `unit/conftest.py`.

