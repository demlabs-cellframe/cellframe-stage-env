from typing import List, Dict, Any, Union
import re
from pathlib import Path

from src.utils.logger import get_logger
from .base import StepExecutor
from src.scenarios.schema_config import ConfigStep
from src.scenarios.executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class ConfigStepExecutor(StepExecutor):
    """Executor for configuration regeneration steps."""
    
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
        
    async def execute(self, step: ConfigStep, ctx: RuntimeContext) -> None:
        """Execute config regeneration step."""
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
            
        logger.info(f"Config: regenerating '{step.config}' for nodes {node_ids} with vars {list(variables.keys())}")
        
        # 3. Regenerate
        await self._regenerate_config(node_ids, ctx.substitute(step.config), variables)
        
        ctx.add_result("config", True, {"name": step.config, "nodes": node_ids})

    def _parse_set_string(self, set_str: str) -> Dict[str, Any]:
        """Parse 'key=value, key2="value 2"' string."""
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
                # Try to cast to appropriate types
                if v.lower() == 'true':
                    v = True
                elif v.lower() == 'false':
                    v = False
                elif v.isdigit():
                    v = int(v)
                context[k] = v
        return context
