"""Unit tests for new scenario operands: print, multi-node waiters."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import RuntimeContext
from src.scenarios.schema import PrintStep, TestScenario, WaitStep, CLIStep
from src.scenarios.step.print import PrintStepExecutor
from src.monitoring.waiter.genesis_waiters import GlobalDBNodeListSyncWaiter
from src.network.models import NodeConfig


def create_node_config(node_id, role="root"):
    """Helper to create valid NodeConfig for tests."""
    return NodeConfig(
        node_id=node_id,
        role=role,
        node_type=role,
        rpc_port=8000 + node_id,
        p2p_port=9000 + node_id,
        cf_port=10000 + node_id,
        http_port=11000 + node_id,
        ip_address=f"172.20.0.{10 + node_id}"
    )


class TestPrintOperand:
    """Tests for print operand."""
    
    @pytest.mark.asyncio
    async def test_print_basic(self):
        """Test basic print operand."""
        executor = PrintStepExecutor(container_manager=None)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        step = PrintStep(print="Test message")
        
        await executor.execute(step, ctx)
        
        assert len(ctx.step_results) == 1
        assert ctx.step_results[0]["success"] is True
        assert ctx.step_results[0]["type"] == "print"
        assert ctx.step_results[0]["message"] == "Test message"
    
    @pytest.mark.asyncio
    async def test_print_with_variables(self):
        """Test print with variable substitution."""
        executor = PrintStepExecutor(container_manager=None)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("node", "node-1")
        ctx.set_variable("status", "ready")
        
        step = PrintStep(print="Node {{node}} is {{status}}")
        await executor.execute(step, ctx)
        
        assert ctx.step_results[0]["message"] == "Node node-1 is ready"


class TestGlobalDBSyncMultiNode:
    """Tests for multi-node global_db_sync waiter."""
    
    @pytest.mark.asyncio
    async def test_single_node_synced(self):
        """Test sync check with single node."""
        def mock_exec_cli(node_id, cmd, check_output=False):
            # Return output > min_output_length (50) to indicate sync
            output = "Node list:\n"
            for idx in range(1, 11):
                output += f"  node{idx}: 192.168.1.{idx}\n"
            return (0, output, "")
        
        node = create_node_config(1, "root")
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node],
            network_name="stagenet"
        )
        
        result = await waiter.check()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_multiple_nodes_all_synced(self):
        """Test sync check with multiple nodes, all ready."""
        def mock_exec_cli(node_id, cmd, check_output=False):
            # Return sufficient output to pass min_output_length check
            output = "Node list:\n"
            for idx in range(1, 11):
                output += f"  node{idx}: 192.168.1.{idx}\n"
            return (0, output, "")
        
        nodes = [create_node_config(i, "root") for i in range(1, 4)]
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=nodes,
            network_name="stagenet"
        )
        
        result = await waiter.check()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_multiple_nodes_partial_sync(self):
        """Test sync check when some nodes not ready yet."""
        call_count = [0]
        
        def mock_exec_cli(node_id, cmd, check_output=False):
            call_count[0] += 1
            # Node 3 not synced first 4 times (covering check 1 and 2)
            if node_id == 3 and call_count[0] <= 4:
                return (0, "No records", "")
            # Return sufficient output for synced nodes
            output = "Node list:\n"
            for idx in range(1, 11):
                output += f"  node{idx}: 192.168.1.{idx}\n"
            return (0, output, "")
        
        nodes = [create_node_config(i, "root") for i in range(1, 4)]
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=nodes,
            network_name="stagenet"
        )
        
        # First check - node1,2 sync, node3 not synced
        assert await waiter.check() is False
        # Second check - node1,2 already synced (cached), node3 still not synced
        assert await waiter.check() is False
        # Third check - all synced now
        assert await waiter.check() is True


class TestWaitStepSchema:
    """Tests for WaitStep schema with new parameters."""
    
    def test_wait_with_nodes_list(self):
        """Test WaitStep with nodes parameter."""
        step = WaitStep(
            wait="global_db_sync",
            nodes=["node1", "node2"],
            timeout=60
        )
        assert step.nodes == ["node1", "node2"]
    
    def test_wait_with_min_blocks(self):
        """Test WaitStep with min_blocks parameter."""
        step = WaitStep(
            wait="block_created",
            node="node1",
            chain="main",
            min_blocks=5
        )
        assert step.min_blocks == 5


class TestPrintStepSchema:
    """Tests for PrintStep schema."""
    
    def test_print_step_creation(self):
        """Test PrintStep schema validation."""
        step = PrintStep(print="Debug output")
        assert step.print == "Debug output"
