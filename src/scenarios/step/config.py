from typing import List, Dict, Any, Union
import re
import subprocess
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
        resolve_node_alias_callback=None,
        custom_templates_dirs=None,
    ):
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.base_path = container_manager.base_path
        self.custom_templates_dirs: List[Path] = [Path(d) for d in (custom_templates_dirs or [])]
        
    def _lookup_node_id_from_compose(self, service_name: str):
        """Resolve NODE_ID for a custom compose service (e.g. cdb-node-1 → 9)."""
        try:
            compose_file = self.base_path / "docker-compose.generated.yml"
            if not compose_file.exists():
                logger.debug(f"compose file not found at {compose_file}")
                return None
            import yaml
            with open(compose_file) as f:
                data = yaml.safe_load(f)
            svc = (data or {}).get("services", {}).get(service_name)
            if not svc:
                logger.debug(f"service '{service_name}' not in compose file")
                return None
            env = svc.get("environment", {})
            nid = env.get("NODE_ID")
            if nid is not None:
                logger.info(f"resolved_compose_node_id", service=service_name, node_id=int(nid))
                return int(nid)
        except Exception as e:
            logger.warning(f"compose_node_id_lookup_failed", service=service_name, error=str(e))
        return None

    def _resolve_container_for_node_id(self, node_id: int) -> str:
        """Map numeric node_id to the Docker container name via compose file."""
        try:
            import yaml
            compose_file = self.base_path / "docker-compose.generated.yml"
            if compose_file.exists():
                with open(compose_file) as f:
                    data = yaml.safe_load(f)
                for name, svc in (data or {}).get("services", {}).items():
                    env = svc.get("environment", {})
                    if isinstance(env, dict) and str(env.get("NODE_ID")) == str(node_id):
                        cname = svc.get("container_name", f"cellframe-stage-{name}")
                        logger.info("resolved_container_for_node", node_id=node_id, container=cname)
                        return cname
            else:
                logger.warning("compose_file_not_found_for_container_resolve", path=str(compose_file))
        except Exception as e:
            logger.warning("container_resolve_exception", node_id=node_id, error=str(e))
        logger.warning("container_resolve_fallback", node_id=node_id)
        return f"cellframe-stage-node-{node_id}"

    def _sync_config_to_container(self, node_id: int, config_rel_path: str, host_file: Path):
        """Push a rendered config file into the running container via docker cp.

        Only needed for paths that are NOT bind-mounted (e.g. lib/plugins/).
        Paths under ``configs/`` or mounted ``data/`` subdirs are already
        visible inside the container.
        """
        container_dest = f"/opt/cellframe-node/var/{config_rel_path}"
        svc_name = self._resolve_container_for_node_id(node_id)

        try:
            result = subprocess.run(
                ["docker", "cp", str(host_file), f"{svc_name}:{container_dest}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("config_synced_to_container",
                            node_id=node_id, container=svc_name, path=container_dest)
            else:
                logger.warning("config_sync_docker_cp_failed",
                               node_id=node_id, container=svc_name, stderr=result.stderr.strip())
        except Exception as e:
            logger.warning("config_sync_exception", node_id=node_id, error=str(e))

    def _expand_nodes_list(self, nodes, ctx) -> list:
        """Expand nodes that can be a template string or list."""
        if isinstance(nodes, str):
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
    
    def _resolve_template_path(self, template_str: str) -> Path:
        """
        Resolve template path by searching custom_templates_dirs, then base_path.
        Bare names (no directory separators) are looked up in custom dirs first.
        """
        tpl_path = Path(template_str)
        if tpl_path.is_absolute() and tpl_path.exists():
            return tpl_path

        if '/' not in template_str and '\\' not in template_str:
            for d in self.custom_templates_dirs:
                candidate = d / template_str
                if candidate.exists():
                    return candidate.resolve()

        resolved = (self.base_path / tpl_path).resolve()
        if resolved.exists():
            return resolved

        raise ScenarioExecutionError(
            f"Template not found: {template_str} "
            f"(searched: {[str(d) for d in self.custom_templates_dirs]} + {self.base_path})"
        )

    async def execute(self, step: ConfigStep, ctx: RuntimeContext) -> None:
        """Execute config regeneration step."""
        if isinstance(step.set, dict):
            variables = {k: ctx.substitute(str(v)) for k, v in step.set.items()}
        else:
            variables = self._parse_set_string(ctx.substitute(step.set))

        config_path = ctx.substitute(step.config)
        template_path = ctx.substitute(step.template) if step.template else None
        deploy_mode = ctx.substitute(step.deploy) if step.deploy else None

        if deploy_mode == "container":
            await self._deploy_to_containers(step, ctx, config_path, template_path, variables)
            return

        nodes_list = self._expand_nodes_list(step.nodes, ctx)
        svc_map = ctx.variables.get('_service_node_ids', {})
        node_ids = []
        for node_alias in nodes_list:
            resolved = ctx.substitute(node_alias)
            if self.resolve_node_alias_callback:
                resolved = self.resolve_node_alias_callback(resolved)
            # Match base-topology names: node1, node-1, root-2, master-3, full-1
            match = re.match(r'^(?:node|root|master|full)-?(\d+)$', resolved)
            if match:
                node_ids.append(int(match.group(1)))
            elif resolved in svc_map:
                node_ids.append(int(svc_map[resolved]))
            else:
                # Custom compose service (cdb-node-1, kelvpn-client-3, etc.)
                nid = self._lookup_node_id_from_compose(resolved)
                if nid is not None:
                    node_ids.append(nid)
                else:
                    logger.warning(f"Could not parse node ID from {resolved}")

        if not node_ids:
            raise ScenarioExecutionError(f"No valid nodes resolved from {step.nodes}", step=step)

        logger.info(f"Config: regenerating '{config_path}' for nodes {node_ids} with vars {list(variables.keys())}")
        
        network_name = ctx.variables.get('network_name', 'stagenet')
        
        await self._regenerate_config(node_ids, config_path, variables, network_name, template_path)
        
        ctx.add_result("config", True, {"name": step.config, "nodes": node_ids})

    async def _deploy_to_containers(
        self, step: ConfigStep, ctx: RuntimeContext,
        config_path: str, template_path: str, variables: Dict[str, Any],
    ) -> None:
        """Render a J2 template and deploy the result into running containers via docker exec."""
        import jinja2

        if not template_path:
            raise ScenarioExecutionError("deploy: container requires a 'template' field", step=step)

        tpl_path = self._resolve_template_path(template_path)
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(tpl_path.parent)))
        template = env.get_template(tpl_path.name)

        nodes_list = self._expand_nodes_list(step.nodes, ctx)
        deployed = []
        for node_alias in nodes_list:
            node = ctx.substitute(node_alias)
            full_context = {**variables, "node": node}
            rendered = template.render(full_context)
            escaped = rendered.replace("'", "'\\''")

            target = config_path.replace("{{node}}", node)
            result = await self.container_manager.exec_bash_command(
                f"mkdir -p $(dirname '{target}') && printf '%s' '{escaped}' > '{target}'",
                node=node,
                timeout=30,
            )
            if result["returncode"] != 0:
                raise ScenarioExecutionError(
                    f"Failed to deploy config to {node}:{target}: {result['stderr'] or result['stdout']}",
                    step=step,
                )
            deployed.append(node)
            logger.info("config_deployed_to_container", node=node, target=target, template=str(tpl_path))

        ctx.add_result("config", True, {"name": config_path, "deploy": "container", "nodes": deployed})

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

    async def _regenerate_config(
        self,
        node_ids: List[int],
        config_name: str,
        variables: Dict[str, Any],
        network_name: str = "stagenet",
        template_override: str = None,
    ):
        """
        Regenerate config file from template, merging existing values with new variables.
        
        Routing:
            1. Absolute/relative path + template → render J2 into that path per node
            2. "cellframe-node.cfg.d/<snippet>" → direct INI write
            3. Standard names ("cellframe-node", "stagenet/main") → built-in J2 templates
        """
        from src.config.manager import get_config_loader
        from src.config.generator import ConfigGenerator
        
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', '../../cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        generator = ConfigGenerator(self.base_path, config_loader.config_path)

        # Route 1: explicit template — render into target path per node
        if template_override:
            await self._render_with_template(
                node_ids, config_name, variables, cache_dir, template_override
            )
            return
        
        # Route 2: cfg.d snippets — direct INI write (any path containing .cfg.d/)
        if '.cfg.d/' in config_name:
            self._write_ini_snippet(node_ids, config_name, variables, cache_dir)
            return

        # Route 3: standard configs via built-in J2 templates
        await self._regenerate_standard_config(
            node_ids, config_name, variables, network_name, cache_dir, generator
        )

    def _write_ini_snippet(
        self,
        node_ids: List[int],
        config_name: str,
        variables: Dict[str, Any],
        cache_dir: Path,
    ):
        """Write cfg.d INI snippet directly (no template).
        
        Supports any path containing .cfg.d/, e.g.:
          - cellframe-node.cfg.d/overrides.cfg
          - network/vpntest.cfg.d/role.cfg
        """
        for node_id in node_ids:
            target = cache_dir / "configs" / f"node{node_id}" / config_name
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
            logger.info("config_snippet_written", node_id=node_id, file=config_name)

    async def _render_with_template(
        self,
        node_ids: List[int],
        config_name: str,
        variables: Dict[str, Any],
        cache_dir: Path,
        template_path_str: str,
    ):
        """
        Render an external J2 template into per-node target paths.
        
        config_name may contain {{node_id}} for per-node expansion,
        or be an absolute path under cache/data/node{N}/...
        """
        import jinja2

        tpl_path = self._resolve_template_path(template_path_str)

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tpl_path.parent))
        )
        template = env.get_template(tpl_path.name)

        for node_id in node_ids:
            expanded = config_name.replace("{{node_id}}", str(node_id))

            if expanded.startswith("/"):
                target = cache_dir / "data" / f"node{node_id}" / expanded.lstrip("/")
            else:
                target = cache_dir / "data" / f"node{node_id}" / expanded

            target.parent.mkdir(parents=True, exist_ok=True)

            existing_context = {}
            if target.exists():
                try:
                    existing_context = self._extract_context_from_ini(target.read_text())
                except PermissionError:
                    existing_context = self._read_root_owned_file(target)

            full_context = {**existing_context, **variables, "node_id": node_id}

            rendered = template.render(full_context)
            try:
                target.write_text(rendered)
            except PermissionError:
                self._write_root_owned_file(target, rendered)
            logger.info("config_rendered", node_id=node_id, target=str(target), template=str(tpl_path))

            # Paths under cache/data/ (e.g. lib/plugins/) are NOT bind-mounted
            # by default — push the rendered file into the running container.
            # Paths under cache/configs/ (cellframe-node.cfg, cfg.d/, network/)
            # ARE bind-mounted and don't need docker cp.
            if "/data/" in str(target):
                self._sync_config_to_container(node_id, expanded, target)

    async def _regenerate_standard_config(
        self,
        node_ids: List[int],
        config_name: str,
        variables: Dict[str, Any],
        network_name: str,
        cache_dir: Path,
        generator,
    ):
        """Regenerate standard cellframe-node configs via built-in J2 templates."""
        import jinja2

        is_chain = False
        is_network = False
        parts = []
        
        if '/' in config_name:
            parts = config_name.split('/')
            chain_file = parts[1]
            template_name = f"chains/{chain_file}.cfg.j2"
            is_chain = True
        elif config_name == network_name:
            template_name = "network.cfg.j2"
            is_network = True
        else:
            template_name = f"{config_name}.cfg.j2"

        template_path = generator._resolve_template(template_name)
        if template_path is None:
            raise RuntimeError(
                f"Template not found for {config_name}: tried {template_name} "
                f"in {generator.versioned_templates_dir} and {generator.templates_dir}"
            )
        
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(generator.templates_dir)))
        template = env.get_template(str(template_path.relative_to(generator.templates_dir)))

        for node_id in node_ids:
            node_dir = cache_dir / "configs" / f"node{node_id}"
            if is_chain:
                target_file = node_dir / "network" / parts[0] / f"{parts[1]}.cfg"
            elif is_network:
                target_file = node_dir / "network" / f"{config_name}.cfg"
            else:
                target_file = node_dir / f"{config_name}.cfg"
                
            if not target_file.exists():
                logger.warning(f"Target config file {target_file} does not exist, skipping regeneration for node {node_id}")
                continue

            existing_content = target_file.read_text()
            current_context = self._extract_context_from_ini(existing_content)
            full_context = {**current_context, **variables}
            full_context['network_name'] = network_name
            if is_network and 'id' in full_context and 'network_id' not in full_context:
                full_context['network_id'] = full_context['id']
            
            try:
                rendered = template.render(full_context)
                target_file.write_text(rendered)
                logger.info(f"Regenerated {target_file.name} for node {node_id}")
            except Exception as e:
                logger.error(f"Failed to render template for node {node_id}: {e}")
                raise

    def _write_root_owned_file(self, target: Path, content: str) -> None:
        """Write to a root-owned file via Docker (containers create files as root)."""
        logger.info("config_write_via_docker", target=str(target))
        subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{target.parent}:/target",
             "alpine", "sh", "-c",
             f"chmod 666 /target/{target.name} 2>/dev/null; true"],
            capture_output=True
        )
        target.write_text(content)

    def _read_root_owned_file(self, target: Path) -> Dict[str, Any]:
        """Read a root-owned config file via Docker and parse INI context."""
        logger.info("config_read_via_docker", target=str(target))
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{target.parent}:/target:ro",
             "alpine", "cat", f"/target/{target.name}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return self._extract_context_from_ini(result.stdout)
        return {}

    def _extract_context_from_ini(self, content: str) -> Dict[str, Any]:
        """Extract key=value pairs from INI-like content to recreate a context."""
        context = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('['):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                if v.lower() == 'true':
                    v = True
                elif v.lower() == 'false':
                    v = False
                elif v.isdigit():
                    v = int(v)
                context[k] = v
        
        for key in list(context.keys()):
            if '-' in key:
                underscore_key = key.replace('-', '_')
                if underscore_key not in context:
                    context[underscore_key] = context[key]
        
        special_mappings = {
            'ext_address': 'node_ip',
        }
        for config_key, template_key in special_mappings.items():
            if config_key in context and template_key not in context:
                context[template_key] = context[config_key]
        
        return context
