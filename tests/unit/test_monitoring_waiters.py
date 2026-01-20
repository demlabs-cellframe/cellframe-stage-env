"""Unit tests for src/monitoring/waiter/ modules."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ============================================================================
# BaseWaiter Tests
# ============================================================================

class TestBaseWaiter:
    """Test BaseWaiter abstract class."""
    
    @pytest.mark.asyncio
    async def test_base_waiter_timeout(self):
        """Test BaseWaiter timeout functionality."""
        from src.monitoring.base import BaseWaiter
        
        class TestWaiter(BaseWaiter):
            async def check(self) -> bool:
                return False  # Never succeeds
        
        waiter = TestWaiter(poll_interval=0.1)
        
        with pytest.raises(asyncio.TimeoutError):
            await waiter.wait(timeout=0.3)
    
    @pytest.mark.asyncio
    async def test_base_waiter_success(self):
        """Test BaseWaiter successful wait."""
        from src.monitoring.base import BaseWaiter
        
        class TestWaiter(BaseWaiter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.check_count = 0
            
            async def check(self) -> bool:
                self.check_count += 1
                return self.check_count >= 3  # Succeed on 3rd check
        
        waiter = TestWaiter(poll_interval=0.05)
        result = await waiter.wait(timeout=1.0)
        
        # wait() returns None on success
        assert waiter.check_count >= 3


# ============================================================================
# DatumWaiter Tests
# ============================================================================

class TestDatumWaiters:
    """Test datum waiter classes."""
    
    def test_datum_in_mempool_waiter_init(self):
        """Test DatumInMempoolWaiter initialization."""
        from src.monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = MagicMock()
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=1,
            datum_hash="0xabc123",
            network_name="testnet",
            chain="mainchain",
            poll_interval=1.0
        )
        
        assert waiter.exec_cli is exec_cli
        assert waiter.node_id == 1
        assert waiter.datum_hash == "0xabc123"
        assert waiter.network_name == "testnet"
        assert waiter.chain == "mainchain"
        assert waiter.poll_interval == 1.0
    
    @pytest.mark.asyncio
    async def test_datum_in_mempool_waiter_check_found(self):
        """Test DatumInMempoolWaiter check when datum is found."""
        from src.monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = MagicMock()
        exec_cli.return_value = (0, "datum: 0xabc123\nother data", "")
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=1,
            datum_hash="0xabc123",
            poll_interval=0.1
        )
        
        result = await waiter.check()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_datum_in_mempool_waiter_check_not_found(self):
        """Test DatumInMempoolWaiter check when datum not found."""
        from src.monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = MagicMock()
        exec_cli.return_value = (0, "other datum: 0xdef456", "")
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=1,
            datum_hash="0xabc123",
            poll_interval=0.1
        )
        
        result = await waiter.check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_datum_in_mempool_waiter_container_crash(self):
        """Test DatumInMempoolWaiter handles container crash."""
        from src.monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = MagicMock()
        exec_cli.return_value = (1, "", "container not running")
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=1,
            datum_hash="0xabc123",
            poll_interval=0.1
        )
        
        with pytest.raises(RuntimeError, match="Container crashed"):
            await waiter.check()


# ============================================================================
# TokenWaiter Tests  
# ============================================================================

class TestTokenWaiters:
    """Test token waiter classes - basic import test."""
    
    def test_token_waiters_import(self):
        """Test importing token waiters module."""
        from src.monitoring.waiter import token_waiters
        assert token_waiters is not None


# ============================================================================
# SyncWaiter Tests
# ============================================================================

class TestSyncWaiters:
    """Test sync waiter classes - basic import test."""
    
    def test_sync_waiters_import(self):
        """Test importing sync waiters module."""
        from src.monitoring.waiter import sync_waiters
        assert sync_waiters is not None


# ============================================================================
# GenesisWaiter Tests
# ============================================================================

class TestGenesisWaiters:
    """Test genesis waiter classes - basic import test."""
    
    def test_genesis_waiters_import(self):
        """Test importing genesis waiters module."""
        from src.monitoring.waiter import genesis_waiters
        assert genesis_waiters is not None


# ============================================================================
# Integration Tests
# ============================================================================

class TestWaitersIntegration:
    """Integration tests for multiple waiters."""
    
    @pytest.mark.asyncio
    async def test_multiple_waiters_parallel(self):
        """Test running multiple waiters in parallel."""
        from src.monitoring.base import BaseWaiter
        
        class FastWaiter(BaseWaiter):
            async def check(self) -> bool:
                await asyncio.sleep(0.01)
                return True
        
        class SlowWaiter(BaseWaiter):
            async def check(self) -> bool:
                await asyncio.sleep(0.05)
                return True
        
        fast = FastWaiter(poll_interval=0.01)
        slow = SlowWaiter(poll_interval=0.02)
        
        # Both should succeed (wait() returns None on success)
        results = await asyncio.gather(
            fast.wait(timeout=1.0),
            slow.wait(timeout=1.0)
        )
        
        # Both completed without timeout
        assert len(results) == 2
    
    @pytest.mark.asyncio
    async def test_waiter_timeout_behavior(self):
        """Test waiter timeout behavior."""
        from src.monitoring.base import BaseWaiter
        
        class NeverSucceedsWaiter(BaseWaiter):
            async def check(self) -> bool:
                return False
        
        waiter = NeverSucceedsWaiter(poll_interval=0.05)
        
        start = asyncio.get_event_loop().time()
        with pytest.raises(asyncio.TimeoutError):
            await waiter.wait(timeout=0.2)
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should timeout around 0.2s
        assert 0.15 < elapsed < 0.35
    
    @pytest.mark.asyncio
    async def test_waiter_early_success(self):
        """Test waiter succeeds before timeout."""
        from src.monitoring.base import BaseWaiter
        
        class QuickSuccessWaiter(BaseWaiter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.attempts = 0
            
            async def check(self) -> bool:
                self.attempts += 1
                return self.attempts >= 2
        
        waiter = QuickSuccessWaiter(poll_interval=0.05)
        
        start = asyncio.get_event_loop().time()
        result = await waiter.wait(timeout=10.0)
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should succeed quickly, not wait full timeout
        assert elapsed < 0.5
        assert waiter.attempts >= 2


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestWaitersErrorHandling:
    """Test error handling in waiters."""
    
    @pytest.mark.asyncio
    async def test_waiter_exception_in_check(self):
        """Test waiter handles exceptions in check method."""
        from src.monitoring.base import BaseWaiter
        
        class FailingWaiter(BaseWaiter):
            async def check(self) -> bool:
                raise ValueError("Simulated error")
        
        waiter = FailingWaiter(poll_interval=0.1)
        
        with pytest.raises(ValueError, match="Simulated error"):
            await waiter.wait(timeout=0.3)
    
    @pytest.mark.asyncio
    async def test_datum_waiter_cli_failure(self):
        """Test datum waiter handles CLI failures gracefully."""
        from src.monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = MagicMock()
        exec_cli.return_value = (1, "", "command not found")
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=1,
            datum_hash="0xabc",
            poll_interval=0.1
        )
        
        # Should return False, not crash
        result = await waiter.check()
        assert result is False
