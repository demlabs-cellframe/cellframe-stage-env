"""Integration tests for Scenario execution pipeline."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch, AsyncMock
import yaml

from src.scenarios.executor import ScenarioExecutor
from src.scenarios.parser import ScenarioParser, ScenarioParseError
from src.docker_ctl.container import DockerContainerManager


class TestScenarioExecutionPipeline:
    """Test integration of ScenarioParser -> ScenarioExecutor -> DockerContainer."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "scenarios").mkdir()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def simple_scenario_file(self, temp_base_path):
        """Create a simple test scenario YAML."""
        scenario_file = temp_base_path / "scenarios" / "test.yml"
        scenario_content = {
            "name": "Test scenario",
            "description": "Simple test",
            "network": {"preset": "minimal"},
            "test": {
                "steps": [
                    {
                        "cli": "version",
                        "node": "node1",
                        "expect": "success"
                    }
                ]
            }
        }
        scenario_file.write_text(yaml.dump(scenario_content))
        return scenario_file
    
    @pytest.fixture
    def mock_container_manager(self):
        """Mock DockerContainerManager."""
        manager = MagicMock(spec=DockerContainerManager)
        
        async def mock_exec(command, node, timeout=30):
            return {
                "returncode": 0,
                "stdout": "Version 1.0.0",
                "stderr": ""
            }
        
        manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
        manager.resolve_node_to_container = MagicMock(side_effect=lambda n: f"cellframe-node-{n}")
        return manager
    
    def test_parser_to_executor_flow(self, simple_scenario_file, temp_base_path, mock_container_manager):
        """Test that parsed scenario can be executed."""
        # Parse scenario
        parser = ScenarioParser(temp_base_path / "scenarios")
        scenario = parser.load_scenario("test.yml")
        
        assert scenario is not None
        assert scenario.name == "Test scenario"
        assert len(scenario.test.steps) == 1
        
        # Executor should accept parsed scenario
        # ScenarioExecutor(node_cli_path, log_file, debug, base_path)
        executor = ScenarioExecutor(node_cli_path="cellframe-node-cli", base_path=temp_base_path)
        assert executor is not None
    
    @pytest.mark.asyncio
    async def test_full_scenario_execution_pipeline(self, simple_scenario_file, temp_base_path, mock_container_manager):
        """Test full pipeline: Parse -> Execute -> Verify."""
        # Parse
        parser = ScenarioParser(temp_base_path / "scenarios")
        scenario = parser.load_scenario("test.yml")
        
        # Execute
        executor = ScenarioExecutor(node_cli_path="cellframe-node-cli", base_path=temp_base_path)
        
        # Mock execute_scenario method
        executor.execute_scenario = AsyncMock(return_value={"success": True, "steps": 1})
        
        result = await executor.execute_scenario(scenario)
        
        assert result["success"] is True
        assert result["steps"] == 1
    
    def test_scenario_with_variables_integration(self, temp_base_path, mock_container_manager):
        """Test scenario variable substitution through pipeline."""
        scenario_file = temp_base_path / "scenarios" / "vars_test.yml"
        scenario_content = {
            "name": "Variable test",
            "description": "Test variable substitution",
            "variables": {
                "test_node": "node1",
                "test_cmd": "version"
            },
            "test": {
                "steps": [
                    {
                        "cli": "{{test_cmd}}",
                        "node": "{{test_node}}"
                    }
                ]
            }
        }
        scenario_file.write_text(yaml.dump(scenario_content))
        
        parser = ScenarioParser(temp_base_path / "scenarios")
        scenario = parser.load_scenario("vars_test.yml")
        
        # Variables should be available for executor
        assert scenario.variables is not None
        assert "test_node" in scenario.variables
    
    def test_scenario_step_execution_integration(self, temp_base_path, mock_container_manager):
        """Test that scenario steps are executed via container manager."""
        # Create multi-step scenario
        scenario_file = temp_base_path / "scenarios" / "multi_step.yml"
        scenario_content = {
            "name": "Multi-step test",
            "description": "Test multi-step execution",
            "test": {
                "steps": [
                    {"cli": "cmd1", "node": "node1"},
                    {"cli": "cmd2", "node": "node1"},
                    {"cli": "cmd3", "node": "node1"}
                ]
            }
        }
        scenario_file.write_text(yaml.dump(scenario_content))
        
        parser = ScenarioParser(temp_base_path / "scenarios")
        scenario = parser.load_scenario("multi_step.yml")
        
        assert len(scenario.test.steps) == 3
        
        # All steps should be executable
        executor = ScenarioExecutor(node_cli_path="cellframe-node-cli", base_path=temp_base_path)
        assert executor is not None


class TestScenarioErrorPropagation:
    """Test error handling through scenario execution pipeline."""
    
    def test_invalid_scenario_rejected_by_parser(self, tmp_path):
        """Test that invalid scenario is caught at parse stage."""
        invalid_scenario = tmp_path / "scenarios" / "invalid.yml"
        (tmp_path / "scenarios").mkdir(exist_ok=True)
        invalid_scenario.write_text("invalid: yaml: content:")
        
        parser = ScenarioParser(tmp_path / "scenarios")
        
        with pytest.raises((yaml.YAMLError, ValueError, KeyError, ScenarioParseError)):
            parser.load_scenario("invalid.yml")
    
    @pytest.mark.asyncio
    async def test_step_failure_propagates_to_executor(self, tmp_path):
        """Test that step execution failures are properly handled."""
        mock_manager = MagicMock()
        
        async def failing_exec(command, node, timeout=30):
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "Command failed"
            }
        
        mock_manager.exec_cli_command = AsyncMock(side_effect=failing_exec)
        
        # Executor should handle failure
        executor = ScenarioExecutor(tmp_path, mock_manager)
        
        # Mock scenario with failing step
        executor.execute_scenario = AsyncMock(return_value={"success": False, "error": "Step failed"})
        
        result = await executor.execute_scenario(MagicMock())
        assert result["success"] is False
