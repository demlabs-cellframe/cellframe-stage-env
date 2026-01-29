"""Unit tests for new features: print step, multi-node waiters."""

import pytest
from pathlib import Path
import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import ScenarioExecutor, RuntimeContext
from src.scenarios.schema import PrintStep, TestScenario, WaitStep
from src.scenarios.step.print import PrintStepExecutor
from src.monitoring.waiter.genesis_waiters import GlobalDBNodeListSyncWaiter
from src.network.models import NodeConfig


class TestPrintStep:
    """Test Print step functionality."""
    
    @pytest.mark.asyncio
    async def test_print_step_basic(self):
        """Test basic print step execution."""
        executor = PrintStepExecutor()
        scenario = TestScenario(name="test", description="Test", test=[])
        ctx = RuntimeContext(scenario)
        
        step = PrintStep(print="Hello, World!")
        
        await executor.execute(step, ctx)
        
        # Verify result added to context
        assert len(ctx.step_results) == 1
        assert ctx.step_results[0]["success"] is True
        assert ctx.step_results[0]["details"]["message"] == "Hello, World!"
    
    @pytest.mark.asyncio
    async def test_print_step_with_variable_substitution(self):
        """Test print step with Jinja2 variable substitution."""
        executor = PrintStepExecutor()
        scenario = TestScenario(name="test", description="Test", test=[])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("node_name", "node-1")
        ctx.set_variable("status", "online")
        
        step = PrintStep(print="Node {{node_name}} is {{status}}")
        
        await executor.execute(step, ctx)
        
        # Verify substitution
        assert ctx.step_results[0]["details"]["message"] == "Node node-1 is online"
    
    @pytest.mark.asyncio
    async def test_print_step_with_dict_variable(self):
        """Test print step with dictionary variable."""
        executor = PrintStepExecutor()
        scenario = TestScenario(name="test", description="Test", test=[])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("result", {"hash": "0xABC123", "status": "ok"})
        
        step = PrintStep(print="Result: {{result}}")
        
        await executor.execute(step, ctx)
        
        # Verify dict printed
        assert "hash" in ctx.step_results[0]["details"]["message"]
        assert "0xABC123" in ctx.step_results[0]["details"]["message"]


class TestGlobalDBSyncWaiterMultiNode:
    """Test GlobalDBNodeListSyncWaiter multi-node support."""
    
    @pytest.mark.asyncio
    async def test_single_node_sync(self):
        """Test waiting for single node sync."""
        node1 = NodeConfig(node_id=1, role="root")
        
        # Mock exec_cli
        def mock_exec_cli(node_id, command, check_output=False):
            # Return synced output
            return (0, "Node list:\n  node1: 192.168.1.1\n  node2: 192.168.1.2\n", "")
        
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node1],
            network_name="stagenet"
        )
        
        result = await waiter.check()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_multi_node_sync_all_ready(self):
        """Test waiting for multiple nodes when all are synced."""
        node1 = NodeConfig(node_id=1, role="root")
        node2 = NodeConfig(node_id=2, role="root")
        node3 = NodeConfig(node_id=3, role="master")
        
        # Mock exec_cli - all nodes return synced
        def mock_exec_cli(node_id, command, check_output=False):
            return (0, "Node list:\n  node1: 192.168.1.1\n  node2: 192.168.1.2\n", "")
        
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node1, node2, node3],
            network_name="stagenet"
        )
        
        result = await waiter.check()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_multi_node_sync_partial_ready(self):
        """Test waiting for multiple nodes when only some are synced."""
        node1 = NodeConfig(node_id=1, role="root")
        node2 = NodeConfig(node_id=2, role="root")
        node3 = NodeConfig(node_id=3, role="master")
        
        call_count = {"count": 0}
        
        # Mock exec_cli - node3 not synced on first call
        def mock_exec_cli(node_id, command, check_output=False):
            call_count["count"] += 1
            if node_id == 3 and call_count["count"] < 3:
                # Node 3 not synced yet
                return (0, "No records", "")
            return (0, "Node list:\n  node1: 192.168.1.1\n  node2: 192.168.1.2\n", "")
        
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node1, node2, node3],
            network_name="stagenet"
        )
        
        # First check - not all synced
        result1 = await waiter.check()
        assert result1 is False
        
        # Second check - still not all synced
        result2 = await waiter.check()
        assert result2 is False
        
        # Third check - all synced
        result3 = await waiter.check()
        assert result3 is True
    
    @pytest.mark.asyncio
    async def test_backward_compatibility_single_node_param(self):
        """Test backward compatibility with single 'node' parameter."""
        node1 = NodeConfig(node_id=1, role="root")
        
        def mock_exec_cli(node_id, command, check_output=False):
            return (0, "Node list:\n  node1: 192.168.1.1\n", "")
        
        # Use old 'node' parameter
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            node=node1,  # Old single-node API
            network_name="stagenet"
        )
        
        result = await waiter.check()
        
        assert result is True


class TestWaitStepSchemaValidation:
    """Test WaitStep schema validation for new features."""
    
    def test_wait_step_with_nodes_list(self):
        """Test WaitStep accepts nodes parameter."""
        step = WaitStep(
            wait="global_db_sync",
            nodes=["node1", "node2", "node3"],
            timeout=60
        )
        
        assert step.wait == "global_db_sync"
        assert step.nodes == ["node1", "node2", "node3"]
        assert step.timeout == 60
    
    def test_wait_step_with_min_blocks(self):
        """Test WaitStep accepts min_blocks parameter for block_created."""
        step = WaitStep(
            wait="block_created",
            node="node1",
            chain="main",
            min_blocks=5,
            timeout=120
        )
        
        assert step.wait == "block_created"
        assert step.min_blocks == 5
        assert step.chain == "main"


class TestPrintStepSchemaValidation:
    """Test PrintStep schema validation."""
    
    def test_print_step_creation(self):
        """Test PrintStep can be created."""
        step = PrintStep(print="Debug message")
        
        assert step.print == "Debug message"
    
    def test_print_step_with_jinja2(self):
        """Test PrintStep accepts Jinja2 templates."""
        step = PrintStep(print="Node {{node_id}} has hash {{hash_value}}")
        
        assert "{{node_id}}" in step.print
        assert "{{hash_value}}" in step.print
