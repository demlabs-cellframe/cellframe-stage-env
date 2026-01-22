"""Unit tests for scenario parser and schema."""

import pytest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.parser import ScenarioParser, ScenarioParseError
from src.scenarios.schema import ScenarioDefinition as ScenarioSchema, CLIStep

class TestScenarioParser:
    """Test scenario parser logic."""
    
    @pytest.fixture
    def parser(self, tmp_path):
        """Create ScenarioParser instance."""
        return ScenarioParser(tmp_path)
    
    def test_load_scenario_valid(self, parser, tmp_path):
        """Test loading a valid scenario."""
        scenario_file = tmp_path / "valid.yml"
        scenario_file.write_text("""
        name: Valid Scenario
        description: Test description
        test:
          steps:
            - cli: version
              node: node1
        """)
        
        scenario = parser.load_scenario("valid.yml")
        
        assert isinstance(scenario, ScenarioSchema)
        assert scenario.name == "Valid Scenario"
        assert len(scenario.test.steps) == 1
        assert isinstance(scenario.test.steps[0], CLIStep)
        assert scenario.test.steps[0].cli == "version"

    def test_load_scenario_invalid_yaml(self, parser, tmp_path):
        """Test loading invalid YAML."""
        scenario_file = tmp_path / "invalid.yml"
        scenario_file.write_text("""
        name: Invalid
        description: : : : invalid yaml
        """)
        
        with pytest.raises(ScenarioParseError) as excinfo:
            parser.load_scenario("invalid.yml")
        
        assert "YAML parse error" in str(excinfo.value)

    def test_load_scenario_validation_error(self, parser, tmp_path):
        """Test loading scenario with schema validation errors."""
        scenario_file = tmp_path / "schema_error.yml"
        # Missing required 'test' field
        scenario_file.write_text("""
        name: Schema Error
        description: Missing test section
        """)
        
        with pytest.raises(ScenarioParseError) as excinfo:
            parser.load_scenario("schema_error.yml")
        
        assert "Validation error" in str(excinfo.value)
        assert "Field required" in str(excinfo.value)

    def test_substitute_variables_simple(self, parser):
        """Test simple variable substitution."""
        variables = {"var1": "value1", "var2": "value2"}
        text = "Test {{var1}} and {{var2}}"
        
        result = parser.substitute_variables(text, variables)
        assert result == "Test value1 and value2"

    def test_substitute_variables_list_index(self, parser):
        """Test list indexing substitution."""
        variables = {"list": ["item0", "item1"]}
        text = "Item: {{list[1]}}"
        
        result = parser.substitute_variables(text, variables)
        assert result == "Item: item1"

    def test_substitute_variables_dict_key(self, parser):
        """Test dictionary key substitution."""
        variables = {"map": {"key": "value"}}
        text = "Value: {{map['key']}}"
        
        result = parser.substitute_variables(text, variables)
        assert result == "Value: value"
    
    def test_substitute_variables_dict_dot(self, parser):
        """Test dictionary dot notation substitution."""
        variables = {"map": {"key": "value"}}
        text = "Value: {{map.key}}"
        
        result = parser.substitute_variables(text, variables)
        assert result == "Value: value"

    def test_substitute_variables_undefined(self, parser):
        """Test error on undefined variable."""
        variables = {}
        text = "Test {{undefined}}"
        
        with pytest.raises(ScenarioParseError) as excinfo:
            parser.substitute_variables(text, variables)
        
        assert "Undefined variable: undefined" in str(excinfo.value)

    def test_process_includes(self, parser, tmp_path):
        """Test include processing."""
        # Main file
        main_file = tmp_path / "main.yml"
        
        # Included file
        include_file = tmp_path / "included.yml"
        include_file.write_text("""
        variables:
          included_var: value
        defaults:
          node: node2
        """)
        
        data = {
            "includes": ["included.yml"],
            "name": "Main",
            "description": "Desc",
            "test": [{"cli": "cmd"}]
        }
        
        # Mock _load_yaml_file to return dicts without parsing actual files recursively for main
        # But we need to let it load the included file
        
        # Easier approach: write main file too and use public load_scenario logic 
        # but that tests validation too. Let's unit test _process_includes directly.
        
        result = parser._process_includes(data, tmp_path)
        
        assert result["variables"]["included_var"] == "value"
        assert result["defaults"]["node"] == "node2"

