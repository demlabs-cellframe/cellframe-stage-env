"""Unit tests for NetworkManager auto_build functionality."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch

from src.network.manager import NetworkManager
from src.config.manager import initialize_config, reset_config


class TestNetworkManagerAutoBuild:
    """Test NetworkManager auto_build related methods."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "config").mkdir()
        (temp_dir / "config" / "topologies").mkdir(parents=True)
        
        # Create valid topology following default.json.tpl structure
        topology_file = temp_dir / "config" / "topologies" / "default.json.tpl"
        topology_content = {
            "network": {
                "name": "testnet",
                "network_id": "0x1234",
                "consensus": "esbocs",
                "native_ticker": "TCELL"
            },
            "topology": {
                "root_nodes": {
                    "count": 1,
                    "role": "root",
                    "consensus_participation": False,
                    "is_seed_node": True,
                    "description": "Root nodes"
                },
                "master_nodes": {
                    "count": 0,
                    "role": "master",
                    "consensus_participation": True,
                    "is_seed_node": False,
                    "description": "Master nodes"
                },
                "full_nodes": {
                    "count": 0,
                    "role": "full",
                    "consensus_participation": False,
                    "is_seed_node": False,
                    "description": "Full nodes"
                }
            },
            "build": {
                "type": "debug",
                "cellframe_version": "latest"
            },
            "network_settings": {
                "base_rpc_port": 8545,
                "base_p2p_port": 31337,
                "base_cf_port": 7007,
                "base_http_port": 8079,
                "node_port": 8079,
                "base_ip": "172.20.0.10",
                "subnet": "172.20.0.0/16"
            },
            "consensus": {
                "type": "esbocs",
                "min_validators": 1,
                "new_round_delay": 30,
                "collecting_level": 10.0,
                "auth_certs_prefix": "testnet.master",
                "round_start_sync_timeout": 5,
                "round_attempts_max": 2,
                "round_attempt_timeout": 5,
                "consensus_debug": True,
                "min_fee": "0.01"
            }
        }
        import json
        topology_file.write_text(json.dumps(topology_content, indent=2))
        
        # Create minimal config
        config_file = temp_dir / "config" / "stage-env.cfg"
        config_file.write_text("""[network]
name = testnet
""")
        
        # Initialize config manager
        initialize_config(temp_dir)
        
        yield temp_dir
        
        # Cleanup
        reset_config()
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def network_manager(self, temp_base_path):
        """Create NetworkManager instance."""
        with patch('src.network.manager.DockerComposeManager'):
            with patch('src.network.manager.ConfigGenerator'):
                with patch('src.network.manager.GenesisInitializer'):
                    with patch('src.network.manager.NodeStateManager'):
                        with patch('src.network.manager.SnapshotManager'):
                            manager = NetworkManager(temp_base_path, topology_name="default")
                            return manager
    
    def test_check_package_available_local_path_exists(self, network_manager, temp_base_path):
        """Test _check_package_available with existing local .deb file."""
        # Create a .deb file
        deb_file = temp_base_path / "test.deb"
        deb_file.touch()
        
        node_source_config = {
            'type': 'local_path',
            'local_path': str(deb_file)
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is True
    
    def test_check_package_available_local_path_not_exists(self, network_manager, temp_base_path):
        """Test _check_package_available with non-existing local .deb file."""
        node_source_config = {
            'type': 'local_path',
            'local_path': str(temp_base_path / "nonexistent.deb")
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is False
    
    def test_check_package_available_local_path_relative(self, network_manager, temp_base_path):
        """Test _check_package_available with relative path."""
        # Create a .deb file
        deb_file = temp_base_path / "build" / "test.deb"
        deb_file.parent.mkdir(exist_ok=True)
        deb_file.touch()
        
        node_source_config = {
            'type': 'local_path',
            'local_path': 'build/test.deb'
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is True
    
    def test_check_package_available_local_path_not_deb(self, network_manager, temp_base_path):
        """Test _check_package_available with non-.deb file."""
        # Create a non-.deb file
        txt_file = temp_base_path / "test.txt"
        txt_file.touch()
        
        node_source_config = {
            'type': 'local_path',
            'local_path': str(txt_file)
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is False
    
    def test_check_package_available_local_path_no_path(self, network_manager):
        """Test _check_package_available with local_path type but no path specified."""
        node_source_config = {
            'type': 'local_path'
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is False
    
    def test_check_package_available_url_source(self, network_manager):
        """Test _check_package_available with URL source (always available)."""
        node_source_config = {
            'type': 'url',
            'url': 'https://example.com/cellframe-node.deb'
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is True
    
    def test_check_package_available_repository_source(self, network_manager):
        """Test _check_package_available with repository source (always available)."""
        node_source_config = {
            'type': 'repository',
            'repository_url': 'https://github.com/cellframe-node.git'
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is True
    
    def test_check_package_available_unknown_source_type(self, network_manager):
        """Test _check_package_available with unknown source type."""
        node_source_config = {
            'type': 'unknown_type'
        }
        
        result = network_manager._check_package_available(node_source_config)
        assert result is False


class TestNetworkManagerAutoBuildIntegration:
    """Integration tests for auto_build workflow."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "config").mkdir()
        (temp_dir / "config" / "topologies").mkdir(parents=True)
        
        # Create minimal topology
        topology_file = temp_dir / "config" / "topologies" / "default.json.tpl"
        topology_file.write_text('{"network": {"name": "testnet"}, "nodes": [{"name": "node1", "role": "root"}]}')
        
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_auto_build_disabled_by_default(self, temp_base_path):
        """Test that auto_build is disabled by default."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[network]
name = testnet

[build]
build_type = debug
""")
        
        from src.config.loader import ConfigLoader
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['auto_build'] is False
    
    def test_auto_build_enabled_in_config(self, temp_base_path):
        """Test that auto_build can be enabled via config."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[network]
name = testnet

[build]
auto_build = true
""")
        
        from src.config.loader import ConfigLoader
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['auto_build'] is True
