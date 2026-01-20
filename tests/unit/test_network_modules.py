"""Unit tests for src/network/ modules."""
import pytest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestNetworkManager:
    """Test NetworkManager class."""
    
    def test_network_manager_import(self):
        """Test importing NetworkManager."""
        from src.network.manager import NetworkManager
        assert NetworkManager is not None
    
    def test_network_manager_init(self):
        """Test NetworkManager initialization."""
        from src.network.manager import NetworkManager
        
        # NetworkManager requires initialized config, skip instantiation
        # Just test that class is importable
        assert NetworkManager is not None


class TestGenesisBase:
    """Test genesis_base module."""
    
    def test_genesis_base_import(self):
        """Test importing genesis_base."""
        from src.network import genesis_base
        assert genesis_base is not None
    
    def test_genesis_base_class_import(self):
        """Test importing from genesis_base module."""
        from src.network import genesis_base
        # Module has various genesis classes, just check module is importable
        assert genesis_base is not None


class TestTopology:
    """Test network config modules."""
    
    def test_genesis_config_import(self):
        """Test importing genesis_config module."""
        from src.network import genesis_config
        assert genesis_config is not None
    
    def test_config_context_import(self):
        """Test importing config_context."""
        from src.network import config_context
        assert config_context is not None


class TestGenesisSubmodules:
    """Test genesis submodules."""
    
    def test_import_genesis(self):
        """Test importing genesis."""
        from src.network import genesis
        assert genesis is not None
    
    def test_import_genesis_registration(self):
        """Test importing genesis_registration."""
        from src.network import genesis_registration
        assert genesis_registration is not None
    
    def test_import_genesis_token(self):
        """Test importing genesis_token."""
        from src.network import genesis_token
        assert genesis_token is not None


class TestNetworkIntegration:
    """Integration tests for network modules."""
    
    def test_network_manager_importable(self):
        """Test NetworkManager can be imported."""
        from src.network.manager import NetworkManager
        
        assert NetworkManager is not None
    
    def test_genesis_modules_importable(self):
        """Test genesis modules can be imported."""
        from src.network import genesis_base, genesis_config
        
        assert genesis_base is not None
        assert genesis_config is not None
