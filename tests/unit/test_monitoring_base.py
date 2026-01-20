"""Unit tests for src/monitoring/ base modules."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, call
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ============================================================================
# DatumMonitor Tests
# ============================================================================

class TestDatumMonitor:
    """Test DatumMonitor class."""
    
    @patch('docker.from_env')
    def test_datum_monitor_init(self, mock_docker):
        """Test DatumMonitor initialization."""
        from src.monitoring.datum import DatumMonitor
        
        mock_docker.return_value = MagicMock()
        monitor = DatumMonitor(node_cli_path="test-cli")
        
        assert monitor.node_cli_path == "test-cli"
        assert monitor.docker_client is not None
        assert monitor._topology_map is None
        mock_docker.assert_called_once()
    
    @patch('docker.from_env')
    def test_datum_monitor_init_with_log_file(self, mock_docker, tmp_path):
        """Test DatumMonitor initialization with log file."""
        from src.monitoring.datum import DatumMonitor
        
        mock_docker.return_value = MagicMock()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        monitor = DatumMonitor(node_cli_path="test-cli", log_file=log_dir)
        
        assert monitor.log_file is not None
        assert monitor.log_file.parent.name == "health-logs"
        assert monitor.log_file.name == "datum-monitor.log"
    
    @patch('docker.from_env')
    def test_datum_monitor_log(self, mock_docker, tmp_path):
        """Test DatumMonitor logging."""
        from src.monitoring.datum import DatumMonitor
        
        mock_docker.return_value = MagicMock()
        log_file = tmp_path / "test.log"
        
        monitor = DatumMonitor(log_file=log_file)
        monitor._log("test message")
        
        assert monitor.log_file.exists()
        content = monitor.log_file.read_text()
        assert "DATUM_MONITOR" in content
        assert "test message" in content
    
    @patch('docker.from_env')
    def test_datum_monitor_result(self, mock_docker):
        """Test DatumMonitorResult dataclass."""
        from src.monitoring.datum import DatumMonitorResult
        from src.scenarios.schema import DatumStatus
        
        result = DatumMonitorResult(
            status=DatumStatus.SUCCESS,
            datum_hash="0x123abc",
            elapsed_time=1.5,
            details={"node": "node1"}
        )
        
        assert result.status == DatumStatus.SUCCESS
        assert result.datum_hash == "0x123abc"
        assert result.elapsed_time == 1.5
        assert result.details["node"] == "node1"
        assert result.error_message is None


# ============================================================================
# HealthChecker Tests
# ============================================================================

class TestHealthChecker:
    """Test HealthChecker class."""
    
    def test_health_checker_init(self):
        """Test HealthChecker initialization."""
        from src.monitoring.health import HealthChecker
        
        checker = HealthChecker(timeout=5.0)
        
        assert checker.timeout == 5.0
        assert checker._client is None  # Lazy initialization
    
    def test_health_checker_client_lazy_init(self):
        """Test HealthChecker client lazy initialization."""
        from src.monitoring.health import HealthChecker
        
        checker = HealthChecker()
        
        # Client should be None initially
        assert checker._client is None
        
        # Access client property to trigger lazy init
        client = checker.client
        
        assert client is not None
        assert checker._client is not None
    
    @pytest.mark.asyncio
    async def test_health_checker_check_http_success(self):
        """Test successful HTTP health check."""
        from src.monitoring.health import HealthChecker, HealthStatus
        
        checker = HealthChecker()
        
        # Mock the client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get = AsyncMock(return_value=mock_response)
        
        # Set _client directly to avoid property issues
        checker._client = mock_client
        
        result = await checker.check_http("http://test:8000", "node1")
        
        assert isinstance(result, HealthStatus)
        assert result.node_id == "node1"
        assert result.healthy is True
        assert result.response_time_ms > 0
        mock_client.get.assert_called_once_with("http://test:8000")
    
    @pytest.mark.asyncio
    async def test_health_checker_check_http_failure(self):
        """Test failed HTTP health check."""
        from src.monitoring.health import HealthChecker, HealthStatus
        
        checker = HealthChecker()
        
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection failed"))
        checker._client = mock_client
        
        result = await checker.check_http("http://test:8000", "node1")
        
        assert isinstance(result, HealthStatus)
        assert result.node_id == "node1"
        assert result.healthy is False
        assert result.error is not None
        assert "Connection failed" in result.error
    
    @pytest.mark.asyncio
    async def test_health_checker_check_rpc_success(self):
        """Test successful RPC health check."""
        from src.monitoring.health import HealthChecker, HealthStatus
        
        checker = HealthChecker()
        
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post = AsyncMock(return_value=mock_response)
        checker._client = mock_client
        
        result = await checker.check_json_rpc("http://test:8080/rpc", "node1")
        
        assert isinstance(result, HealthStatus)
        assert result.node_id == "node1"
        assert result.healthy is True
    
    @pytest.mark.asyncio
    async def test_health_checker_check_rpc_invalid_response(self):
        """Test RPC health check with invalid response."""
        from src.monitoring.health import HealthChecker, HealthStatus
        
        checker = HealthChecker()
        
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.post = AsyncMock(return_value=mock_response)
        checker._client = mock_client
        
        result = await checker.check_json_rpc("http://test:8080/rpc", "node1")
        
        assert result.healthy is False
    
    def test_health_status_model(self):
        """Test HealthStatus Pydantic model."""
        from src.monitoring.health import HealthStatus
        
        status = HealthStatus(
            node_id="node1",
            healthy=True,
            response_time_ms=123.45,
            details={"test": "data"}
        )
        
        assert status.node_id == "node1"
        assert status.healthy is True
        assert status.response_time_ms == 123.45
        assert status.error is None
        assert status.details["test"] == "data"


# ============================================================================
# MonitoringManager Tests
# ============================================================================

class TestMonitoringManager:
    """Test MonitoringManager class."""
    
    def test_monitoring_manager_init(self, tmp_path):
        """Test MonitoringManager initialization."""
        from src.monitoring.manager import MonitoringManager
        
        log_file = tmp_path / "monitor.log"
        
        with patch('docker.from_env'):
            manager = MonitoringManager(
                node_cli_path="test-cli",
                log_file=log_file
            )
        
            assert manager.node_cli_path == "test-cli"
            assert manager.log_file == log_file
            assert manager.datum is not None
            assert manager.health is not None
    
    def test_monitoring_manager_singleton(self, tmp_path):
        """Test MonitoringManager singleton pattern."""
        from src.monitoring.manager import MonitoringManager
        
        # Reset singleton
        MonitoringManager.reset_instance()
        
        with patch('docker.from_env'):
            # First call creates instance
            manager1 = MonitoringManager.get_instance(node_cli_path="cli1")
            
            # Second call returns same instance
            manager2 = MonitoringManager.get_instance(node_cli_path="cli2")
            
            assert manager1 is manager2
            assert manager1.node_cli_path == "cli1"  # Uses first call params
        
        # Cleanup
        MonitoringManager.reset_instance()
    
    def test_monitoring_manager_reset_instance(self):
        """Test MonitoringManager.reset_instance()."""
        from src.monitoring.manager import MonitoringManager
        
        with patch('docker.from_env'):
            # Create instance
            manager1 = MonitoringManager.get_instance()
            
            # Reset
            MonitoringManager.reset_instance()
            
            # New instance should be created
            manager2 = MonitoringManager.get_instance()
            
            assert manager1 is not manager2
        
        # Cleanup
        MonitoringManager.reset_instance()
    
    def test_monitoring_manager_services_integration(self, tmp_path):
        """Test MonitoringManager integrates datum and health services."""
        from src.monitoring.manager import MonitoringManager
        from src.monitoring.datum import DatumMonitor
        from src.monitoring.health import HealthChecker
        
        MonitoringManager.reset_instance()
        
        with patch('docker.from_env'):
            manager = MonitoringManager.get_instance(log_file=tmp_path / "test.log")
            
            # Datum monitor should be initialized
            assert isinstance(manager.datum, DatumMonitor)
            assert manager.datum.node_cli_path == "cellframe-node-cli"
            
            # Health checker should be initialized
            assert isinstance(manager.health, HealthChecker)
            assert manager.health.timeout == 10.0
        
        MonitoringManager.reset_instance()


# ============================================================================
# Integration Tests
# ============================================================================

class TestMonitoringIntegration:
    """Integration tests for monitoring modules."""
    
    @pytest.mark.asyncio
    async def test_manager_datum_health_integration(self, tmp_path):
        """Test MonitoringManager integrates datum and health."""
        from src.monitoring.manager import MonitoringManager
        
        MonitoringManager.reset_instance()
        
        with patch('docker.from_env'):
            manager = MonitoringManager.get_instance(log_file=tmp_path / "test.log")
            
            # Both services should be accessible
            assert manager.datum is not None
            assert manager.health is not None
            
            # Health checker should be usable
            mock_client = AsyncMock()
            mock_response = MagicMock(status_code=200)
            mock_client.get = AsyncMock(return_value=mock_response)
            manager.health._client = mock_client
            
            result = await manager.health.check_http("http://test", "node1")
            assert result.healthy is True
        
        MonitoringManager.reset_instance()
