from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import re
from pathlib import Path

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema_config import ConfigStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

# Forward declaration for type hinting
class ConfigStepExecutorBase(StepExecutor):
    pass

class ConfigActionHandler(ABC):
    """Abstract base class for configuration action handlers."""
    
    def __init__(self, executor: 'ConfigStepExecutor'):
        self.executor = executor
        
    @abstractmethod
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        """Handle specific configuration action."""
        pass

class SetGenesisHandler(ConfigActionHandler):
    """Handler for 'set_genesis' action."""
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.chain or not step.hash:
            raise ScenarioExecutionError("chain and hash required for set_genesis", step=step)
        
        chain_name = ctx.substitute(step.chain)
        genesis_hash = ctx.substitute(step.hash)
        
        await self.executor._update_static_genesis(node_ids, chain_name, genesis_hash)

class SetFeeAddrHandler(ConfigActionHandler):
    """Handler for 'set_fee_addr' action."""
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.value:
            raise ScenarioExecutionError("value (fee_addr) required for set_fee_addr", step=step)
        
        fee_addr = ctx.substitute(step.value)
        await self.executor._update_fee_addr(node_ids, fee_addr)

class DisableSeedModeHandler(ConfigActionHandler):
    """Handler for 'disable_seed_mode' action."""
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not hasattr(ctx, 'genesis_config_manager') or not ctx.genesis_config_manager:
             raise ScenarioExecutionError("GenesisConfigManager required for disable_seed_mode", step=step)
        
        mgr = ctx.genesis_config_manager
        
        # Resolve optional parameters
        z_hash = ctx.substitute(step.zerochain_genesis_hash) if step.zerochain_genesis_hash else None
        m_hash = ctx.substitute(step.main_genesis_hash) if step.main_genesis_hash else None
        fee = ctx.substitute(step.fee_addr) if step.fee_addr else None
        
        if z_hash or m_hash or fee:
            mgr.disable_seed_mode_in_configs_with_genesis_hash(
                node_ids,
                zerochain_genesis_hash=z_hash,
                mainchain_genesis_hash=m_hash,
                fee_addr=fee
            )
        else:
            mgr.disable_seed_mode_in_configs(node_ids)

class EnableSeedModeHandler(ConfigActionHandler):
    """Handler for 'enable_seed_mode' action."""
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not hasattr(ctx, 'genesis_config_manager') or not ctx.genesis_config_manager:
             raise ScenarioExecutionError("GenesisConfigManager required for enable_seed_mode", step=step)
        
        ctx.genesis_config_manager.enable_seed_mode_in_configs(node_ids)

class UpdateHandler(ConfigActionHandler):
    """Handler for generic 'update' action."""
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.file or not step.key or step.value is None:
            raise ScenarioExecutionError("file, key, value required for update", step=step)
        
        # Implementation placeholder
        raise ScenarioExecutionError("update action not yet implemented", step=step)


class ConfigStepExecutor(StepExecutor):
    """Executor for configuration management steps."""
    
    def __init__(
        self, 
        container_manager, 
        log_file=None, 
        debug=False,
        resolve_node_alias_callback=None
    ):
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.base_path = container_manager.base_path
        
        # Register handlers
        self.handlers: Dict[str, ConfigActionHandler] = {
            'set_genesis': SetGenesisHandler(self),
            'set_fee_addr': SetFeeAddrHandler(self),
            'disable_seed_mode': DisableSeedModeHandler(self),
            'enable_seed_mode': EnableSeedModeHandler(self),
            'update': UpdateHandler(self),
        }
        
    async def execute(self, step: ConfigStep, ctx: RuntimeContext) -> None:
        """Execute configuration step."""
        # Resolve nodes
        nodes_list = step.nodes if isinstance(step.nodes, list) else [step.nodes]
        node_ids = []
        
        for node_alias in nodes_list:
            resolved = ctx.substitute(node_alias)
            if self.resolve_node_alias_callback:
                resolved = self.resolve_node_alias_callback(resolved)
            
            # Extract ID
            if resolved.startswith("node") and len(resolved) > 4:
                try:
                    nid = int(resolved[4:])
                    node_ids.append(nid)
                except ValueError:
                    logger.warning(f"Could not parse node ID from {resolved}")
            elif resolved.startswith("node-"):
                try:
                    nid = int(resolved[5:])
                    node_ids.append(nid)
                except ValueError:
                    logger.warning(f"Could not parse node ID from {resolved}")
            else:
                logger.warning(f"Unknown node format: {resolved}")

        if not node_ids:
            raise ScenarioExecutionError(f"No valid nodes resolved from {step.nodes}", step=step)
            
        logger.info(f"Config action '{step.config}' on nodes {node_ids}")
        
        # Dispatch to handler
        handler = self.handlers.get(step.config)
        if not handler:
            raise ScenarioExecutionError(f"Unknown config action: {step.config}", step=step)
            
        await handler.handle(step, ctx, node_ids)
        
        ctx.add_result("config", True, {"action": step.config, "nodes": node_ids})

    async def _update_static_genesis(self, node_ids: List[int], chain_name: str, genesis_hash: str):
        """Update static_genesis_* in chain config."""
        is_dag = chain_name.lower() in ["zerochain", "zero", "0"]
        param_name = "static_genesis_event" if is_dag else "static_genesis_block"
        
        from ..config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../testing/cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        for node_id in node_ids:
            try:
                config_file = cache_dir / "configs" / f"node{node_id}" / "network" / "stagenet" / f"{chain_name}.cfg"
                if not config_file.exists():
                    logger.warning(f"Config not found: {config_file}")
                    continue
                    
                content = config_file.read_text()
                section_name = "[dag]" if is_dag else "[blocks]"
                
                if section_name not in content:
                    content += f"\n{section_name}\n"
                
                # Update hash
                pattern = re.compile(f"^{re.escape(param_name)}=.*", re.MULTILINE)
                if pattern.search(content):
                    content = pattern.sub(f"{param_name}={genesis_hash}", content)
                else:
                    content += f"{param_name}={genesis_hash}\n"
                
                # Enable flag
                flag_name = "is_static_genesis_event" if is_dag else "is_static_genesis_block"
                flag_pattern = re.compile(f"^{re.escape(flag_name)}=.*", re.MULTILINE)
                if flag_pattern.search(content):
                    content = flag_pattern.sub(f"{flag_name}=true", content)
                else:
                    content += f"{flag_name}=true\n"
                    
                config_file.write_text(content)
                logger.info(f"Updated {param_name} for node{node_id} on chain {chain_name}")
                
            except Exception as e:
                logger.error(f"Failed to update genesis for node{node_id}: {e}")
                raise

    async def _update_fee_addr(self, node_ids: List[int], fee_addr: str):
        """Update fee_addr in main.cfg."""
        from ..config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../testing/cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        for node_id in node_ids:
            try:
                config_file = cache_dir / "configs" / f"node{node_id}" / "network" / "stagenet" / "main.cfg"
                if not config_file.exists():
                    continue
                    
                content = config_file.read_text()
                pattern = re.compile(r"^fee_addr=.*", re.MULTILINE)
                if pattern.search(content):
                    content = pattern.sub(f"fee_addr={fee_addr}", content)
                else:
                    if "[esbocs]" not in content:
                        content += "\n[esbocs]\n"
                    content += f"fee_addr={fee_addr}\n"
                    
                config_file.write_text(content)
                logger.info(f"Updated fee_addr for node{node_id}")
                
            except Exception as e:
                logger.error(f"Failed to update fee_addr for node{node_id}: {e}")
                raise
