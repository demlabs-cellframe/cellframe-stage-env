"""
Token genesis management for Cellframe stagenet.

Handles TCELL native token creation and initial transaction.
"""

import asyncio
import re
import time
from pathlib import Path
from typing import List

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from src.utils.logger import get_logger
from ..monitoring.waiter.esbocs_waiters import ESBocsActiveWaiter


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
                f"token_decl -token TCELL -type private -total_supply 1000000000000000000000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs {root_cert_name} -net {self.network_name} -chain zerochain",
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
                f"token_emit -token TCELL -emission_value 1000000000000000000000000 -addr {fee_addr} -certs {root_cert_name} -net {self.network_name} -chain zerochain",
                check_output=False
            )
            
            logger.info("token_emit_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            # CRITICAL: Log full output including stderr for debugging
            logger.info("token_emit_full_output",
                       exit_code=exit_code,
                       stdout=stdout_str[:2000] if stdout_str else "empty",
                       stderr=stderr_str[:2000] if stderr_str else "empty",
                       note="Full token_emit output - check if datum was created and added to mempool")
            
            if exit_code != 0:
                logger.error("token_emit_failed_with_error",
                           exit_code=exit_code,
                           stderr=stderr_str[:1000] if stderr_str else "none",
                           stdout=stdout_str[:1000] if stdout_str else "none")
                raise RuntimeError(f"token_emit failed: exit code {exit_code}, stderr: {stderr_str[:500]}")
            
            # CRITICAL: Verify datum is in mempool immediately after creation
            logger.info("verifying_emission_datum_in_mempool_after_creation")
            await asyncio.sleep(2)  # Wait a bit for datum to be added to mempool
            exit_code_mempool, stdout_mempool, _ = self._exec_cli(
                1,
                f"mempool list -net {self.network_name} -chain zerochain",
                check_output=False
            )
            if exit_code_mempool == 0 and stdout_mempool:
                logger.info("mempool_content_after_token_emit",
                           mempool_content=stdout_mempool[:1000],
                           note="Check if emission datum is in mempool after token_emit")
            else:
                logger.warning("failed_to_check_mempool_after_token_emit",
                             exit_code=exit_code_mempool,
                             note="Could not verify emission datum in mempool")
            
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
            total_match = re.search(r'total_events:\s*(\d+)', stdout_dag, re.IGNORECASE) if stdout_dag else None
            total_events = int(total_match.group(1)) if total_match else 0
            
            logger.info("dag_events_check",
                       exit_code=exit_code_dag,
                       total_events=total_events,
                       has_data=total_events > 0,
                       output_preview=stdout_dag[:300] if stdout_dag else "empty")
            
            # CRITICAL: Verify emission hash is actually in DAG events
            emission_found_in_dag = False
            if stdout_dag and emission_hash.lower() in stdout_dag.lower():
                emission_found_in_dag = True
                logger.info("emission_hash_found_in_dag_events", emission=emission_hash[:16])
            else:
                logger.warning("emission_hash_not_found_in_dag_events",
                             emission=emission_hash[:16],
                             note="Emission may not be synced to MASTER node")
            
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
            
            # CRITICAL: Check network state before creating transaction
            logger.info("diagnostic_checking_network_state_before_tx")
            exit_code_net, stdout_net, stderr_net = self._exec_cli(
                first_master.node_id,
                f"net -net {self.network_name} get status",
                check_output=False
            )
            is_online = False
            if exit_code_net == 0 and stdout_net:
                is_online = "NET_STATE_ONLINE" in stdout_net or "current: ONLINE" in stdout_net
                logger.info("network_state_check",
                           exit_code=exit_code_net,
                           is_online=is_online,
                           state_preview=stdout_net[:300] if stdout_net else "empty")
            else:
                logger.error("network_state_check_failed",
                           exit_code=exit_code_net,
                           stderr=stderr_net[:200] if stderr_net else "empty")
            
            if not is_online:
                logger.error("node_not_online_before_tx",
                           node_id=first_master.node_id,
                           note="Network must be ONLINE to create transactions")
                raise RuntimeError(f"Node {first_master.node_id} is not ONLINE. Cannot create transaction.")
            
            # CRITICAL: Check mempool status before creating transaction
            logger.info("diagnostic_checking_mempool_before_tx")
            exit_code_mp, stdout_mp, _ = self._exec_cli(
                first_master.node_id,
                f"mempool list -net {self.network_name} -chain main",
                check_output=False
            )
            logger.info("mempool_check_before_tx",
                       exit_code=exit_code_mp,
                       output_preview=stdout_mp[:300] if stdout_mp else "empty")
            
            # CRITICAL: Check ESBocs consensus state (if available)
            logger.info("diagnostic_checking_consensus_state_before_tx")
            try:
                exit_code_consensus, stdout_consensus, _ = self._exec_cli(
                    first_master.node_id,
                    f"block list -net {self.network_name} -chain main -last 1",
                    check_output=False
                )
                logger.info("consensus_check_before_tx",
                           exit_code=exit_code_consensus,
                           output_preview=stdout_consensus[:300] if stdout_consensus else "empty")
            except Exception as e:
                logger.debug("consensus_check_exception", error=str(e)[:100])
            
            # CRITICAL: Check ESBocs status - validator mode must be active!
            logger.info("diagnostic_checking_esbocs_status_before_tx")
            esbocs_active = False
            esbocs_round_id = None
            try:
                exit_code_esbocs, stdout_esbocs, stderr_esbocs = self._exec_cli(
                    first_master.node_id,
                    f"esbocs status -net {self.network_name} -chain main",
                    check_output=False
                )
                if exit_code_esbocs == 0 and stdout_esbocs:
                    logger.info("esbocs_status_check",
                               exit_code=exit_code_esbocs,
                               output_preview=stdout_esbocs[:500] if stdout_esbocs else "empty")
                    # Check if ESBocs is active (round_id > 0 means it's running)
                    round_match = re.search(r'round_id:\s*(\d+)', stdout_esbocs, re.IGNORECASE)
                    if round_match:
                        esbocs_round_id = int(round_match.group(1))
                        esbocs_active = esbocs_round_id > 0
                        logger.info("esbocs_round_id_check",
                                   round_id=esbocs_round_id,
                                   active=esbocs_active)
                    else:
                        # Check if output contains "validator mode" or similar
                        if "validator" in stdout_esbocs.lower() or "active" in stdout_esbocs.lower():
                            esbocs_active = True
                            logger.info("esbocs_active_by_keyword")
                        else:
                            logger.warning("esbocs_round_id_not_found",
                                         output_preview=stdout_esbocs[:300])
                else:
                    logger.error("esbocs_status_check_failed",
                               exit_code=exit_code_esbocs,
                               stderr=stderr_esbocs[:200] if stderr_esbocs else "empty")
            except Exception as e:
                logger.error("esbocs_status_check_exception", error=str(e)[:100])
            
            # CRITICAL: Check validator orders - validator mode requires orders!
            logger.info("diagnostic_checking_validator_orders_before_tx")
            has_validator_orders = False
            order_count = 0
            try:
                exit_code_orders, stdout_orders, stderr_orders = self._exec_cli(
                    first_master.node_id,
                    f"srv_stake order list -net {self.network_name}",
                    check_output=False
                )
                if exit_code_orders == 0 and stdout_orders:
                    stdout_lower = stdout_orders.lower()
                    order_count = stdout_lower.count("order:")
                    has_validator_orders = order_count > 0
                    logger.info("validator_orders_check",
                               exit_code=exit_code_orders,
                               order_count=order_count,
                               has_orders=has_validator_orders,
                               output_preview=stdout_orders[:500] if stdout_orders else "empty")
                else:
                    logger.error("validator_orders_check_failed",
                               exit_code=exit_code_orders,
                               stderr=stderr_orders[:200] if stderr_orders else "empty")
            except Exception as e:
                logger.error("validator_orders_check_exception", error=str(e)[:100])
            
            # CRITICAL: If round_id is 0, wait for validator synchronization
            # ESBocs requires validators to exchange START_SYNC messages before round_id is set
            # This can take time (up to round_start_sync_timeout seconds, default 15)
            if not esbocs_active or esbocs_round_id == 0:
                logger.info("esbocs_not_active_waiting_for_synchronization",
                           round_id=esbocs_round_id,
                           node_id=first_master.node_id,
                           note="Waiting for validators to synchronize via START_SYNC messages")
                
                # Wait up to 60 seconds for consensus to become active
                waiter_esbocs_active = ESBocsActiveWaiter(
                    exec_cli=self._exec_cli,
                    node_id=first_master.node_id,
                    network_name=self.network_name,
                    chain="main",
                    poll_interval=3.0
                )
                try:
                    await waiter_esbocs_active.wait(timeout=60.0)
                    esbocs_active = True
                    # Re-check round_id after wait
                    exit_code_esbocs, stdout_esbocs, stderr_esbocs = self._exec_cli(
                        first_master.node_id,
                        f"esbocs status -net {self.network_name} -chain main",
                        check_output=False
                    )
                    if exit_code_esbocs == 0 and stdout_esbocs:
                        round_match = re.search(r'round_id:\s*(\d+)', stdout_esbocs, re.IGNORECASE)
                        if round_match:
                            esbocs_round_id = int(round_match.group(1))
                except TimeoutError:
                    logger.error("esbocs_not_active_after_wait",
                               node_id=first_master.node_id,
                               round_id=esbocs_round_id,
                               note="Validators may not have synchronized - check network links and START_SYNC messages")
                    esbocs_active = False
            
            # CRITICAL: Fail if ESBocs is not active or validator orders are missing
            if not esbocs_active:
                logger.error("esbocs_not_active_before_tx",
                           node_id=first_master.node_id,
                           round_id=esbocs_round_id,
                           note="ESBocs consensus must be active to process transactions")
                raise RuntimeError(f"ESBocs consensus is not active on node {first_master.node_id}. "
                                 f"Round ID: {esbocs_round_id}, "
                                 f"Cannot create transactions without active consensus.")
            
            if not has_validator_orders:
                logger.error("validator_orders_missing_before_tx",
                           node_id=first_master.node_id,
                           order_count=order_count,
                           note="Validator mode requires orders in GDB")
                raise RuntimeError(f"Validator orders not found on node {first_master.node_id}. "
                                 f"Order count: {order_count}, "
                                 f"Cannot create transactions without validator orders.")
            
            # Create transaction
            logger.debug("executing_tx_create")
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                first_master.node_id,
                f"tx create -token TCELL -from_emission {emission_hash} -value 100000000 -fee 0.1 -cert {master_cert_name} -net {self.network_name} -chain main",
                check_output=False
            )
            
            logger.info("tx_create_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            # CRITICAL: Check if output contains error message
            if stdout_str and "Can't place TX datum in mempool" in stdout_str:
                logger.error("tx_create_mempool_error",
                           emission=emission_hash[:16],
                           node_id=first_master.node_id,
                           output_full=stdout_str[:1000],
                           note="Transaction cannot be placed in mempool - check node logs for details")
                # Try to get more diagnostic info
                logger.info("collecting_additional_diagnostics_for_mempool_error")
                try:
                    # Check mempool again
                    exit_code_mp2, stdout_mp2, _ = self._exec_cli(
                        first_master.node_id,
                        f"mempool list -net {self.network_name} -chain main",
                        check_output=False
                    )
                    logger.error("mempool_after_tx_failure",
                                exit_code=exit_code_mp2,
                                output=stdout_mp2[:500] if stdout_mp2 else "empty")
                    
                    # Check network state again
                    exit_code_net2, stdout_net2, _ = self._exec_cli(
                        first_master.node_id,
                        f"net -net {self.network_name} get status",
                        check_output=False
                    )
                    logger.error("network_state_after_tx_failure",
                                exit_code=exit_code_net2,
                                state=stdout_net2[:500] if stdout_net2 else "empty")
                except Exception as e:
                    logger.debug("diagnostic_collection_failed", error=str(e)[:100])
                
                raise RuntimeError(f"Transaction cannot be placed in mempool. "
                                 f"Emission hash: {emission_hash[:16]}, "
                                 f"Node: {first_master.node_id}, "
                                 f"Output: {stdout_str[:200]}")
            
            if exit_code != 0:
                raise RuntimeError(f"tx_create failed: exit code {exit_code}, stderr: {stderr_str[:200] if stderr_str else 'empty'}")
            
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
                
                # CRITICAL DIAGNOSTIC: Verify TX is actually in mempool
                logger.info("verifying_tx_in_mempool", tx_hash=tx_hash[:16])
                import asyncio
                await asyncio.sleep(2.0)  # Give time for mempool placement
                
                exit_code_mempool, stdout_mempool, _ = self._exec_cli(
                    first_master.node_id,
                    f"mempool list -net {self.network_name} -chain main",
                    check_output=False
                )
                
                if exit_code_mempool == 0 and stdout_mempool:
                    # Check if TX is in mempool
                    if tx_hash in stdout_mempool:
                        logger.info("tx_confirmed_in_mempool", tx_hash=tx_hash[:16])
                    else:
                        # Count total TX in mempool
                        total_match = re.search(r'total:\s*stagenet\.main:\s*(\d+)', stdout_mempool, re.IGNORECASE)
                        total_tx = int(total_match.group(1)) if total_match else 0
                        
                        logger.error("tx_not_in_mempool",
                                   tx_hash=tx_hash[:16],
                                   total_tx_in_mempool=total_tx,
                                   mempool_output=stdout_mempool[:500])
                
                return tx_hash
            
            logger.error("tx_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract tx hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("first_transaction_creation_error", error=str(e))
            raise

