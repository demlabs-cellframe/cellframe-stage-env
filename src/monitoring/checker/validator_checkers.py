"""
Checkers for validator operations.

Extracted from genesis_validator.py for better code organization.
"""

from pathlib import Path
from typing import List, Optional

from .base import BaseChecker
from ...network.models import NodeConfig
from src.utils.logger import get_logger
from ...config.manager import get_config_loader
from ..validator import ValidatorMonitor
from ..base import MonitorConfig

logger = get_logger(__name__)


class ValidatorOrdersChecker(BaseChecker):
    """
    Verify that all nodes can see all validator orders.
    
    Creates ValidatorMonitor on-demand for this specific verification.
    Monitor is SILENT after this call completes - no background tasks!
    
    This is critical for ESBocs consensus - if nodes don't see orders,
    they will switch off validator mode and refuse to create blocks.
    
    Usage:
        checker = ValidatorOrdersChecker(nodes, expected_count, network_name, base_path, config_path)
        await checker.verify()  # Raises RuntimeError if orders not visible
    """
    
    def __init__(
        self,
        nodes: List[NodeConfig],
        expected_count: int,
        network_name: str,
        base_path: Path,
        config_path: Optional[Path] = None,
        timeout: float = 30.0
    ):
        """
        Initialize validator orders checker.
        
        Args:
            nodes: List of NodeConfig objects to check
            expected_count: Expected number of validator orders
            network_name: Network name
            base_path: Base path to stage-env directory
            config_path: Optional path to stage-env.cfg
            timeout: Maximum time to wait for orders to appear
        """
        self.nodes = nodes
        self.expected_count = expected_count
        self.network_name = network_name
        self.base_path = base_path
        self.config_path = config_path
        self.timeout = timeout
    
    async def check(self) -> bool:
        """
        Check if validator orders are visible.
        
        Returns:
            True if orders are visible, False otherwise
        """
        try:
            await self._verify_orders()
            return True
        except RuntimeError:
            return False
    
    async def verify(self) -> None:
        """
        Verify that orders are visible and raise exception if not.
        
        Raises:
            RuntimeError: If orders are not visible after timeout
        """
        await self._verify_orders()
    
    async def _verify_orders(self) -> None:
        """Internal method to verify orders."""
        # Load monitoring config from stage-env.cfg
        config_loader = get_config_loader()
        stage_config = config_loader.load_stage_config()
        
        # Extract monitoring settings (keys are flattened)
        monitoring_cfg = {
            'validator_log_enabled': stage_config.get('validator_log_enabled', True),
            'validator_poll_interval': stage_config.get('validator_poll_interval', 2.0),
            'validator_log_interval': stage_config.get('validator_log_interval', 5.0),
            'validator_timeout': stage_config.get('validator_timeout', 60.0),
            'verbose': stage_config.get('verbose', True)
        }
        
        monitor_config = MonitorConfig(
            log_enabled=monitoring_cfg.get("validator_log_enabled", True),
            poll_interval=float(monitoring_cfg.get("validator_poll_interval", 2.0)),
            log_interval=float(monitoring_cfg.get("validator_log_interval", 5.0)),
            timeout=float(monitoring_cfg.get("validator_timeout", self.timeout)),
            verbose=monitoring_cfg.get("verbose", True)
        )
        
        # Create monitor ON-DEMAND for this verification only
        # It will be garbage collected after wait_until_ready() completes
        monitor = ValidatorMonitor(
            nodes=self.nodes,
            network_name=self.network_name,
            expected_order_count=self.expected_count,
            config=monitor_config
        )
        
        try:
            await monitor.wait_until_ready(name="validator_orders_verification")
            # Monitor is now SILENT - no more logging until next call
        except TimeoutError as e:
            raise RuntimeError(str(e)) from e


class CertificateOrderMatchChecker(BaseChecker):
    """
    Verify that each node's blocks-sign-cert matches the order signature.
    
    CRITICAL: ESBocs will only find orders signed by the same certificate
    used for block signing. This checker verifies the match.
    
    Usage:
        checker = CertificateOrderMatchChecker(nodes, network_name, base_path)
        await checker.verify()  # Raises RuntimeError if mismatch detected
    """
    
    def __init__(
        self,
        nodes: List[NodeConfig],
        network_name: str,
        base_path: Path,
        root_nodes_count: int = None
    ):
        """
        Initialize certificate order match checker.
        
        Args:
            nodes: List of master nodes to verify
            network_name: Network name
            base_path: Base path to stage-env directory
            root_nodes_count: Number of root nodes (calculated from nodes if not provided)
        """
        self.nodes = nodes
        self.network_name = network_name
        self.base_path = base_path
        # Calculate root_nodes_count if not provided
        if root_nodes_count is not None:
            self.root_nodes_count = root_nodes_count
        else:
            self.root_nodes_count = sum(1 for n in nodes if n.is_seed_node)
    
    async def check(self) -> bool:
        """
        Check if certificates match orders.
        
        Returns:
            True if all certificates match, False otherwise
        """
        try:
            await self._verify_certificates()
            return True
        except RuntimeError:
            return False
    
    async def verify(self) -> None:
        """
        Verify certificates and raise exception on mismatch.
        
        Raises:
            RuntimeError: If certificate mismatch is detected
        """
        await self._verify_certificates()
    
    async def _verify_certificates(self) -> None:
        """Internal method to verify certificates."""
        logger.info("verifying_certificate_order_match",
                   node_count=len(self.nodes))
        
        mismatches = []
        
        for node in self.nodes:
            # Calculate validator_idx based on root_nodes_count
            validator_idx = node.node_id - self.root_nodes_count - 1
            # Certificate format: {network}.master.pvt.{idx}
            expected_cert = f"pvt.{self.network_name}.master.{validator_idx}"
            
            # Read blocks-sign-cert from config file directly
            # Config files are in tests/testing/cache/configs/node{X}/etc/network/{network_name}/{chain_name}
            # or in tests/testing/cache/configs/node{X}/cellframe-node.cfg.d/node{X}.cfg
            config_found = False
            
            # Try chain config first (main chain)
            chain_config_path = self.base_path.parent / "testing" / "cache" / "configs" / f"node{node.node_id}" / "etc" / "network" / self.network_name / "main"
            if chain_config_path.exists():
                try:
                    # Use centralized config manager
                    config_loader = get_config_loader()
                    config = config_loader.load_config_file(chain_config_path)
                    if config.has_section('esbocs') and config.has_option('esbocs', 'blocks-sign-cert'):
                        config_cert = config.get('esbocs', 'blocks-sign-cert').strip()
                        config_found = True
                        if config_cert != expected_cert:
                            mismatches.append({
                                'node_id': node.node_id,
                                'expected': expected_cert,
                                'found': config_cert,
                                'source': str(chain_config_path)
                            })
                            logger.error("blocks_sign_cert_mismatch",
                                       node_id=node.node_id,
                                       expected=expected_cert,
                                       found=config_cert,
                                       config_path=str(chain_config_path),
                                       note="Certificate mismatch - ESBocs won't find orders")
                        else:
                            logger.debug("blocks_sign_cert_match",
                                       node_id=node.node_id,
                                       cert=expected_cert,
                                       config_path=str(chain_config_path))
                except Exception as e:
                    logger.warning("failed_to_read_chain_config",
                                 node_id=node.node_id,
                                 path=str(chain_config_path),
                                 error=str(e)[:100])
            
            # Try network config (cellframe-node.cfg.d/node{X}.cfg)
            if not config_found:
                network_config_path = self.base_path.parent / "testing" / "cache" / "configs" / f"node{node.node_id}" / "cellframe-node.cfg.d" / f"node{node.node_id}.cfg"
                if network_config_path.exists():
                    try:
                        # Use centralized config manager
                        config_loader = get_config_loader()
                        config = config_loader.load_config_file(network_config_path)
                        # Check if there's an [esbocs] section
                        if config.has_section('esbocs') and config.has_option('esbocs', 'blocks-sign-cert'):
                            config_cert = config.get('esbocs', 'blocks-sign-cert').strip()
                            config_found = True
                            if config_cert != expected_cert:
                                mismatches.append({
                                    'node_id': node.node_id,
                                    'expected': expected_cert,
                                    'found': config_cert,
                                    'source': str(network_config_path)
                                })
                                logger.error("blocks_sign_cert_mismatch",
                                           node_id=node.node_id,
                                           expected=expected_cert,
                                           found=config_cert,
                                           config_path=str(network_config_path),
                                           note="Certificate mismatch - ESBocs won't find orders")
                            else:
                                logger.debug("blocks_sign_cert_match",
                                           node_id=node.node_id,
                                           cert=expected_cert,
                                           config_path=str(network_config_path))
                    except Exception as e:
                        logger.warning("failed_to_read_network_config",
                                     node_id=node.node_id,
                                     path=str(network_config_path),
                                     error=str(e)[:100])
            
            # Try network/{network_name}/main.cfg
            if not config_found:
                network_file_path = self.base_path.parent / "testing" / "cache" / "configs" / f"node{node.node_id}" / "network" / self.network_name / "main"
                if network_file_path.exists():
                    try:
                        # Use centralized config manager
                        config_loader = get_config_loader()
                        config = config_loader.load_config_file(network_file_path)
                        if config.has_section('esbocs') and config.has_option('esbocs', 'blocks-sign-cert'):
                            config_cert = config.get('esbocs', 'blocks-sign-cert').strip()
                            config_found = True
                            if config_cert != expected_cert:
                                mismatches.append({
                                    'node_id': node.node_id,
                                    'expected': expected_cert,
                                    'found': config_cert,
                                    'source': str(network_file_path)
                                })
                                logger.error("blocks_sign_cert_mismatch",
                                           node_id=node.node_id,
                                           expected=expected_cert,
                                           found=config_cert,
                                           config_path=str(network_file_path),
                                           note="Certificate mismatch - ESBocs won't find orders")
                            else:
                                logger.debug("blocks_sign_cert_match",
                                           node_id=node.node_id,
                                           cert=expected_cert,
                                           config_path=str(network_file_path))
                    except Exception as e:
                        logger.warning("failed_to_read_network_file",
                                     node_id=node.node_id,
                                     path=str(network_file_path),
                                     error=str(e)[:100])
            
            if not config_found:
                logger.warning("cannot_find_blocks_sign_cert_in_config",
                             node_id=node.node_id,
                             expected=expected_cert,
                             note="Config file not found or esbocs section missing")
        
        # FAIL-FAST: Raise exception if any mismatches found
        if mismatches:
            error_msg = "Certificate mismatch detected! ESBocs won't find orders.\n"
            error_msg += "Expected certificates:\n"
            for node in self.nodes:
                validator_idx = node.node_id - self.root_nodes_count - 1
                expected_cert = f"pvt.{self.network_name}.master.{validator_idx}"
                error_msg += f"  node{node.node_id}: {expected_cert}\n"
            error_msg += "\nMismatches found:\n"
            for mismatch in mismatches:
                error_msg += f"  node{mismatch['node_id']}: expected {mismatch['expected']}, found {mismatch['found']} in {mismatch['source']}\n"
            logger.error("certificate_mismatch_fail_fast",
                        mismatches=len(mismatches),
                        total_nodes=len(self.nodes))
            raise RuntimeError(error_msg)
        
        logger.info("certificate_order_match_verification_completed",
                   verified_nodes=len(self.nodes))


# Backward compatibility functions
async def verify_validator_orders(
    nodes: List[NodeConfig],
    expected_count: int,
    network_name: str,
    base_path: Path,
    config_path: Optional[Path] = None,
    timeout: float = 30.0
) -> None:
    """
    Verify that all nodes can see all validator orders.
    
    This is a convenience function that uses ValidatorOrdersChecker.
    For new code, prefer using ValidatorOrdersChecker directly.
    
    Args:
        nodes: List of NodeConfig objects to check
        expected_count: Expected number of validator orders
        network_name: Network name
        base_path: Base path to stage-env directory
        config_path: Optional path to stage-env.cfg
        timeout: Maximum time to wait for orders to appear
    
    Raises:
        RuntimeError: If orders are not visible after timeout
    """
    checker = ValidatorOrdersChecker(nodes, expected_count, network_name, base_path, config_path, timeout)
    await checker.verify()


async def verify_certificate_order_match(
    nodes: List[NodeConfig],
    network_name: str,
    base_path: Path
) -> None:
    """
    Verify that each node's blocks-sign-cert matches the order signature.
    
    This is a convenience function that uses CertificateOrderMatchChecker.
    For new code, prefer using CertificateOrderMatchChecker directly.
    
    Args:
        nodes: List of master nodes to verify
        network_name: Network name
        base_path: Base path to stage-env directory
    
    Raises:
        RuntimeError: If certificate mismatch is detected
    """
    checker = CertificateOrderMatchChecker(nodes, network_name, base_path)
    await checker.verify()

