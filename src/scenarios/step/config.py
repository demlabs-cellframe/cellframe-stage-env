from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Union
import re
from pathlib import Path

from src.utils.logger import get_logger
from .base import StepExecutor
from src.scenarios.schema_config import ConfigStep, GenConfigStep
from src.scenarios.executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

# Forward declaration for type hinting
class ConfigStepExecutorBase(StepExecutor):
    pass

class ConfigActionHandler(ABC):
    """Abstract base class for configuration action handlers."""
    
    def __init__(self, executor: 'ConfigStepExecutor'):
        # print(f"DEBUG: ConfigActionHandler init called with executor={executor}")
        self.executor = executor
        
    @abstractmethod
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        """Handle specific configuration action."""
        pass

class SetGenesisHandler(ConfigActionHandler):
    """Handler for 'set_genesis' action."""
    
    def __init__(self, executor):
        super().__init__(executor)

    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.chain or not step.hash:
            raise ScenarioExecutionError("chain and hash required for set_genesis", step=step)
        
        chain_name = ctx.substitute(step.chain)
        genesis_hash = ctx.substitute(step.hash)
        
        await self.executor._update_static_genesis(node_ids, chain_name, genesis_hash)

class SetFeeAddrHandler(ConfigActionHandler):
    """Handler for 'set_fee_addr' action."""

    def __init__(self, executor):
        super().__init__(executor)
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.value:
            raise ScenarioExecutionError("value (fee_addr) required for set_fee_addr", step=step)
        
        fee_addr = ctx.substitute(step.value)
        await self.executor._update_fee_addr(node_ids, fee_addr)

class DisableSeedModeHandler(ConfigActionHandler):
    """Handler for 'disable_seed_mode' action."""

    def __init__(self, executor):
        super().__init__(executor)
    
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

    def __init__(self, executor):
        super().__init__(executor)
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not hasattr(ctx, 'genesis_config_manager') or not ctx.genesis_config_manager:
             raise ScenarioExecutionError("GenesisConfigManager required for enable_seed_mode", step=step)
        
        ctx.genesis_config_manager.enable_seed_mode_in_configs(node_ids)

class UpdateHandler(ConfigActionHandler):
    """Handler for generic 'update' action."""

    def __init__(self, executor):
        super().__init__(executor)
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if not step.file or not step.key or step.value is None:
            raise ScenarioExecutionError("file, key, value required for update", step=step)
        
        # Implementation placeholder
        raise ScenarioExecutionError("update action not yet implemented", step=step)

class SetMinimumFeeHandler(ConfigActionHandler):
    """Handler for 'set_minimum_fee' action."""

    def __init__(self, executor):
        super().__init__(executor)
    
    async def handle(self, step: ConfigStep, ctx: RuntimeContext, node_ids: List[int]) -> None:
        if step.value is None:
            raise ScenarioExecutionError("value (minimum_fee) required for set_minimum_fee", step=step)
        
        minimum_fee = ctx.substitute(str(step.value))
        await self.executor._update_minimum_fee(node_ids, minimum_fee)


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
        # print(f"DEBUG: ConfigStepExecutor init called. Self is {self}")
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.base_path = container_manager.base_path
        
        # Register handlers
        # print("DEBUG: Creating handlers...")
        self.handlers: Dict[str, ConfigActionHandler] = {
            'set_genesis': SetGenesisHandler(self),
            'set_fee_addr': SetFeeAddrHandler(self),
            'disable_seed_mode': DisableSeedModeHandler(self),
            'enable_seed_mode': EnableSeedModeHandler(self),
            'update': UpdateHandler(self),
            'set_minimum_fee': SetMinimumFeeHandler(self),
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
        
        from src.config.manager import get_config_loader
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
        from src.config.manager import get_config_loader
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

    async def _update_minimum_fee(self, node_ids: List[int], minimum_fee: str):
        """Update minimum_fee in main.cfg."""
        from src.config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../testing/cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        for node_id in node_ids:
            try:
                config_file = cache_dir / "configs" / f"node{node_id}" / "network" / "stagenet" / "main.cfg"
                if not config_file.exists():
                    logger.warning(f"Config not found for node{node_id}: {config_file}")
                    continue
                    
                content = config_file.read_text()
                pattern = re.compile(r"^minimum_fee=.*", re.MULTILINE)
                if pattern.search(content):
                    content = pattern.sub(f"minimum_fee={minimum_fee}", content)
                else:
                    if "[esbocs]" not in content:
                        content += "\n[esbocs]\n"
                    content += f"minimum_fee={minimum_fee}\n"
                    
                config_file.write_text(content)
                logger.info(f"Updated minimum_fee={minimum_fee} for node{node_id}")
                
            except Exception as e:
                logger.error(f"Failed to update minimum_fee for node{node_id}: {e}")
                raise


class GenConfigStepExecutor(StepExecutor):
    """Executor for generation-based config steps."""
    
    def __init__(self, container_manager, log_file=None, debug=False, resolve_node_alias_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.base_path = container_manager.base_path
        
    async def execute(self, step: GenConfigStep, ctx: RuntimeContext) -> None:
        """Execute gen_config step."""
        # 1. Resolve nodes
        nodes_list = step.nodes if isinstance(step.nodes, list) else [step.nodes]
        node_ids = []
        for node_alias in nodes_list:
            resolved = ctx.substitute(node_alias)
            if self.resolve_node_alias_callback:
                resolved = self.resolve_node_alias_callback(resolved)
            
            # Extract ID logic
            match = re.search(r'(?:node|root|master|full)-?(\d+)', resolved)
            if match:
                node_ids.append(int(match.group(1)))
            else:
                logger.warning(f"Could not parse node ID from {resolved}")

        if not node_ids:
            raise ScenarioExecutionError(f"No valid nodes resolved from {step.nodes}", step=step)

        # 2. Parse variables
        if isinstance(step.set, dict):
            variables = {k: ctx.substitute(str(v)) for k, v in step.set.items()}
        else:
            variables = self._parse_set_string(ctx.substitute(step.set))
            
        logger.info(f"GenConfig: regenerating '{step.name}' for nodes {node_ids} with vars {list(variables.keys())}")
        
        # 3. Regenerate
        await self._regenerate_config(node_ids, ctx.substitute(step.name), variables)
        
        ctx.add_result("gen_config", True, {"name": step.name, "nodes": node_ids})

    def _parse_set_string(self, set_str: str) -> Dict[str, Any]:
        """Parse 'key=value, key2="value 2"' string."""
        # Simple split by comma is dangerous if values contain commas.
        # This is a basic implementation. For complex cases, use Dict in YAML.
        result = {}
        parts = set_str.split(',')
        for part in parts:
            if '=' in part:
                k, v = part.split('=', 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                result[k] = v
        return result

    async def _regenerate_config(self, node_ids: List[int], config_name: str, variables: Dict[str, Any]):
        """
        Regenerate config file from template, merging existing config values with new variables.
        """
        from src.config.manager import get_config_loader
        from src.config.generator import ConfigGenerator
        
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../testing/cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        # Initialize generator to access templates
        generator = ConfigGenerator(self.base_path, config_loader.config_path)
        
        # Determine template path based on config_name
        # config_name e.g. "cellframe-node" or "stagenet/zerochain"
        
        # Mapping heuristic
        if '/' in config_name:
            # "stagenet/zerochain" -> chains template
            # Assumes generic template "chains/{chain}.cfg.j2" exists? 
            # Or "chains/main.cfg.j2".
            # Actually stage-env uses "chains/chain_name.cfg.j2" usually.
            parts = config_name.split('/')
            network = parts[0]
            chain_file = parts[1] # e.g. "zerochain"
            template_name = f"chains/{chain_file}.cfg.j2"
            is_chain = True
        else:
            # "cellframe-node" -> base template
            template_name = f"base/{config_name}.cfg.j2"
            is_chain = False
            
        # Verify template exists
        template_path = generator.templates_dir / template_name
        if not template_path.exists():
             # Fallback: try direct name
             template_path = generator.templates_dir / f"{config_name}.cfg.j2"
             if not template_path.exists():
                 raise RuntimeError(f"Template not found for {config_name}: tried {template_name} and {config_name}.cfg.j2")
        
        # Load template
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(generator.templates_dir)))
        template = env.get_template(str(template_path.relative_to(generator.templates_dir)))

        for node_id in node_ids:
            # 1. Determine target file path
            node_dir = cache_dir / "configs" / f"node{node_id}"
            if is_chain:
                # network/stagenet/chain.cfg
                # We assume network name is in config_name parts[0]
                target_file = node_dir / "network" / parts[0] / f"{parts[1]}.cfg"
            else:
                target_file = node_dir / f"{config_name}.cfg"
                
            if not target_file.exists():
                logger.warning(f"Target config file {target_file} does not exist, skipping regeneration for node {node_id}")
                continue

            # 2. Read existing file and extract key-values (Mock context)
            existing_content = target_file.read_text()
            current_context = self._extract_context_from_ini(existing_content)
            
            # 3. Merge with provided variables
            # Note: provided variables override existing file content
            full_context = {**current_context, **variables}
            
            # 4. Render
            try:
                rendered = template.render(full_context)
                target_file.write_text(rendered)
                logger.info(f"Regenerated {target_file.name} for node {node_id}")
            except Exception as e:
                logger.error(f"Failed to render template for node {node_id}: {e}")
                raise

    def _extract_context_from_ini(self, content: str) -> Dict[str, Any]:
        """
        Extract key=value pairs from INI-like content to recreate a context.
        This is a heuristic method.
        """
        context = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('['):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                # Try to cast to appropriate types if possible?
                # Jinja expects strings usually, or booleans
                if v.lower() == 'true':
                    v = True
                elif v.lower() == 'false':
                    v = False
                elif v.isdigit():
                    v = int(v)
                context[k] = v
        return context
