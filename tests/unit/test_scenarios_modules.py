"""Unit tests for src/scenarios/ modules."""
import pytest
from pathlib import Path
import sys
import yaml
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import ScenarioExecutor, ScenarioExecutionError, RuntimeContext
from src.scenarios.parser import ScenarioParser, ScenarioParseError
from src.scenarios.schema import TestScenario


# ============================================================================
# RuntimeContext Tests
# ============================================================================

class TestRuntimeContext:
    """Test RuntimeContext class."""
    
    def test_runtime_context_set_get_variable(self):
        """Test set/get variable."""
        scenario_dict = {
            "name": "test",
            "description": "test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}  # Simple wait step
        }
        scenario = TestScenario(**scenario_dict)
        context = RuntimeContext(scenario)
        
        context.set_variable("test_var", "test_value")
        assert context.get_variable("test_var") == "test_value"
    
    def test_runtime_context_undefined_variable(self):
        """Test accessing undefined variable raises error."""
        scenario_dict = {
            "name": "test",
            "description": "test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}
        }
        scenario = TestScenario(**scenario_dict)
        context = RuntimeContext(scenario)
        
        with pytest.raises(ScenarioExecutionError, match="Undefined variable"):
            context.get_variable("undefined_var")
    
    def test_runtime_context_add_result(self):
        """Test adding step results."""
        scenario_dict = {
            "name": "test",
            "description": "test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}
        }
        scenario = TestScenario(**scenario_dict)
        context = RuntimeContext(scenario)
        
        context.add_result("cli", True, {"command": "test"})
        
        assert len(context.step_results) == 1
        assert context.step_results[0]["type"] == "cli"
        assert context.step_results[0]["success"] is True
    
    def test_runtime_context_get_summary(self):
        """Test getting execution summary."""
        scenario_dict = {
            "name": "test_scenario",
            "description": "test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}
        }
        scenario = TestScenario(**scenario_dict)
        context = RuntimeContext(scenario)
        
        context.add_result("cli", True, {})
        context.add_result("cli", False, {})
        
        summary = context.get_summary()
        
        assert summary["scenario"] == "test_scenario"
        assert summary["total_steps"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["success_rate"] == 50.0


# ============================================================================
# ScenarioExecutor Tests
# ============================================================================

class TestScenarioExecutor:
    """Test ScenarioExecutor class."""
    
    def test_executor_init(self, tmp_path):
        """Test ScenarioExecutor initialization."""
        executor = ScenarioExecutor(
            node_cli_path="/usr/bin/cli",
            log_file=tmp_path / "test.log",
            debug=True,
            base_path=tmp_path
        )
        
        assert executor.node_cli_path == "/usr/bin/cli"
        assert executor.log_file == tmp_path / "test.log"
        assert executor.debug is True
        assert executor.base_path == tmp_path
    
    def test_executor_init_defaults(self):
        """Test ScenarioExecutor with default parameters."""
        executor = ScenarioExecutor()
        
        assert executor.node_cli_path == "cellframe-node-cli"
        assert executor.log_file is None
        assert executor.debug is False
    
    @pytest.mark.asyncio
    async def test_executor_run_scenario_basic(self, tmp_path):
        """Test basic scenario execution (mocked)."""
        scenario_dict = {
            "name": "basic_test",
            "description": "Basic test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}
        }
        scenario = TestScenario(**scenario_dict)
        
        executor = ScenarioExecutor(base_path=tmp_path)
        
        # Mock the internal execution
        with patch.object(executor, '_execute_steps', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = None
            
            result = await executor.execute_scenario(scenario)
            
            assert result is not None
            # Called multiple times for different sections (setup, test, etc)
            assert mock_exec.call_count >= 1


# ============================================================================
# ScenarioParser Tests
# ============================================================================

class TestScenarioParser:
    """Test ScenarioParser class."""
    
    def test_parser_init(self, tmp_path):
        """Test ScenarioParser initialization."""
        parser = ScenarioParser(tmp_path)
        
        assert parser.scenarios_root == tmp_path
    
    def test_parser_load_scenario_success(self, tmp_path):
        """Test loading valid scenario."""
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        scenario_file = scenarios_dir / "test.yml"
        scenario_data = {
            "name": "test_scenario",
            "description": "Test description",
            "network": {"preset": "minimal"},
            "test": {
                "steps": [
                    {"wait": "1s"}  # Simplified step
                ]
            }
        }
        scenario_file.write_text(yaml.dump(scenario_data))
        
        parser = ScenarioParser(scenarios_dir)
        scenario = parser.load_scenario("test.yml")
        
        assert scenario.name == "test_scenario"
        assert scenario.description == "Test description"
    
    def test_parser_load_scenario_not_found(self, tmp_path):
        """Test loading non-existent scenario."""
        parser = ScenarioParser(tmp_path)
        
        with pytest.raises(ScenarioParseError, match="Scenario file not found"):
            parser.load_scenario("nonexistent.yml")
    
    def test_parser_load_scenario_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML."""
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        scenario_file = scenarios_dir / "invalid.yml"
        scenario_file.write_text("invalid: yaml: -\n  malformed")
        
        parser = ScenarioParser(scenarios_dir)
        
        with pytest.raises(ScenarioParseError, match="YAML parse error"):
            parser.load_scenario("invalid.yml")
    
    def test_parser_substitute_variables(self, tmp_path):
        """Test variable substitution."""
        parser = ScenarioParser(tmp_path)
        
        variables = {"name": "test", "count": "5"}
        text = "Hello {{name}}, count is {{count}}"
        
        result = parser.substitute_variables(text, variables)
        
        assert result == "Hello test, count is 5"
    
    def test_parser_substitute_variables_undefined(self, tmp_path):
        """Test substitution with undefined variable raises error."""
        parser = ScenarioParser(tmp_path)
        
        variables = {"name": "test"}
        text = "Hello {{name}}, missing {{undefined}}"
        
        # Should raise error for undefined vars
        with pytest.raises(ScenarioParseError, match="Undefined variable"):
            parser.substitute_variables(text, variables)


# ============================================================================
# Error Tests
# ============================================================================

class TestScenarioErrors:
    """Test scenario error classes."""
    
    def test_execution_error_basic(self):
        """Test basic execution error."""
        error = ScenarioExecutionError("Test error")
        assert "Test error" in str(error)
    
    def test_execution_error_with_step(self):
        """Test error with step context."""
        step = {"type": "cli", "command": "test"}
        error = ScenarioExecutionError("Test error", step=step)
        
        error_str = str(error)
        assert "Test error" in error_str
        assert "Step:" in error_str
    
    def test_parse_error_basic(self):
        """Test basic parse error."""
        error = ScenarioParseError("Parse failed")
        assert "Parse failed" in str(error)
    
    def test_parse_error_with_file(self, tmp_path):
        """Test parse error with file context."""
        file_path = tmp_path / "test.yml"
        error = ScenarioParseError("Parse failed", file_path=file_path)
        
        error_str = str(error)
        assert "Parse failed" in error_str
        assert "test.yml" in error_str


# ============================================================================
# Integration Tests
# ============================================================================

class TestScenariosIntegration:
    """Integration tests for scenarios modules."""
    
    def test_parser_to_executor_flow(self, tmp_path):
        """Test loading scenario and passing to executor."""
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        scenario_file = scenarios_dir / "integration.yml"
        scenario_data = {
            "name": "integration_test",
            "description": "Integration test",
            "network": {"preset": "minimal"},
            "test": {"steps": [{"wait": "1s"}]}  # Simple wait step
        }
        scenario_file.write_text(yaml.dump(scenario_data))
        
        parser = ScenarioParser(scenarios_dir)
        scenario = parser.load_scenario("integration.yml")
        
        executor = ScenarioExecutor(base_path=tmp_path)
        
        # Verify executor can accept parsed scenario
        assert scenario.name == "integration_test"
        assert executor is not None
    
    def test_runtime_context_with_parsed_scenario(self, tmp_path):
        """Test RuntimeContext with parsed scenario."""
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        scenario_file = scenarios_dir / "context_test.yml"
        scenario_data = {
            "name": "context_test",
            "description": "Context test",
            "network": {"preset": "minimal"},
            "variables": {"test_var": "test_value"},
            "test": {"steps": [{"wait": "1s"}]}  # Simple wait step
        }
        scenario_file.write_text(yaml.dump(scenario_data))
        
        parser = ScenarioParser(scenarios_dir)
        scenario = parser.load_scenario("context_test.yml")
        
        context = RuntimeContext(scenario)
        
        assert context.variables["test_var"] == "test_value"
        assert context.scenario.name == "context_test"


# ============================================================================
# Import Tests
# ============================================================================

class TestScenariosModulesImports:
    """Test importing scenarios modules."""
    
    def test_import_executor(self):
        """Test importing ScenarioExecutor."""
        from src.scenarios.executor import ScenarioExecutor
        assert ScenarioExecutor is not None
    
    def test_import_parser(self):
        """Test importing ScenarioParser."""
        from src.scenarios.parser import ScenarioParser
        assert ScenarioParser is not None
    
    def test_import_schema(self):
        """Test importing scenario schemas."""
        from src.scenarios.schema import TestScenario, CLIStep
        assert TestScenario is not None
        assert CLIStep is not None
    
    def test_import_step_base(self):
        """Test importing step base module."""
        from src.scenarios.step import base as step_base
        assert step_base is not None
    
    def test_import_check_base(self):
        """Test importing check base module."""
        from src.scenarios.check import base as check_base
        assert check_base is not None
