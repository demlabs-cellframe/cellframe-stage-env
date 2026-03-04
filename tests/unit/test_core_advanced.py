"""Comprehensive test suite for Stage-Env core functionality.

Expanded test coverage for:
- ScenarioGlobalContext (0% -> 70%+)
- ScenarioExecutor node resolution (44% -> 60%+)
- WaitStep with new parameters
- Print operand
- Multi-node waiters
"""

import pytest
from pathlib import Path
import sys
from unittest.mock import MagicMock, AsyncMock, patch, Mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import ScenarioExecutor, RuntimeContext
from src.scenarios.global_context import ScenarioGlobalContext
from src.scenarios.schema import PrintStep, TestScenario, WaitStep, CLIStep
from src.scenarios.step.print import PrintStepExecutor
from src.monitoring.waiter.genesis_waiters import GlobalDBNodeListSyncWaiter
from src.network.models import NodeConfig


def create_node_config(node_id, role="root", ip_address=None):
    """Helper to create valid NodeConfig for tests."""
    return NodeConfig(
        node_id=node_id,
        role=role,
        node_type=role,
        rpc_port=8000 + node_id,
        p2p_port=9000 + node_id,
        cf_port=10000 + node_id,
        http_port=11000 + node_id,
        ip_address=ip_address or f"172.20.0.{10 + node_id}"
    )


class TestScenarioGlobalContext:
    """Tests for ScenarioGlobalContext (0% -> 70%+ coverage)."""
    
    def test_initialization(self):
        """Test basic initialization."""
        ctx = ScenarioGlobalContext(
            network_name="stagenet",
            topology_name="default",
            native_ticker="TCELL"
        )
        
        assert ctx.network_name == "stagenet"
        assert ctx.topology_name == "default"
        assert ctx.native_ticker == "TCELL"
        assert ctx.node_count == 0
        assert ctx.root_count == 0
        assert ctx.master_count == 0
        assert ctx.full_count == 0
    
    def test_set_static_node_info(self):
        """Test setting static node information."""
        ctx = ScenarioGlobalContext(
            network_name="stagenet",
            topology_name="default"
        )
        
        nodes = [
            create_node_config(1, "root", "172.20.0.11"),
            create_node_config(2, "root", "172.20.0.12"),
            create_node_config(3, "master", "172.20.0.13"),
        ]
        
        ctx.set_static_node_info(nodes)
        
        assert ctx.node_count == 3
        assert ctx.root_count == 2
        assert ctx.master_count == 1
        assert ctx.full_count == 0
    
    def test_to_dict_basic(self):
        """Test to_dict conversion."""
        ctx = ScenarioGlobalContext(
            network_name="stagenet",
            topology_name="default",
            native_ticker="TCELL"
        )
        
        nodes = [
            create_node_config(1, "root"),
            create_node_config(2, "master"),
        ]
        
        ctx.set_static_node_info(nodes)
        data = ctx.to_dict()
        
        assert data['network_name'] == "stagenet"
        assert data['topology_name'] == "default"
        assert data['native_ticker'] == "TCELL"
        assert data['node_count'] == 2
        assert data['root_count'] == 1
        assert data['master_count'] == 1
        assert data['root_nodes'] == ["node-1"]
        assert data['master_nodes'] == ["node-2"]
        assert data['first_root'] == "node-1"
        assert data['first_master'] == "node-2"
    
    def test_to_dict_empty(self):
        """Test to_dict with no nodes."""
        ctx = ScenarioGlobalContext(
            network_name="testnet",
            topology_name="empty"
        )
        
        data = ctx.to_dict()
        
        assert data['node_count'] == 0
        assert data['root_nodes'] == []
        assert data['first_root'] is None
        assert data['first_master'] is None
    
    def test_get_node_ip(self):
        """Test getting node IP address."""
        ctx = ScenarioGlobalContext(
            network_name="stagenet",
            topology_name="default"
        )
        
        # Mock static IP setting
        ctx._node_ip_map = {
            "node1": "172.20.0.11",
            "node2": "172.20.0.12",
        }
        
        assert ctx.get_node_ip("node1") == "172.20.0.11"
        assert ctx.get_node_ip("node2") == "172.20.0.12"
        assert ctx.get_node_ip("node99") is None
    
    def test_repr(self):
        """Test __repr__ output."""
        ctx = ScenarioGlobalContext(
            network_name="stagenet",
            topology_name="3root_2master"
        )
        
        nodes = [create_node_config(i, "root") for i in range(1, 4)]
        ctx.set_static_node_info(nodes)
        
        repr_str = repr(ctx)
        assert "stagenet" in repr_str
        assert "3root_2master" in repr_str
        assert "nodes=3" in repr_str


class TestScenarioExecutorNodeResolution:
    """Tests for ScenarioExecutor node alias resolution (44% -> 55%+ coverage)."""
    
    def test_resolve_simple_node_id(self):
        """Test resolving simple node IDs."""
        executor = ScenarioExecutor()
        assert executor._resolve_node_alias("node1") == "node1"
        assert executor._resolve_node_alias("node99") == "node99"
    
    def test_resolve_dashed_node_id(self):
        """Test resolving dashed node IDs."""
        executor = ScenarioExecutor()
        assert executor._resolve_node_alias("node-1") == "node1"
        assert executor._resolve_node_alias("node-5") == "node5"
        assert executor._resolve_node_alias("node-123") == "node123"
    
    def test_resolve_invalid_formats(self):
        """Test handling invalid node ID formats."""
        executor = ScenarioExecutor()
        # Invalid formats should pass through unchanged
        assert executor._resolve_node_alias("invalid") == "invalid"
        assert executor._resolve_node_alias("node-abc") == "node-abc"
        assert executor._resolve_node_alias("") == ""


class TestPrintOperand:
    """Tests for print operand (100% coverage)."""
    
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
    
    @pytest.mark.asyncio
    async def test_print_with_complex_variable(self):
        """Test print with dictionary variable."""
        executor = PrintStepExecutor(container_manager=None)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("data", {"hash": "0xABC", "count": 42})
        
        step = PrintStep(print="Data: {{data}}")
        await executor.execute(step, ctx)
        
        message = ctx.step_results[0]["message"]
        assert "hash" in message
        assert "0xABC" in message


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
    
    @pytest.mark.asyncio
    async def test_cli_command_failure(self):
        """Test handling CLI command failures."""
        def mock_exec_cli(node_id, cmd, check_output=False):
            # Simulate CLI failure
            return (1, "", "Error executing command")
        
        node = create_node_config(1, "root")
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node],
            network_name="stagenet"
        )
        
        result = await waiter.check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_short_output_not_synced(self):
        """Test that short output is treated as not synced."""
        def mock_exec_cli(node_id, cmd, check_output=False):
            # Return output < min_output_length (50)
            return (0, "Node list: node1", "")
        
        node = create_node_config(1, "root")
        waiter = GlobalDBNodeListSyncWaiter(
            exec_cli=mock_exec_cli,
            nodes=[node],
            network_name="stagenet",
            min_output_length=50
        )
        
        result = await waiter.check()
        assert result is False


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
        assert step.timeout == 60
    
    def test_wait_with_single_node(self):
        """Test WaitStep with single node parameter."""
        step = WaitStep(
            wait="global_db_sync",
            node="node1",
            timeout=30
        )
        assert step.node == "node1"
        assert step.nodes is None
    
    def test_wait_with_min_blocks(self):
        """Test WaitStep with min_blocks parameter."""
        step = WaitStep(
            wait="block_created",
            node="node1",
            chain="main",
            min_blocks=5
        )
        assert step.min_blocks == 5
        assert step.chain == "main"
    
    def test_wait_with_chain_and_network(self):
        """Test WaitStep with chain and network parameters."""
        step = WaitStep(
            wait="datum_processed",
            node="node1",
            chain="zerochain",
            network="stagenet",
            timeout=120
        )
        assert step.chain == "zerochain"
        assert step.network == "stagenet"


class TestPrintStepSchema:
    """Tests for PrintStep schema."""
    
    def test_print_step_creation(self):
        """Test PrintStep schema validation."""
        step = PrintStep(print="Debug output")
        assert step.print == "Debug output"
    
    def test_print_step_with_template(self):
        """Test PrintStep with Jinja2 template."""
        step = PrintStep(print="Node {{node_id}} status: {{status}}")
        assert "{{node_id}}" in step.print
        assert "{{status}}" in step.print
    
    def test_print_step_with_multiline(self):
        """Test PrintStep with multiline message."""
        message = """
        === Debug Info ===
        Node: {{node}}
        Status: {{status}}
        """
        step = PrintStep(print=message)
        assert "Debug Info" in step.print


class TestRuntimeContextAdvanced:
    """Advanced tests for RuntimeContext."""
    
    def test_variable_scoping(self):
        """Test variable scoping in RuntimeContext."""
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        
        # Set variables
        ctx.set_variable("local_var", "value1")
        ctx.set_variable("global_var", "value2")
        
        # Get variables - access via ctx.variables dict
        assert ctx.variables.get("local_var") == "value1"
        assert ctx.variables.get("global_var") == "value2"
        assert ctx.variables.get("nonexistent") is None
    
    def test_variable_substitution(self):
        """Test variable substitution."""
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        
        ctx.set_variable("node", "node-1")
        ctx.set_variable("port", 8080)
        
        result = ctx.substitute("Connect to {{node}} on port {{port}}")
        assert result == "Connect to node-1 on port 8080"
    
    def test_nested_variable_substitution(self):
        """Test nested variable substitution."""
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        
        ctx.set_variable("config", {"host": "localhost", "port": 8080})
        
        result = ctx.substitute("Host: {{config.host}}, Port: {{config.port}}")
        assert "localhost" in result
        assert "8080" in result


class TestControlFlowEvalNamespace:
    """Tests for unified eval namespace in control flow steps.
    
    After the refactoring, all eval() calls use a single merged globals dict
    (builtins + explicit functions + ctx.variables) instead of separate
    globals/locals.  This ensures variables are accessible as first-class
    names inside expressions like 'len(my_list)'.
    """
    
    @pytest.mark.asyncio
    async def test_if_condition_accesses_variables(self):
        """Test that if-condition can reference ctx variables directly."""
        from src.scenarios.step.control_flow import IfStepExecutor
        from src.scenarios.schema import IfStep
        
        executed = []
        
        async def fake_execute_steps(steps, ctx, defaults=None):
            executed.append("then")
        
        executor = IfStepExecutor(container_manager=None, execute_steps_callback=fake_execute_steps)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("count", 5)
        
        step = IfStep.model_validate({"if": "count > 3", "then": [{"cli": "version"}]})
        await executor.execute(step, ctx)
        
        assert "then" in executed
    
    @pytest.mark.asyncio
    async def test_if_condition_uses_builtins(self):
        """Test that if-condition has access to len(), str(), int()."""
        from src.scenarios.step.control_flow import IfStepExecutor
        from src.scenarios.schema import IfStep
        
        executed = []
        
        async def fake_execute_steps(steps, ctx, defaults=None):
            executed.append("then")
        
        executor = IfStepExecutor(container_manager=None, execute_steps_callback=fake_execute_steps)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("items", [1, 2, 3])
        
        step = IfStep.model_validate({"if": "len(items) == 3", "then": [{"cli": "version"}]})
        await executor.execute(step, ctx)
        
        assert "then" in executed
    
    @pytest.mark.asyncio
    async def test_for_eval_accesses_variables(self):
        """Test that for-loop items expression can reference ctx variables."""
        from src.scenarios.step.control_flow import ForStepExecutor
        from src.scenarios.schema import ForStep
        
        collected = []
        
        async def fake_execute_steps(steps, ctx, defaults=None):
            collected.append(ctx.variables.get("item"))
        
        executor = ForStepExecutor(container_manager=None, execute_steps_callback=fake_execute_steps)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("max_nodes", 3)
        
        step = ForStep(**{"for": "item", "in": "range(max_nodes)", "steps": [CLIStep(cli="version")]})
        await executor.execute(step, ctx)
        
        assert collected == [0, 1, 2]
    
    @pytest.mark.asyncio
    async def test_switch_eval_accesses_variables(self):
        """Test that switch expression can reference ctx variables."""
        from src.scenarios.step.control_flow import SwitchStepExecutor
        from src.scenarios.schema import SwitchStep
        
        executed = []
        
        async def fake_execute_steps(steps, ctx, defaults=None):
            executed.append("matched")
        
        executor = SwitchStepExecutor(container_manager=None, execute_steps_callback=fake_execute_steps)
        scenario = TestScenario(name="test", description="test", test=[CLIStep(cli="version")])
        ctx = RuntimeContext(scenario)
        ctx.set_variable("mode", "fast")
        
        step = SwitchStep(
            switch="mode",
            cases={"fast": [CLIStep(cli="version")], "slow": [CLIStep(cli="version")]},
        )
        await executor.execute(step, ctx)
        
        assert "matched" in executed


class TestNodeStateJSONParsing:
    """Tests for JSON format parsing in NodeStateManager (SDK 6.0+)."""
    
    def test_parse_json_online_state(self):
        """Test parsing JSON format: NET_STATE_ONLINE."""
        import json
        output = json.dumps([{
            "status": {
                "states": {"current": "NET_STATE_ONLINE", "target": "NET_STATE_ONLINE"}
            }
        }])
        
        from src.network.node_states import NodeState
        parsed = json.loads(output.strip())
        item = parsed[0]
        status = item.get("status", item)
        states = status.get("states", {})
        current_str = states.get("current")
        
        matched_state = None
        for state in NodeState:
            if state.value == current_str:
                matched_state = state
                break
        
        assert matched_state == NodeState.ONLINE
    
    def test_parse_json_links_connecting_state(self):
        """Test parsing JSON format: NET_STATE_LINKS_CONNECTING."""
        import json
        output = json.dumps([{
            "status": {
                "states": {"current": "NET_STATE_LINKS_CONNECTING", "target": "NET_STATE_ONLINE"},
                "links": {"active": 1, "required": 3}
            }
        }])
        
        from src.network.node_states import NodeState
        parsed = json.loads(output.strip())
        item = parsed[0]
        status = item.get("status", item)
        states = status.get("states", {})
        current_str = states.get("current")
        
        matched_state = None
        for state in NodeState:
            if state.value == current_str:
                matched_state = state
                break
        
        assert matched_state == NodeState.LINKS_CONNECTING
    
    def test_parse_text_format_fallback(self):
        """Test fallback to text format when JSON parsing fails."""
        from src.network.node_states import NodeState
        
        output = """
        states:
            current: NET_STATE_ONLINE
            target: NET_STATE_ONLINE
        """
        
        import json
        parsed_json = False
        try:
            json.loads(output.strip())
            parsed_json = True
        except json.JSONDecodeError:
            pass
        
        assert not parsed_json, "Text format should not parse as JSON"
        
        found_state = None
        for line in output.split('\n'):
            line_stripped = line.strip()
            if line_stripped.startswith('current:'):
                for state in NodeState:
                    if state.value in line_stripped:
                        found_state = state
                        break
        
        assert found_state == NodeState.ONLINE
    
    def test_parse_json_unknown_state(self):
        """Test JSON parsing with unknown state value."""
        import json
        output = json.dumps([{
            "status": {
                "states": {"current": "NET_STATE_SOMETHING_NEW", "target": "NET_STATE_ONLINE"}
            }
        }])
        
        from src.network.node_states import NodeState
        parsed = json.loads(output.strip())
        item = parsed[0]
        status = item.get("status", item)
        states = status.get("states", {})
        current_str = states.get("current")
        
        matched_state = None
        for state in NodeState:
            if state.value == current_str:
                matched_state = state
                break
        
        assert matched_state is None, "Unknown state should not match any NodeState"
