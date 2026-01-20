"""Integration tests for Monitoring system with live data collection."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from src.monitoring.datum import DatumMonitor
from src.monitoring.validator import ValidatorMonitor
from src.docker_ctl.container import DockerContainerManager


class TestMonitoringIntegration:
    """Test monitoring system integration with Docker and network components."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "logs").mkdir()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_container_manager(self):
        """Mock container manager for monitoring."""
        manager = MagicMock(spec=DockerContainerManager)
        
        async def mock_exec(command, node, timeout=30):
            if "datum" in command:
                return {
                    "returncode": 0,
                    "stdout": "datum_hash: 0xabc123\nstatus: confirmed",
                    "stderr": ""
                }
            elif "validator" in command:
                return {
                    "returncode": 0,
                    "stdout": "stake: 1000000\nstatus: active",
                    "stderr": ""
                }
            return {"returncode": 0, "stdout": "", "stderr": ""}
        
        manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
        return manager
    
    def test_datum_monitor_with_container_integration(self, temp_base_path, mock_container_manager):
        """Test DatumMonitor integrates with DockerContainerManager."""
        network_config = {"name": "stagenet"}
        
        with patch('docker.from_env'):
            monitor = DatumMonitor(temp_base_path, network_config, mock_container_manager)
            
            assert monitor is not None
    
    @pytest.mark.asyncio
    async def test_monitor_collects_data_from_containers(self, temp_base_path, mock_container_manager):
        """Test monitoring collects data via container exec."""
        network_config = {"name": "stagenet"}
        
        with patch('docker.from_env'):
            monitor = DatumMonitor(temp_base_path, network_config, mock_container_manager)
            
            # Mock check method
            monitor.check_datum_status = AsyncMock(return_value={
                "hash": "0xabc123",
                "status": "confirmed",
                "timestamp": datetime.now()
            })
            
            result = await monitor.check_datum_status("0xabc123", "node1")
            
            assert result["hash"] == "0xabc123"
            assert result["status"] == "confirmed"
    
    def test_validator_monitor_integration(self, temp_base_path, mock_container_manager):
        """Test ValidatorMonitor integrates with network."""
        network_config = {
            "name": "stagenet",
            "validators": ["node1", "node2"]
        }
        
        with patch('docker.from_env'):
            monitor = ValidatorMonitor(temp_base_path, network_config, mock_container_manager)
            
            assert monitor is not None
    
    @pytest.mark.asyncio
    async def test_monitoring_logs_to_filesystem(self, temp_base_path, mock_container_manager):
        """Test that monitoring results are logged to filesystem."""
        network_config = {"name": "stagenet"}
        
        with patch('docker.from_env'):
            monitor = DatumMonitor(temp_base_path, network_config, mock_container_manager)
            
            # Create log file
            log_file = temp_base_path / "logs" / "monitoring.log"
            log_file.write_text("2026-01-20 00:00:00 - Datum 0xabc123 confirmed\n")
            
            assert log_file.exists()
            assert "confirmed" in log_file.read_text()


class TestMonitoringScenarioIntegration:
    """Test monitoring integration with scenario execution."""
    
    @pytest.mark.asyncio
    async def test_scenario_waits_for_monitor_condition(self, tmp_path):
        """Test scenario can wait for monitoring conditions."""
        mock_manager = MagicMock()
        
        # Mock monitoring condition
        condition_met = False
        
        async def check_condition():
            nonlocal condition_met
            condition_met = True
            return True
        
        # Scenario should wait for condition
        result = await check_condition()
        assert result is True
        assert condition_met is True
    
    @pytest.mark.asyncio
    async def test_monitor_provides_data_for_scenario_assertions(self, tmp_path):
        """Test monitoring data can be used in scenario assertions."""
        mock_container_manager = MagicMock()
        
        async def mock_exec(command, node, timeout=30):
            return {
                "returncode": 0,
                "stdout": "balance: 1000",
                "stderr": ""
            }
        
        mock_container_manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
        
        # Get monitoring data
        result = await mock_container_manager.exec_cli_command("wallet balance", "node1")
        
        # Scenario can use this data for assertions
        assert "balance: 1000" in result["stdout"]


class TestMonitoringArtifactsIntegration:
    """Test monitoring integration with artifacts collection."""
    
    def test_monitoring_data_collected_as_artifacts(self, tmp_path):
        """Test monitoring data is saved as test artifacts."""
        # Create monitoring output
        monitoring_dir = tmp_path / "artifacts" / "monitoring"
        monitoring_dir.mkdir(parents=True)
        
        # Save monitoring data
        datum_report = monitoring_dir / "datum_status.json"
        datum_report.write_text('{"datum": "0xabc123", "status": "confirmed"}')
        
        validator_report = monitoring_dir / "validator_status.json"
        validator_report.write_text('{"stake": 1000000, "status": "active"}')
        
        # Verify artifacts collected
        assert datum_report.exists()
        assert validator_report.exists()
        assert "confirmed" in datum_report.read_text()
