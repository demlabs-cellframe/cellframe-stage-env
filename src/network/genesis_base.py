"""
Base class for genesis managers.

Provides common functionality for all genesis-related managers.
"""

import re
import time
import asyncio
import decimal
from pathlib import Path
from typing import Optional, List

import docker

from src.utils.logger import get_logger
from .models import NodeConfig


logger = get_logger(__name__)


class BaseGenesisManager:
    """
    Base class for all genesis managers.
    
    Provides common functionality:
    - CLI command execution in containers
    - Node address retrieval with retry logic
    - Docker client management
    - Wallet operations
    - Token transfers
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", config_path: Path = None,
                 custom_templates_dir: Path = None):
        """
        Initialize base genesis manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to stage-env.cfg
            custom_templates_dir: Optional path to custom templates directory
        """
        self.base_path = base_path
        self.network_name = network_name
        self.config_path = config_path
        self.custom_templates_dir = custom_templates_dir
        self.docker_client = docker.from_env(timeout=30)
        # Use DockerContainerManager for CLI execution
        from ..docker.container import DockerContainerManager
        self.container_manager = DockerContainerManager(base_path, "cellframe-node-cli")
    
    def _exec_cli(self, node_id: int, command: str, check_output: bool = True) -> tuple:
        """
        Execute CLI command inside container (delegates to DockerContainerManager).
        
        Args:
            node_id: Node ID (1-8)
            command: CLI command without 'cellframe-node-cli' prefix
            check_output: Whether to check for errors in output (not used, kept for compatibility)
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        # Use container manager for fail-fast execution
        exit_code, stdout, stderr = self.container_manager.exec_cli_command_sync(
            command=command,
            node=f"node{node_id}",
            timeout=30
        )
        
        if check_output and exit_code != 0:
            logger.warning("cli_command_failed",
                         node_id=node_id,
                         command=command[:100],
                         exit_code=exit_code,
                         stderr=stderr[:500])
            
        return exit_code, stdout, stderr
    
    def _read_node_addr_from_cli(self, node_id: int, max_retries: int = 3) -> str:
        """
        Read node address from running container via CLI with retry logic.
        
        Executes 'node dump -net {network}' and parses node address from output.
        
        Args:
            node_id: Node ID (1-8)
            max_retries: Maximum number of retry attempts
            
        Returns:
            Node address string or empty string if failed
        """
        for attempt in range(max_retries):
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node_id,
                    f"node dump -net {self.network_name}",
                    check_output=False
                )
                
                if exit_code == 0 and stdout_str:
                    # Parse node address from output
                    # Format: "Node addr: XXXX::YYYY::ZZZZ::WWWW"
                    addr_match = re.search(r'Node addr:\s*([A-Fa-f0-9:]+)', stdout_str)
                    if addr_match:
                        node_addr = addr_match.group(1)
                        logger.debug("node_addr_found",
                                   node_id=node_id,
                                   addr=node_addr,
                                   attempt=attempt + 1)
                        return node_addr
                    else:
                        logger.warning("node_addr_not_in_output",
                                     node_id=node_id,
                                     attempt=attempt + 1,
                                     output_preview=stdout_str[:200])
                else:
                    logger.warning("node_dump_failed",
                                 node_id=node_id,
                                 attempt=attempt + 1,
                                 exit_code=exit_code,
                                 stderr=stderr_str[:200])
                
            except Exception as e:
                logger.warning("node_addr_read_exception",
                             node_id=node_id,
                             attempt=attempt + 1,
                             error=str(e))
            
            # Wait before retry
            if attempt < max_retries - 1:
                time.sleep(2)
        
        logger.error("failed_to_read_node_addr_after_retries",
                   node_id=node_id,
                   max_retries=max_retries)
        return ""
    
    async def _read_node_addr_with_retry(self, node_id: int, network_name: str, max_retries: int = 10) -> str:
        """
        Read node address with async retry logic.
        
        Args:
            node_id: Node ID
            network_name: Network name
            max_retries: Maximum retry attempts
            
        Returns:
            Node address string
            
        Raises:
            RuntimeError: If address cannot be retrieved
        """
        for attempt in range(max_retries):
            addr = self._read_node_addr_from_cli(node_id)
            if addr:
                return addr
            if attempt < max_retries - 1:
                await asyncio.sleep(2.0)
        
        raise RuntimeError(f"Failed to read node address for node {node_id} after {max_retries} attempts")
    
    async def create_wallet(self, node_id: int, wallet_name: str, cert_name: str) -> str:
        """
        Create wallet on node.
        
        Args:
            node_id: Node ID
            wallet_name: Wallet name
            cert_name: Certificate name for signing
            
        Returns:
            Wallet address
            
        Raises:
            RuntimeError: If wallet creation fails
        """
        logger.info("creating_wallet", node_id=node_id, wallet_name=wallet_name, cert_name=cert_name)
        
        try:
            # Create wallet
            # CRITICAL: -sign requires signature TYPE (sig_dil, sig_falcon), not certificate name!
            # Our validator certs use DILITHIUM, so use sig_dil (like tests-in-docker)
            exit_code, stdout, stderr = self._exec_cli(
                node_id,
                f"wallet new -w {wallet_name} -sign sig_dil -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                raise RuntimeError(f"wallet new failed: exit_code={exit_code}, stderr={stderr}")
            
            # Parse wallet address from output
            # Format: "new address: WkojSeUjApyYYy5XF6sFwwiLvXnxv5oV6moCWVaicdsj1D"
            addr_match = re.search(r'new address:\s*([A-Za-z0-9]+)', stdout)
            if not addr_match:
                # Try alternative formats
                addr_match = re.search(r'addr:\s*([A-Za-z0-9]+)', stdout)
            if not addr_match:
                addr_match = re.search(r'Address:\s*([A-Za-z0-9]+)', stdout)
            
            if addr_match:
                wallet_addr = addr_match.group(1)
                logger.info("wallet_created",
                          node_id=node_id,
                          wallet_name=wallet_name,
                          address=wallet_addr)
                return wallet_addr
            else:
                raise RuntimeError(f"Failed to parse wallet address from output: {stdout[:200]}")
                
        except Exception as e:
            logger.error("wallet_creation_failed",
                       node_id=node_id,
                       wallet_name=wallet_name,
                       error=str(e))
            raise RuntimeError(f"Failed to create wallet {wallet_name} on node {node_id}: {e}") from e
    
    async def get_wallet_address(self, node_id: int, wallet_name: str) -> str:
        """
        Get wallet address.
        
        Args:
            node_id: Node ID
            wallet_name: Wallet name
            
        Returns:
            Wallet address
            
        Raises:
            RuntimeError: If wallet address cannot be retrieved
        """
        try:
            exit_code, stdout, stderr = self._exec_cli(
                node_id,
                f"wallet info -w {wallet_name} -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                raise RuntimeError(f"wallet info failed: exit_code={exit_code}, stderr={stderr}")
            
            # Parse wallet address from output
            # Format: "new address: WkojSeUjApyYYy5XF6sFwwiLvXnxv5oV6moCWVaicdsj1D"
            addr_match = re.search(r'new address:\s*([A-Za-z0-9]+)', stdout)
            if not addr_match:
                # Try alternative formats
                addr_match = re.search(r'addr:\s*([A-Za-z0-9]+)', stdout)
            if not addr_match:
                addr_match = re.search(r'Address:\s*([A-Za-z0-9]+)', stdout)
            
            if addr_match:
                return addr_match.group(1)
            else:
                raise RuntimeError(f"Failed to parse wallet address from output: {stdout[:200]}")
                
        except Exception as e:
            logger.error("wallet_address_retrieval_failed",
                       node_id=node_id,
                       wallet_name=wallet_name,
                       error=str(e))
            raise RuntimeError(f"Failed to get wallet address for {wallet_name} on node {node_id}: {e}") from e
    
    async def transfer_tokens(
        self,
        from_node_id: int,
        from_wallet: str,
        to_address: str,
        amount: str,
        token: str = "TCELL",
        fee: Optional[str] = None,
        chain: str = "main"
    ) -> str:
        """
        Transfer tokens from wallet to address.
        
        Args:
            from_node_id: Source node ID
            from_wallet: Source wallet name
            to_address: Destination address
            amount: Amount to transfer (e.g., "100.0" or "1.0e+18")
            token: Token ticker (default: TCELL)
            fee: Transaction fee (optional, default: "0.1" in token units)
            chain: Chain name (default: "main")
            
        Returns:
            Transaction hash
            
        Raises:
            RuntimeError: If transfer fails
        """
        # CRITICAL: SDK requires -fee parameter for tx_create when using -from_wallet
        # Default fee is 0.1 tokens (same as in genesis_token.py)
        if fee is None:
            fee = "0.1"
        
        logger.info("transferring_tokens",
                   from_node=from_node_id,
                   from_wallet=from_wallet,
                   to_address=to_address[:16],
                   amount=amount,
                   token=token,
                   fee=fee,
                   chain=chain)
        
        try:
            # CRITICAL: SDK's dap_chain_balance_scan may not parse scientific notation correctly
            # Convert scientific notation to full datoshi value if needed
            amount_value = amount
            if 'e+' in amount.lower() or 'e-' in amount.lower():
                # Try to convert scientific notation to full number
                try:
                    amount_decimal = decimal.Decimal(amount)
                    # Convert to datoshi (full integer value)
                    amount_value = str(int(amount_decimal))
                    logger.info("converted_scientific_notation_to_datoshi",
                              original=amount,
                              converted=amount_value[:50] + "..." if len(amount_value) > 50 else amount_value,
                              converted_length=len(amount_value))
                except Exception as conv_err:
                    logger.warning("failed_to_convert_scientific_notation",
                                 amount=amount,
                                 error=str(conv_err),
                                 note="Using original value - SDK may parse it incorrectly")
            
            # CRITICAL: Convert fee to datoshi (SDK's dap_chain_balance_scan expects datoshi)
            # Fee can be in format "0.1" (tokens) or "0.1e+18" (scientific notation) or datoshi string
            fee_value = fee
            if fee:
                try:
                    # Check if fee is already in datoshi format (large integer string)
                    if fee.isdigit() and len(fee) >= 15:  # Likely already in datoshi
                        fee_value = fee
                        logger.debug("fee_already_in_datoshi_format", fee=fee)
                    else:
                        # Try to parse as decimal and convert to datoshi
                        fee_decimal = decimal.Decimal(fee)
                        # If fee is less than 1e+12, assume it's in token units (e.g., "0.1" = 0.1 tokens)
                        # Convert to datoshi: 0.1 tokens = 0.1e+18 datoshi
                        if fee_decimal < decimal.Decimal("1e+12"):
                            fee_decimal = fee_decimal * decimal.Decimal("1e+18")
                        
                        fee_value = str(int(fee_decimal))
                        logger.info("converted_fee_to_datoshi",
                                  original=fee,
                                  converted=fee_value[:50] + "..." if len(fee_value) > 50 else fee_value,
                                  converted_length=len(fee_value),
                                  note="Fee converted to datoshi for SDK")
                except Exception as conv_err:
                    logger.warning("failed_to_convert_fee_to_datoshi",
                                 fee=fee,
                                 error=str(conv_err),
                                 note="Using original fee value - SDK may parse it incorrectly")
            
            # Always pass -fee parameter (required by SDK)
            command = (
                f"tx create -net {self.network_name} -chain {chain} -token {token} "
                f"-from_wallet {from_wallet} -value {amount_value} -to_addr {to_address} -fee {fee_value}"
            )
            
            logger.info("tx_create_command_transfer_from_wallet",
                        command=command,
                        original_amount=amount,
                        converted_amount=amount_value,
                        original_fee=fee,
                        converted_fee=fee_value,
                        note="Full command for tx_create from wallet - check if conversion was applied")
            
            exit_code, stdout, stderr = self._exec_cli(from_node_id, command, check_output=False)
            
            # Log full output for debugging
            logger.info("tx_create_output_transfer_from_wallet",
                        exit_code=exit_code,
                        stdout=stdout[:1000] if stdout else "empty",
                        stderr=stderr[:1000] if stderr else "empty",
                        note="Full tx_create output for debugging - check if transaction was created with correct amount")
            
            # CRITICAL: Check for transfer: False in output (SDK returns this when transaction creation fails)
            if "transfer: False" in stdout or "transfer: False" in stderr:
                # Extract error details from stderr or stdout
                error_details = stderr if stderr else stdout
                
                # CRITICAL DIAGNOSTIC: Check wallet balance and UTXO availability before failing
                logger.error("transfer_failed_sdk_returned_false_diagnostic",
                           from_node=from_node_id,
                           from_wallet=from_wallet,
                           to_address=to_address[:16],
                           amount=amount,
                           chain=chain,
                           stdout=stdout[:500],
                           stderr=stderr[:500] if stderr else "none",
                           note="SDK returned transfer: False - checking wallet balance and UTXO availability")
                
                # Check wallet balance on the specified chain
                try:
                    exit_code_balance, stdout_balance, stderr_balance = self._exec_cli(
                        from_node_id,
                        f"wallet info -w {from_wallet} -net {self.network_name} -chain {chain}",
                        check_output=False
                    )
                    
                    logger.error("wallet_balance_check_on_transfer_failure",
                               wallet=from_wallet,
                               chain=chain,
                               exit_code=exit_code_balance,
                               stdout=stdout_balance[:1000] if stdout_balance else "empty",
                               stderr=stderr_balance[:500] if stderr_balance else "empty",
                               note="Wallet balance check - SDK may not find UTXO even if balance exists")
                    
                    # DIAGNOSTIC: Check transaction history (may be empty if PVT(a_dag)->datums not populated)
                    # NOTE: For checking specific transactions, use LedgerTransactionChecker with datum_hash
                    # tx_history depends on PVT(a_dag)->datums which may not be populated after snapshot restore
                    # WORKAROUND: Use -head flag to force forward iteration (get_first/get_next)
                    # because DAG chains don't implement get_last/get_prev callbacks
                    from_addr = await self.get_wallet_address(from_node_id, from_wallet)
                    exit_code_tx_hist, stdout_tx_hist, _ = self._exec_cli(
                        from_node_id,
                        f"tx_history -addr {from_addr} -net {self.network_name} -chain {chain} -limit 5 -head",
                        check_output=False
                    )
                    
                    logger.error("tx_history_check_on_transfer_failure_diagnostic",
                               wallet=from_wallet,
                               addr=from_addr[:16],
                               chain=chain,
                               exit_code=exit_code_tx_hist,
                               stdout=stdout_tx_hist[:1000] if stdout_tx_hist else "empty",
                               note="Transaction history check (diagnostic - may be empty if PVT(a_dag)->datums not populated). "
                                    "For reliable transaction checks, use LedgerTransactionChecker with specific datum_hash")
                    
                except Exception as diag_err:
                    logger.warning("diagnostic_check_failed", error=str(diag_err)[:200])
                
                logger.error("transfer_failed_sdk_returned_false",
                           from_node=from_node_id,
                           from_wallet=from_wallet,
                           to_address=to_address[:16],
                           amount=amount,
                           stdout=stdout[:500],
                           stderr=stderr[:500] if stderr else "none")
                raise RuntimeError(
                    f"SDK returned 'transfer: False' - transaction creation failed. "
                    f"Possible causes: insufficient funds in wallet '{from_wallet}', "
                    f"UTXO not indexed in ledger for chain '{chain}', emission not processed, or wallet not found. "
                    f"Stdout: {stdout[:300]}, Stderr: {stderr[:300] if stderr else 'none'}"
                )
            
            if exit_code != 0:
                raise RuntimeError(f"tx_create failed: exit_code={exit_code}, stderr={stderr}, stdout={stdout[:200]}")
            
            # Parse transaction hash from output
            hash_match = re.search(r'(0x[a-fA-F0-9]{64})', stdout)
            if hash_match:
                tx_hash = hash_match.group(1)
                logger.info("transfer_created",
                          tx_hash=tx_hash[:16],
                          from_node=from_node_id,
                          to_address=to_address[:16])
                return tx_hash
            else:
                raise RuntimeError(f"Failed to parse transaction hash from output: {stdout[:200]}")
                
        except Exception as e:
            logger.error("transfer_failed",
                       from_node=from_node_id,
                       to_address=to_address[:16],
                       error=str(e))
            raise RuntimeError(f"Failed to transfer {amount} {token} from node {from_node_id} to {to_address}: {e}") from e
    
    async def transfer_tokens_from_emission(
        self,
        from_node_id: int,
        emission_hash: str,
        to_address: str,
        amount: str,
        token: str = "TCELL",
        cert_name: str = "pvt.stagenet.root.0",
        fee: Optional[str] = None,
        chain: str = "main"
    ) -> str:
        """
        Transfer tokens from emission hash to address.
        Uses -from_emission instead of -from_wallet for direct emission transfer.
        
        Args:
            from_node_id: Source node ID
            emission_hash: Emission transaction hash
            to_address: Destination address
            amount: Amount to transfer (e.g., "100.0" or "1.0e+18")
            token: Token ticker (default: TCELL)
            cert_name: Certificate name for signing (default: root cert)
            fee: Transaction fee (optional, default: "0.1" in token units)
            chain: Chain name (default: "main")
            
        Returns:
            Transaction hash
            
        Raises:
            RuntimeError: If transfer fails
        """
        # CRITICAL: SDK requires -fee parameter for tx_create
        if fee is None:
            fee = "0.1"
        
        logger.info("transferring_tokens_from_emission",
                   from_node=from_node_id,
                   emission=emission_hash[:16],
                   to_address=to_address[:16],
                   amount=amount,
                   token=token,
                   fee=fee,
                   chain=chain)
        
        try:
            # CRITICAL: When using -from_emission, must specify -chain_emission to indicate where emission is located
            # If chain is zerochain, emission is also on zerochain
            emission_chain = chain  # Emission is on the same chain as the transaction
            
            # Use -from_emission instead of -from_wallet (direct emission transfer)
            # SDK requires -chain_emission when using -from_emission (line 6988-6998)
            # CRITICAL: SDK's dap_chain_balance_scan may not parse scientific notation correctly
            # Convert scientific notation to full datoshi value if needed
            amount_value = amount
            if 'e+' in amount.lower() or 'e-' in amount.lower():
                # Try to convert scientific notation to full number
                try:
                    amount_decimal = decimal.Decimal(amount)
                    # Convert to datoshi (full integer value)
                    amount_value = str(int(amount_decimal))
                    logger.info("converted_scientific_notation_to_datoshi",
                              original=amount,
                              converted=amount_value[:50] + "..." if len(amount_value) > 50 else amount_value,
                              converted_length=len(amount_value))
                except Exception as conv_err:
                    logger.warning("failed_to_convert_scientific_notation",
                                 amount=amount,
                                 error=str(conv_err),
                                 note="Using original value - SDK may parse it incorrectly")
            
            # CRITICAL: Convert fee to datoshi (SDK's dap_chain_balance_scan expects datoshi)
            # Fee can be in format "0.1" (tokens) or "0.1e+18" (scientific notation) or datoshi string
            fee_value = fee
            if fee:
                try:
                    # Check if fee is already in datoshi format (large integer string)
                    if fee.isdigit() and len(fee) >= 15:  # Likely already in datoshi
                        fee_value = fee
                        logger.debug("fee_already_in_datoshi_format", fee=fee)
                    else:
                        # Try to parse as decimal and convert to datoshi
                        fee_decimal = decimal.Decimal(fee)
                        # If fee is less than 1e+12, assume it's in token units (e.g., "0.1" = 0.1 tokens)
                        # Convert to datoshi: 0.1 tokens = 0.1e+18 datoshi
                        if fee_decimal < decimal.Decimal("1e+12"):
                            fee_decimal = fee_decimal * decimal.Decimal("1e+18")
                        
                        fee_value = str(int(fee_decimal))
                        logger.info("converted_fee_to_datoshi",
                                  original=fee,
                                  converted=fee_value[:50] + "..." if len(fee_value) > 50 else fee_value,
                                  converted_length=len(fee_value),
                                  note="Fee converted to datoshi for SDK")
                except Exception as conv_err:
                    logger.warning("failed_to_convert_fee_to_datoshi",
                                 fee=fee,
                                 error=str(conv_err),
                                 note="Using original fee value - SDK may parse it incorrectly")
            
            command = (
                f"tx create -net {self.network_name} -chain {chain} -token {token} "
                f"-from_emission {emission_hash} -chain_emission {emission_chain} "
                f"-value {amount_value} -to_addr {to_address} -cert {cert_name} -fee {fee_value}"
            )
            
            logger.info("tx_create_command",
                        command=command,
                        original_amount=amount,
                        converted_amount=amount_value,
                        original_fee=fee,
                        converted_fee=fee_value,
                        note="Full command for tx_create - check if conversion was applied")
            
            exit_code, stdout, stderr = self._exec_cli(from_node_id, command, check_output=False)
            
            # Log full output for debugging
            logger.info("tx_create_output",
                        exit_code=exit_code,
                        stdout=stdout[:1000] if stdout else "empty",
                        stderr=stderr[:1000] if stderr else "empty",
                        note="Full tx_create output for debugging - check if transaction was created with correct amount")
            
            # CRITICAL: Check for emission: False or transfer: False in output
            if "emission: False" in stdout or "emission: False" in stderr:
                logger.error("transfer_from_emission_failed_sdk_returned_false",
                           from_node=from_node_id,
                           emission=emission_hash[:16],
                           to_address=to_address[:16],
                           amount=amount,
                           stdout=stdout[:500],
                           stderr=stderr[:500] if stderr else "none")
                
                # CRITICAL DIAGNOSTIC: Check if emission is actually in ledger
                # SDK's dap_chain_mempool_base_tx_create (line 1202) calls dap_ledger_token_emission_find
                # If emission is not found, it returns NULL -> "emission: False" error
                # 
                # dap_ledger_token_emission_find (line 3474) searches in network ledger across all chains
                # It iterates through all tokens and looks for emission hash in each token's emissions
                # If emission is not found, it returns NULL
                #
                # Possible causes:
                # 1. Emission not in ledger (but this shouldn't happen if emission is in DAG events)
                # 2. Emission hash mismatch (emission hash doesn't match what's in ledger)
                # 3. Emission on different chain (but ledger should contain emissions from all chains)
                # 4. Token not found (but TCELL should exist if emission was created)
                logger.error("emission_not_found_in_ledger_diagnostic",
                           emission=emission_hash[:16],
                           chain=emission_chain,
                           from_node=from_node_id,
                           note="SDK failed to find emission in ledger via dap_ledger_token_emission_find. "
                                "SDK searches in network ledger (contains emissions from all chains). "
                                "If emission is in DAG events, it MUST be in ledger. "
                                "Possible causes: emission hash mismatch, token not found, or emission not processed from DAG events.")
                
                # Try to verify emission via CLI to get more diagnostics
                logger.info("collecting_diagnostic_info_for_emission_failure",
                           emission=emission_hash[:16],
                           chain=emission_chain)
                try:
                    # Check if token exists
                    exit_code_token, stdout_token, _ = self._exec_cli(
                        from_node_id,
                        f"token show -net {self.network_name} -token {token}",
                        check_output=False
                    )
                    logger.error("token_show_diagnostic",
                                emission=emission_hash[:16],
                                exit_code=exit_code_token,
                                output=stdout_token[:500] if stdout_token else "empty",
                                note="Token should exist if emission was created")
                    
                    # Check if emission is in DAG events
                    exit_code_dag, stdout_dag, _ = self._exec_cli(
                        from_node_id,
                        f"dag event find -net {self.network_name} -chain {emission_chain} -datum {emission_hash}",
                        check_output=False
                    )
                    logger.error("dag_event_find_diagnostic",
                                emission=emission_hash[:16],
                                exit_code=exit_code_dag,
                                output=stdout_dag[:500] if stdout_dag else "empty",
                                note="Emission should be in DAG events if it was processed")
                except Exception as diag_err:
                    logger.debug("diagnostic_collection_failed", error=str(diag_err)[:100])
                
                raise RuntimeError(
                    f"SDK returned 'emission: False' - transaction creation failed. "
                    f"SDK's dap_chain_mempool_base_tx_create requires emission in ledger (line 1202 calls dap_ledger_token_emission_find). "
                    f"Emission hash: {emission_hash[:16]}, chain: {emission_chain}. "
                    f"Possible causes: emission not found in ledger (not processed from DAG events after restart), "
                    f"emission already spent, or mempool cannot place TX datum. "
                    f"Stdout: {stdout[:300]}, Stderr: {stderr[:300] if stderr else 'none'}"
                )
            
            if "transfer: False" in stdout or "transfer: False" in stderr:
                logger.error("transfer_from_emission_failed_sdk_returned_false",
                           from_node=from_node_id,
                           emission=emission_hash[:16],
                           to_address=to_address[:16],
                           amount=amount,
                           stdout=stdout[:500],
                           stderr=stderr[:500] if stderr else "none")
                raise RuntimeError(
                    f"SDK returned 'transfer: False' - transaction creation failed. "
                    f"Possible causes: emission hash not found, emission already spent, "
                    f"or invalid parameters. Stdout: {stdout[:300]}, Stderr: {stderr[:300] if stderr else 'none'}"
                )
            
            if exit_code != 0:
                raise RuntimeError(f"tx_create failed: exit_code={exit_code}, stderr={stderr}, stdout={stdout[:200]}")
            
            # Parse transaction hash from output
            hash_match = re.search(r'(0x[a-fA-F0-9]{64})', stdout)
            if hash_match:
                tx_hash = hash_match.group(1)
                logger.info("transfer_from_emission_created",
                          tx_hash=tx_hash[:16],
                          from_node=from_node_id,
                          to_address=to_address[:16])
                return tx_hash
            else:
                raise RuntimeError(f"Failed to parse transaction hash from output: {stdout[:200]}")
                
        except Exception as e:
            logger.error("transfer_from_emission_failed",
                       from_node=from_node_id,
                       to_address=to_address[:16],
                       error=str(e))
            raise RuntimeError(f"Failed to transfer {amount} {token} from emission {emission_hash[:16]} to {to_address}: {e}") from e
    
    async def delegate_key_via_stake(
        self,
        node_id: int,
        wallet_name: str,
        amount: str,
        cert_name: str,
        fee: Optional[str] = None,
        chain: str = "main"
    ) -> str:
        """
        Delegate key via stake service.
        
        Args:
            node_id: Node ID
            wallet_name: Wallet name for staking
            amount: Stake amount (e.g., "100.0" or "1.0e+18")
            cert_name: Certificate name for signing
            fee: Transaction fee (optional, default: "0.1" in token units)
            chain: Chain name (not used directly, SDK selects chain automatically)
            
        Returns:
            Transaction hash
            
        Raises:
            RuntimeError: If delegation fails
        """
        # CRITICAL: SDK requires -fee parameter for srv_stake delegate (line 2406-2410)
        # Default fee is 0.1 tokens
        if fee is None:
            fee = "0.1"
        
        logger.info("delegating_key_via_stake",
                   node_id=node_id,
                   wallet_name=wallet_name,
                   amount=amount,
                   cert_name=cert_name,
                   fee=fee)
        
        try:
            # Get node address
            node_addr = await self._read_node_addr_with_retry(node_id, self.network_name)
            
            # Delegate key using srv_stake delegate command (like tests-in-docker)
            # CRITICAL: -fee is REQUIRED by SDK (line 2406-2410 in dap_chain_net_srv_stake_pos_delegate.c)
            command = (
                f"srv_stake delegate -net {self.network_name} "
                f"-w {wallet_name} -value {amount} -cert {cert_name} "
                f"-node_addr {node_addr} -fee {fee}"
            )
            
            exit_code, stdout, stderr = self._exec_cli(node_id, command, check_output=False)
            
            if exit_code != 0:
                raise RuntimeError(f"srv_stake delegate failed: exit_code={exit_code}, stderr={stderr}")
            
            # Parse transaction hash from output
            import re
            hash_match = re.search(r'(0x[a-fA-F0-9]{64})', stdout)
            if hash_match:
                tx_hash = hash_match.group(1)
                logger.info("key_delegated_via_stake",
                           node_id=node_id,
                           wallet_name=wallet_name,
                           cert_name=cert_name,
                           tx_hash=tx_hash[:16])
                return tx_hash
            else:
                logger.warning("key_delegation_successful_but_no_hash_found",
                             node_id=node_id,
                             stdout_preview=stdout[:200])
                return ""  # Return empty string if no hash found
                
        except Exception as e:
            logger.error("key_delegation_failed",
                       node_id=node_id,
                       wallet_name=wallet_name,
                       error=str(e))
            raise RuntimeError(f"Failed to delegate key for node {node_id} with wallet {wallet_name}: {e}") from e

