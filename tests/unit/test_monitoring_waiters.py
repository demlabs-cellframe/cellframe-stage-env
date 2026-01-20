"""Unit tests for src/monitoring/waiter/ - stubs."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestWaitersModules:
    """Stub tests for waiter modules."""
    
    def test_import_chain_waiters(self):
        from src.monitoring.waiter import chain_waiters
        assert chain_waiters is not None
    
    def test_import_datum_waiters(self):
        from src.monitoring.waiter import datum_waiters
        assert datum_waiters is not None
