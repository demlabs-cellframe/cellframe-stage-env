"""Unit tests for scenario executor."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.executor import ScenarioExecutor, RuntimeContext, ScenarioExecutionError
from src.scenarios.schema import CLIStep, StepDefaults, TestScenario as ScenarioSchema


class TestNodeAliasResolution:
    """Test node alias resolution logic."""
    
    def test_resolve_simple_node_id(self):
        """Test resolving node1 -> node1."""
        executor = ScenarioExecutor()
        assert executor._resolve_node_alias("node1") == "node1"
        assert executor._resolve_node_alias("node99") == "node99"
        
    def test_resolve_dashed_node_id(self):
        """Test resolving node-1 -> node1."""
        executor = ScenarioExecutor()
        assert executor._resolve_node_alias("node-1") == "node1"
        assert executor._resolve_node_alias("node-5") == "node5"


class TestYAMLErrorDetection:
    """Test YAML error detection in CLI responses."""
    
    def test_detect_yaml_error_dict(self, sample_yaml_error):
        """Test detection of YAML error with dict format."""
        executor = ScenarioExecutor()
        
        result = {
            "returncode": 0,
            "stdout": sample_yaml_error,
            "stderr": ""
        }
        
        success = executor._check_expectation(result, "success", None)
        
        assert success is False, "Should detect YAML error"
    
    def test_detect_yaml_success(self, sample_yaml_success):
        """Test that valid YAML response is accepted."""
        executor = ScenarioExecutor()
        
        result = {
            "returncode": 0,
            "stdout": sample_yaml_success,
            "stderr": ""
        }
        
        success = executor._check_expectation(result, "success", None)
        
        assert success is True, "Should accept valid YAML"
    
    def test_expect_error_with_yaml_error(self, sample_yaml_error):
        """Test that expect=error works with YAML errors."""
        executor = ScenarioExecutor()
        
        result = {
            "returncode": 0,
            "stdout": sample_yaml_error,
            "stderr": ""
        }
        
        success = executor._check_expectation(result, "error", None)
        
        assert success is True, "Should match expected error"


class TestHashExtraction:
    """Test hash extraction from CLI output."""
    
    @pytest.fixture
    def executor(self):
        """Create executor instance."""
        return ScenarioExecutor()
    
    def test_extract_hash_regex_fallback(self, executor):
        """Test regex fallback for hash extraction."""
        import re
        
        output = "Transaction created: 0xABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890"
        
        hash_pattern = r'0x[0-9a-fA-F]{64,}'
        match = re.search(hash_pattern, output)
        
        assert match is not None
        assert match.group(0).startswith("0x")


class TestCLIDefaultsApplication:
    """Test application of CLI defaults to commands."""
    
    def test_defaults_merge_hierarchy(self):
        """Test hierarchical defaults merging (global > section > group)."""
        executor = ScenarioExecutor()
        
        global_defaults = StepDefaults(node="node1", cli={"net": "stagenet"})
        section_defaults = StepDefaults(wait="5s")
        
        merged = executor._merge_defaults(global_defaults, section_defaults)
        
        assert merged is not None
        assert merged.node == "node1"
        assert merged.wait == "5s"
        assert merged.cli == {"net": "stagenet"}

    def test_apply_defaults_to_step(self):
        """Test applying defaults to a step."""
        executor = ScenarioExecutor()
        defaults = StepDefaults(node="node2", timeout=60)
        
        # Step with default values
        step = CLIStep(cli="version", node="node1", timeout=30)
        
        updated_step = executor._apply_defaults(step, defaults)
        
        # Should be updated because they match default values
        assert updated_step.node == "node2"
        assert updated_step.timeout == 60
        
    def test_apply_defaults_does_not_override_custom(self):
        """Test that explicit values are not overridden by defaults."""
        executor = ScenarioExecutor()
        defaults = StepDefaults(node="node2", timeout=60)
        
        # Step with custom values
        step = CLIStep(cli="version", node="node3", timeout=10)
        
        updated_step = executor._apply_defaults(step, defaults)
        
        # Should NOT be updated
        assert updated_step.node == "node3"
        assert updated_step.timeout == 10


class TestDatumMonitorIntegration:
    """Test datum monitor behavior with invalid hashes."""
    
    @pytest.mark.asyncio
    async def test_invalid_hash_rejected_immediately(self):
        """Test that invalid hash is rejected without monitoring."""
        from src.monitoring.datum import DatumMonitor, DatumStatus
        
        monitor = DatumMonitor()
        
        # Try to track obviously invalid hash
        invalid_hash = "errors: code: 102"
        
        result = await monitor.wait_for_datum(
            datum_hash=invalid_hash,
            node="node1",
            network="stagenet"
        )
        
        assert result.status == DatumStatus.REJECTED
        assert "Invalid datum hash format" in result.error_message
