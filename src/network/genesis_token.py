"""
Token genesis management for Cellframe stagenet.

Handles TCELL native token creation and initial transaction.
"""

import re
from pathlib import Path
from typing import List

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from ..utils.logger import get_logger


logger = get_logger(__name__)


class TokenGenesisManager(BaseGenesisManager):
    """
    Manages native token (TCELL) genesis initialization.
    
    Responsibilities:
    - Generate fee collection wallet
    - Create TCELL token declaration
    - Emit TCELL tokens
    - Create first transaction on mainchain
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_from_cli(): Node address retrieval
    """
    
    async def generate_fee_wallet(self) -> str:
        """
        Generate fee collection wallet on node1.
        
        Returns:
            Fee wallet address
            
        Raises:
            RuntimeError: If wallet creation fails
        """
        logger.info("generating_fee_collection_wallet")
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"wallet new -w fee_collector -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                raise RuntimeError(f"Wallet creation failed: exit code {exit_code}, stderr: {stderr_str}")
            
            # Get wallet address
            exit_code_addr, stdout_addr, stderr_addr = self._exec_cli(
                1,
                f"wallet info -w fee_collector -net {self.network_name}",
                check_output=False
            )
            
            if exit_code_addr != 0:
                raise RuntimeError(f"Wallet info failed: exit code {exit_code_addr}")
            
            # Parse address
            addr_match = re.search(r'addr:\s+(\S+)', stdout_addr, re.IGNORECASE)
            if addr_match:
                fee_addr = addr_match.group(1)
                logger.info("fee_wallet_generated", address=fee_addr[:20] + "...")
                return fee_addr
            
            raise RuntimeError(f"Could not parse wallet address from: {stdout_addr[:200]}")
            
        except Exception as e:
            logger.error("fee_wallet_generation_error", error=str(e))
            raise
    
    async def create_native_token(self, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """
        Create TCELL native token on zerochain.
        
        Args:
            root_cert_name: Root certificate name for signing
            
        Returns:
            Token declaration datum hash
            
        Raises:
            RuntimeError: If token creation fails
        """
        logger.info("creating_native_token", token="TCELL", chain="zerochain")
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"token_decl -token TCELL -type private -total_supply 1000000000000000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs {root_cert_name} -net {self.network_name} -chain zerochain",
                check_output=False
            )
            
            logger.info("token_decl_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            if exit_code != 0:
                raise RuntimeError(f"token_decl failed: exit code {exit_code}")
            
            # Parse output
            import yaml
            
            # Try YAML first
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("token_decl_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"token_decl failed: code={error_code}, message={error_msg}")
                    
                    # Extract hash from message
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        token_hash = hash_match.group(1)
                        logger.info("native_token_created", token="TCELL", hash=token_hash)
                        return token_hash
            except yaml.YAMLError:
                pass
            
            # Plain text fallback
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                token_hash = hash_match.group(1)
                logger.info("native_token_created", token="TCELL", hash=token_hash, format="plain_text")
                return token_hash
            
            logger.error("token_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract token hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("native_token_creation_error", error=str(e))
            raise
    
    async def emit_native_token(self, fee_addr: str, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """
        Emit TCELL tokens to fee collection address.
        
        Args:
            fee_addr: Fee collection wallet address
            root_cert_name: Root certificate name for signing
            
        Returns:
            Emission datum hash
            
        Raises:
            RuntimeError: If emission fails
        """
        logger.info("emitting_native_token", token="TCELL", to_addr=fee_addr[:20] + "...")
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"token_emit -token TCELL -emission_value 500000000000000000 -addr {fee_addr} -certs {root_cert_name} -net {self.network_name} -chain zerochain",
                check_output=False
            )
            
            logger.info("token_emit_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            if exit_code != 0:
                raise RuntimeError(f"token_emit failed: exit code {exit_code}")
            
            # Parse output
            import yaml
            
            # Try YAML first
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("token_emit_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"token_emit failed: code={error_code}, message={error_msg}")
                    
                    # Extract hash from message
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        emission_hash = hash_match.group(1)
                        logger.info("native_token_emitted", token="TCELL", hash=emission_hash)
                        return emission_hash
            except yaml.YAMLError:
                pass
            
            # Plain text fallback
            hash_match = re.search(r'Datum\s+(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                emission_hash = hash_match.group(1)
                logger.info("native_token_emitted", token="TCELL", hash=emission_hash, format="plain_text")
                return emission_hash
            
            logger.error("emission_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract emission hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("native_token_emission_error", error=str(e))
            raise
    
    async def create_first_transaction(
        self, 
        emission_hash: str, 
        master_nodes: List[NodeConfig] = None,
        master_cert_name: str = "pvt.stagenet.master.0"
    ) -> str:
        """
        Create first TCELL transaction on mainchain (creates genesis block).
        
        CRITICAL: Must execute on MASTER node with master certificate!
        
        Args:
            emission_hash: Emission datum hash to spend from
            master_nodes: List of master node configs (uses first one)
            master_cert_name: Certificate name for signing
            
        Returns:
            Transaction datum hash
            
        Raises:
            RuntimeError: If transaction creation fails
        """
        logger.info("creating_first_transaction", token="TCELL", chain="main", from_emission=emission_hash[:16])
        
        if not master_nodes or len(master_nodes) == 0:
            raise RuntimeError("No master nodes provided for tx_create")
        
        # Use first MASTER node
        first_master = master_nodes[0]
        logger.debug("using_master_node_for_tx", node_id=first_master.node_id)
        
        try:
            # DIAGNOSTIC: Check if master node can see emission in zerochain DAG events
            logger.info("diagnostic_checking_emission_in_dag", emission=emission_hash[:16])
            exit_code_dag, stdout_dag, _ = self._exec_cli(
                first_master.node_id,
                f"dag event list -net {self.network_name} -chain zerochain -from events -limit 20",
                check_output=False
            )
            # Check if DAG has ANY events
            total_match = re.search(r'total events:\s*(\d+)', stdout_dag, re.IGNORECASE) if stdout_dag else None
            total_events = int(total_match.group(1)) if total_match else 0
            
            logger.info("dag_events_check",
                       exit_code=exit_code_dag,
                       total_events=total_events,
                       has_data=total_events > 0,
                       output_preview=stdout_dag[:300] if stdout_dag else "empty")
            
            # Also check token list
            logger.info("diagnostic_checking_token_list")
            exit_code_token, stdout_token, _ = self._exec_cli(
                first_master.node_id,
                f"token list -net {self.network_name}",
                check_output=False
            )
            logger.info("token_list_check",
                       exit_code=exit_code_token,
                       has_tcell="TCELL" in stdout_token.upper(),
                       output_preview=stdout_token[:300] if stdout_token else "empty")
            
            # Create transaction
            logger.debug("executing_tx_create")
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                first_master.node_id,
                f"tx_create -token TCELL -from_emission {emission_hash} -value 100000000 -fee 0.1 -cert {master_cert_name} -net {self.network_name} -chain main",
                check_output=False
            )
            
            logger.info("tx_create_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            if exit_code != 0:
                raise RuntimeError(f"tx_create failed: exit code {exit_code}")
            
            # Parse output
            import yaml
            
            # Try YAML first
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("tx_create_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"tx_create failed: code={error_code}, message={error_msg}")
                    
                    # Extract hash
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        tx_hash = hash_match.group(1)
                        logger.info("first_transaction_created", token="TCELL", hash=tx_hash)
                        return tx_hash
            except yaml.YAMLError:
                pass
            
            # Plain text fallback
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                tx_hash = hash_match.group(1)
                logger.info("first_transaction_created", token="TCELL", hash=tx_hash, format="plain_text")
                return tx_hash
            
            logger.error("tx_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract tx hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("first_transaction_creation_error", error=str(e))
            raise

