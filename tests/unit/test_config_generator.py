"""Unit tests for config generator."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config.generator import ConfigGenerator
from src.network.models import NodeConfig
from src.config.loader import NetworkTopology

# Mock NodeRole since it's just strings in NodeConfig
class NodeRole:
    ROOT = "root"
    MASTER = "master"
    FULL = "full"

@pytest.fixture
def mock_cert_generator():
    """Mock CertGenerator."""
    with patch("src.config.generator.CertGenerator") as mock:
        instance = mock.return_value
        instance.generate_all.return_value = True
        yield instance

@pytest.fixture
def mock_config_loader(tmp_path):
    """Mock ConfigLoader."""
    with patch("src.config.generator.get_config_loader") as mock:
        loader = MagicMock()
        loader.get_paths_config.return_value = {'cache_dir': 'cache'}
        mock.return_value = loader
        yield loader

@pytest.fixture
def config_generator(tmp_path, mock_cert_generator, mock_config_loader):
    """Create ConfigGenerator with temporary path."""
    # Create required directories
    (tmp_path / "config" / "templates" / "base").mkdir(parents=True)
    (tmp_path / "config" / "templates" / "cellframe-node.cfg.d").mkdir(parents=True)
    (tmp_path / "config" / "templates" / "chains").mkdir(parents=True)
    
    # Create dummy templates
    (tmp_path / "config" / "templates" / "stagenet.cfg.j2").write_text("[general]\nnetwork={{ network_name }}")
    (tmp_path / "config" / "templates" / "base" / "cellframe-node.cfg.j2").write_text("[server]\nip={{ node_ip }}")
    (tmp_path / "config" / "templates" / "chains" / "main.cfg.j2").write_text("[chain]\nname=main")
    
    return ConfigGenerator(tmp_path)

class TestConfigGenerator:
    """Test configuration generation."""
    
    def test_generate_network_configs(self, config_generator, tmp_path):
        """Test generating network configurations."""
        # Setup topology and nodes
        topology_data = {
            "network": {
                "name": "stagenet",
                "network_id": "0x1",
                "consensus": "poa"
            },
            "topology": {
                "root": {"count": 3, "role": "root", "is_seed_node": True},
                "master": {"count": 3, "role": "master", "consensus_participation": True}
            },
            "consensus": {
                "type": "poa",
                "min_validators": 3,
                "new_round_delay": 100,
                "collecting_level": 50.0,
                "auth_certs_prefix": "stagenet.root"
            },
            "network_settings": {
                "base_rpc_port": 8000,
                "base_p2p_port": 8001,
                "base_cf_port": 8002,
                "base_http_port": 8003,
                "base_ip": "10.0.0.1",
                "subnet": "10.0.0.0/24"
            },
            "build": {
                "type": "debug"
            }
        }
        topology = NetworkTopology(**topology_data)
        
        nodes = [
            NodeConfig(
                node_id=1,
                role=NodeRole.ROOT, 
                ip_address="1.2.3.4", 
                is_seed_node=True,
                node_type="root",
                rpc_port=8000,
                p2p_port=8001,
                cf_port=8002,
                http_port=8003
            ),
            NodeConfig(
                node_id=4,
                role=NodeRole.MASTER, 
                ip_address="5.6.7.8", 
                consensus_participation=True,
                node_type="master",
                rpc_port=8010,
                p2p_port=8011,
                cf_port=8012,
                http_port=8013
            )
        ]
        
        # Run generation
        config_generator._generate_network_configs(topology, nodes)
        
        # Verify node1 config
        node1_cfg = tmp_path / "cache" / "configs" / "node1" / "cellframe-node.cfg"
        assert node1_cfg.exists()
        assert "ip=1.2.3.4" in node1_cfg.read_text()
        
        # Verify node1 network config
        node1_net = tmp_path / "cache" / "configs" / "node1" / "network" / "stagenet.cfg"
        assert node1_net.exists()
        # Note: template variable substitution check depends on my dummy template
        
        # Verify chain config
        node1_chain = tmp_path / "cache" / "configs" / "node1" / "network" / "stagenet" / "main.cfg"
        assert node1_chain.exists()
        assert "name=main" in node1_chain.read_text()

    def test_generate_node_snippet(self, config_generator, tmp_path):
        """Test generating node-specific config snippet."""
        node = NodeConfig(
            node_id=1,
            role=NodeRole.ROOT, 
            ip_address="1.2.3.4", 
            is_seed_node=True,
            node_type="root",
            rpc_port=8000,
            p2p_port=8001,
            cf_port=8002,
            http_port=8003
        )
        
        topology_data = {
            "network": {
                "name": "stagenet",
                "network_id": "0x1",
                "consensus": "poa"
            },
            "topology": {
                "root": {"count": 1, "role": "root", "is_seed_node": True}
            },
            "consensus": {
                "type": "poa",
                "min_validators": 1,
                "new_round_delay": 100,
                "collecting_level": 50.0,
                "auth_certs_prefix": "stagenet.root"
            },
            "network_settings": {
                "base_rpc_port": 8000,
                "base_p2p_port": 8001,
                "base_cf_port": 8002,
                "base_http_port": 8003,
                "base_ip": "10.0.0.1",
                "subnet": "10.0.0.0/24"
            },
            "build": {"type": "debug"}
        }
        topology = NetworkTopology(**topology_data)
        
        config_dir = tmp_path / "test_config"
        config_dir.mkdir()
        
        config_generator._generate_node_snippet(
            config_dir, node, topology, validator_idx=0, network_name="stagenet"
        )
        
        snippet = config_dir / "node1.cfg"
        assert snippet.exists()
        content = snippet.read_text()
        assert "node_id=1" in content
        assert "node_role=root" in content

    def test_collect_validator_addresses(self, config_generator, tmp_path):
        """Test collecting validator addresses from files."""
        # Create dummy validator address file
        certs_dir = tmp_path / "cache" / "certs"
        (certs_dir / "node4").mkdir(parents=True)
        (certs_dir / "node4" / "validator_addr.txt").write_text("0xVALIDATOR")
        
        nodes = [
            NodeConfig(
                node_id=4,
                role=NodeRole.MASTER, 
                ip_address="5.6.7.8", 
                consensus_participation=True,
                node_type="master",
                rpc_port=8010,
                p2p_port=8011,
                cf_port=8012,
                http_port=8013
            )
        ]
        
        addrs = config_generator._collect_validator_addresses(nodes, "stagenet")
        
        assert "[0xVALIDATOR]" == addrs

    def test_clean(self, config_generator, tmp_path):
        """Test cleaning configuration."""
        # Create some files
        (tmp_path / "cache" / "configs" / "dummy").mkdir(parents=True)
        (tmp_path / "cache" / "data").mkdir(parents=True)
        
        # Mock Docker for data cleanup
        with patch("docker.from_env") as mock_docker:
            config_generator.clean()
            
            # Configs should be removed (via shutil)
            assert not (tmp_path / "cache" / "configs").exists()
            
            # Data should be removed via Docker
            mock_docker.return_value.containers.run.assert_called()

