"""Integration tests for scenario orchestration (mocked execution)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import ScenarioExecutor, RuntimeContext
from src.scenarios.parser import ScenarioParser
from src.scenarios.schema import TestScenario

@pytest.fixture
def mock_container_manager():
    """Mock DockerContainerManager for happy path."""
    manager = MagicMock()
    
    # Mock CLI execution
    async def mock_exec(command, node, timeout=30):
        # Default success response
        response = {
            "returncode": 0,
            "stdout": "Success",
            "stderr": ""
        }
        
        # Simulate specific command outputs if needed
        if "wallet info" in command:
            response["stdout"] = "Wallet info: 0x123... balance: 100"
        elif "tx_create" in command:
            response["stdout"] = "Transaction created: 0xABCDEF..."
        elif "node dump" in command:
            response["stdout"] = "Node info..."
            
        return response
    
    manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
    
    # Mock container resolution
    manager.resolve_node_to_container.side_effect = lambda n: f"cellframe-node-{n}"
    
    # Mock docker client
    manager.docker_client = MagicMock()
    manager.docker_client.containers.list.return_value = []
    
    return manager

@pytest.fixture
def scenario_executor(mock_container_manager):
    """Create ScenarioExecutor with mocked container manager."""
    executor = ScenarioExecutor()
    executor.container_manager = mock_container_manager
    # Inject into sub-executors
    executor.cli_executor.container_manager = mock_container_manager
    executor.wait_executor.container_manager = mock_container_manager
    return executor

class TestScenarioOrchestration:
    """Test scenario orchestration."""
    
    @pytest.mark.asyncio
    async def test_execute_simple_scenario(self, scenario_executor, tmp_path):
        """Test executing a simple scenario from YAML."""
        # Create scenario file
        scenario_path = tmp_path / "simple_test.yml"
        scenario_path.write_text("""
        name: Simple Test
        description: Integration test
        variables:
          wallet_name: test_wallet
        test:
          steps:
            - cli: wallet info -w {{wallet_name}}
              node: node1
              expect: success
            - cli: version
              node: node1
        """)
        
        # Load scenario
        parser = ScenarioParser(tmp_path)
        scenario = parser.load_scenario("simple_test.yml")
        
        # Execute
        ctx = await scenario_executor.execute_scenario(scenario)
        
        # Verify results
        assert ctx.get_summary()["passed"] == 2
        assert ctx.get_summary()["failed"] == 0
        
        # Verify CLI calls
        assert scenario_executor.container_manager.exec_cli_command.call_count == 2
        
        # Verify variable substitution in calls
        # First call should have substituted wallet name
        calls = scenario_executor.container_manager.exec_cli_command.call_args_list
        assert "wallet info -w test_wallet" in str(calls[0])

    @pytest.mark.asyncio
    async def test_execute_scenario_with_defaults(self, scenario_executor, tmp_path):
        """Test executing scenario with defaults."""
        scenario_path = tmp_path / "defaults_test.yml"
        scenario_path.write_text("""
        name: Defaults Test
        description: Test defaults
        defaults:
          node: node2
          cli:
            net: stagenet
        test:
          steps:
            - cli: wallet info
              # Should inherit node2 and -net stagenet
        """)
        
        # Mock CLI parser needed for CLI defaults
        with patch("src.utils.cli_parser.get_cli_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.apply_cli_defaults.return_value = "wallet info -net stagenet"
            mock_parser._parsed = True
            mock_get_parser.return_value = mock_parser
            
            parser = ScenarioParser(tmp_path)
            scenario = parser.load_scenario("defaults_test.yml")
            
            ctx = await scenario_executor.execute_scenario(scenario)
            
            assert ctx.get_summary()["passed"] == 1
            
            # Verify call
            scenario_executor.container_manager.exec_cli_command.assert_called_with(
                command="wallet info -net stagenet",
                node="node2",
                timeout=30
            )

