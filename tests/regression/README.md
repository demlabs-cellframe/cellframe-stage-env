# Regression Tests

This directory contains regression tests for specific bugs found in `stage-env`.

## How to add a new regression test

1. Create a new file named `test_issue_X.py` where X is the issue number or identifier.
2. Use the `mock_container_manager` fixture to simulate the environment.
3. Reproduce the bug by mocking the specific behavior that caused it (e.g., specific CLI output, error code, or sequence of events).
4. Assert that the bug is fixed (or write the test to fail if you are TDD-ing the fix).

## Example Template

See `test_issue_template.py` for a starting point.

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

def test_issue_reproduction(mock_container_manager):
    # Setup mock to return specific output
    mock_container_manager.exec_cli_command.return_value = {
        "returncode": 0, 
        "stdout": "Problematic output", 
        "stderr": ""
    }
    
    # ... execute code that parses this output ...
    
    # Assert correct handling
```

