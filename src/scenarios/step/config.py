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
        
    def _expand_nodes_list(self, nodes, ctx) -> list:
        """Expand nodes that can be a template string or list."""
        if isinstance(nodes, str):
            # Template string like "{{all_nodes}}" - substitute and parse
            expanded = ctx.substitute(nodes)
            if expanded.startswith('[') and expanded.endswith(']'):
                import ast
                try:
                    return ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    return [expanded]
            else:
                return [s.strip() for s in expanded.split(',') if s.strip()]
        return list(nodes)
    
    async def execute(self, step: ConfigStep, ctx: RuntimeContext) -> None:
        """Execute config regeneration step."""
        # 1. Resolve nodes (can be template string like "{{all_nodes}}")
        nodes_list = self._expand_nodes_list(step.nodes, ctx)
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
        
        # Get network_name from context for dynamic template resolution
        network_name = ctx.variables.get('network_name', 'stagenet')
        
        # 3. Regenerate
        await self._regenerate_config(node_ids, ctx.substitute(step.config), variables, network_name)
        
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

    async def _regenerate_config(self, node_ids: List[int], config_name: str, variables: Dict[str, Any], network_name: str = "stagenet"):
        """
        Regenerate config file from template, merging existing config values with new variables.
        
        Args:
            node_ids: List of node IDs to regenerate config for
            config_name: Config name (e.g. "cellframe-node", "stagenet", "stagenet/zerochain")
            variables: Variables to set in the config
            network_name: Network name from context (used for dynamic template resolution)
        """
        from src.config.manager import get_config_loader
        from src.config.generator import ConfigGenerator
        
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../../cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        # Initialize generator to access templates
        generator = ConfigGenerator(self.base_path, config_loader.config_path)
        
        # cfg.d snippets: write directly as INI (no template needed)
        if config_name.startswith("cellframe-node.cfg.d/"):
            snippet_name = config_name.split("/", 1)[1]
            for node_id in node_ids:
                target = cache_dir / "configs" / f"node{node_id}" / "cellframe-node.cfg.d" / snippet_name
                target.parent.mkdir(parents=True, exist_ok=True)
                lines = []
                current_section = None
                for k, v in variables.items():
                    if '.' in k:
                        section, key = k.rsplit('.', 1)
                        if section != current_section:
                            lines.append(f"[{section}]")
                            current_section = section
                        lines.append(f"{key}={v}")
                    else:
                        lines.append(f"{k}={v}")
                target.write_text("\n".join(lines) + "\n")
                logger.info("config_snippet_written", node_id=node_id, file=snippet_name)
            return

        # Determine template path based on config_name
        is_chain = False
        is_network = False
        parts = []
        
        if '/' in config_name:
            parts = config_name.split('/')
            chain_file = parts[1]
            template_name = f"chains/{chain_file}.cfg.j2"
            is_chain = True
        elif config_name == network_name:
            template_name = "stagenet.cfg.j2"
            is_network = True
        else:
            template_name = f"base/{config_name}.cfg.j2"
            
        template_path = generator.templates_dir / template_name
        if not template_path.exists():
             template_path = generator.templates_dir / f"{config_name}.cfg.j2"
             if not template_path.exists():
                 raise RuntimeError(f"Template not found for {config_name}: tried {template_name} and {config_name}.cfg.j2")
        
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(generator.templates_dir)))
        template = env.get_template(str(template_path.relative_to(generator.templates_dir)))

        for node_id in node_ids:
            # 1. Determine target file path
            node_dir = cache_dir / "configs" / f"node{node_id}"
            if is_chain:
                # network/stagenet/chain.cfg
                target_file = node_dir / "network" / parts[0] / f"{parts[1]}.cfg"
            elif is_network:
                # network/stagenet.cfg
                target_file = node_dir / "network" / f"{config_name}.cfg"
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
        
        # Auto-convert all dash-keys to underscore-keys for Jinja2 compatibility
        # Config files use dashes (e.g. node-role), templates use underscores (node_role)
        for key in list(context.keys()):
            if '-' in key:
                underscore_key = key.replace('-', '_')
                if underscore_key not in context:
                    context[underscore_key] = context[key]
        
        # Special mappings for specific key renames
        special_mappings = {
            'ext_address': 'node_ip',  # ext_address in config -> node_ip in template
        }
        for config_key, template_key in special_mappings.items():
            if config_key in context and template_key not in context:
                context[template_key] = context[config_key]
        
        return context
