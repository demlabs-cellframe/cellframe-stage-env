"""
Docker Compose management using Docker SDK.

Modern replacement for deprecated docker-compose library.
Uses docker SDK 7.0+ with native compose v2 support.
"""

import os
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

from src.utils.logger import get_logger
from ..network.models import NodeConfig

logger = get_logger(__name__)

# Docker cleanup constants
CLEANUP_IMAGE = "alpine:latest"
CLEANUP_MOUNT_PATH = "/cleanup"

# Robust cleanup command that handles:
# - Unix sockets (main culprit for "Directory not empty" on macOS/Linux)
# - Regular files and named pipes
# - Empty directories (bottom-up removal)
# Errors suppressed to ensure cleanup completes even with permission issues
CLEANUP_CMD_TEMPLATE = (
    "find {target} -type s -exec rm -f {{}} + 2>/dev/null || true; "
    "find {target} -type f -exec rm -f {{}} + 2>/dev/null || true; "
    "find {target} -type p -exec rm -f {{}} + 2>/dev/null || true; "
    "find {target} -depth -type d -exec rmdir {{}} + 2>/dev/null || true; "
    "rm -rf {target} 2>/dev/null || true; "
    "echo 'Cleanup complete'"
)


class DockerComposeManager:
    """Manage Docker Compose services using Docker SDK."""
    
    def __init__(self, project_dir: Path, project_name: str = "cellframe", network_name: str = "stagenet"):
        """
        Initialize Docker Compose manager.
        
        Args:
            project_dir: Project directory containing docker-compose.yml
            project_name: Docker Compose project name
            network_name: Cellframe network name (e.g., stagenet, mainnet)
        """
        self.project_dir = project_dir
        self.project_name = project_name
        self.network_name = network_name
        self.compose_file = project_dir / "docker-compose.yml"
        
        try:
            self.client = docker.from_env()
            logger.info("docker_connected", version=self.client.version()["Version"])
        except DockerException as e:
            logger.error("docker_connection_failed", error=str(e))
            raise
    
    def build(
        self,
        services: Optional[List[str]] = None,
        no_cache: bool = False,
        test_mirrors: bool = True,
    ) -> None:
        """
        Build Docker images.
        
        Args:
            services: List of service names to build (None = all)
            no_cache: Don't use cache
            test_mirrors: Test mirror speeds before building
        """
        logger.info("building_images", 
                   services=services or "all",
                   no_cache=no_cache,
                   test_mirrors=test_mirrors)
        
        # Test mirrors and select fastest before building
        debian_mirror = None
        if test_mirrors:
            try:
                from src.utils.mirror_tester import select_fastest_mirrors
                from ..cli.common import print_info, print_success, print_warning
                from src.utils.i18n import _
                
                print_info(_("Testing mirror speeds..."))
                mirror_results = select_fastest_mirrors(timeout=5)
                debian_mirror = mirror_results['debian_mirror']
                debian_time = mirror_results['debian_time']
                
                print_success(_("Fastest Debian mirror: {} ({}s)").format(debian_mirror, f"{debian_time:.2f}"))
                logger.info("fastest_mirror_selected", 
                           debian_mirror=debian_mirror,
                           debian_time=debian_time)
            except Exception as e:
                logger.warning("mirror_test_failed", error=str(e))
                print_warning(_("Mirror testing failed: {}, using default mirrors").format(e))
        
        # Use docker compose CLI via subprocess for build
        # (docker SDK doesn't have direct compose build API yet)
        from src.utils.cli import run_command
        import os
        
        # Set environment variable for mirror (docker-compose reads from env)
        env = os.environ.copy()
        if debian_mirror:
            env["DEBIAN_MIRROR"] = debian_mirror
            logger.info("setting_debian_mirror_env", mirror=debian_mirror)
        
        # Build only the first node service to create shared image
        # (all nodes use the same image: cf-node:debug-latest)
        # This avoids "image already exists" conflicts when building in parallel
        first_node_service = services[0] if services else "node-1"
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "build", first_node_service]
        
        if no_cache:
            cmd.append("--no-cache")
        
        # Print informative messages before starting Docker build
        from ..cli.common import print_info, print_success
        from src.utils.i18n import _
        print_info(_("Starting Docker build..."))
        print_info(_("Docker Compose file: {}").format(self.compose_file.name))
        print_info(_("Project name: {}").format(self.project_name))
        if debian_mirror:
            print_info(_("Using Debian mirror: {}").format(debian_mirror))
        if no_cache:
            print_info(_("Build mode: --no-cache (clean build)"))
        print_info(_("Docker Compose is building images (this may take a while)..."))
        
        logger.info("starting_docker_build", 
                   compose_file=str(self.compose_file),
                   project=self.project_name,
                   no_cache=no_cache,
                   services=services or "all")
        
        try:
            # Run command with real-time output (not captured)
            run_command(cmd, cwd=self.project_dir, env=env, capture_output=False)
            
            print_success(_("Docker build completed successfully"))
            logger.info("build_completed")
        except KeyboardInterrupt:
            from ..cli.common import print_warning
            print_warning(_("\nDocker build interrupted by user (Ctrl+C)"))
            logger.warning("docker_build_interrupted")
            raise
    
    def cleanup_stale_resources(self) -> None:
        """
        Clean up stale containers and networks from previous runs.
        
        This prevents "network overlap" and "container name conflict" errors.
        """
        logger.info("cleanup_stale_resources", project=self.project_name)
        
        # Find and remove stale containers with this project name
        stale_containers = []
        
        # First, try to find by label
        try:
            stale_containers = self.client.containers.list(
                all=True,
                filters={"label": f"com.docker.compose.project={self.project_name}"}
            )
        except Exception as e:
            logger.warning("failed_to_list_containers_by_label", error=str(e))
        
        # Also check by name prefix (more reliable for containers in "Created" state)
        try:
            all_containers = self.client.containers.list(all=True)
            for container in all_containers:
                if container.name.startswith(f"{self.project_name}-"):
                    # Avoid duplicates
                    if container not in stale_containers:
                        stale_containers.append(container)
                        logger.debug("found_stale_container_by_name", name=container.name, status=container.status)
        except Exception as e:
            logger.warning("failed_to_list_all_containers", error=str(e))
        
        if stale_containers:
            logger.info("removing_stale_containers", count=len(stale_containers))
            for container in stale_containers:
                try:
                    logger.debug("removing_container", 
                               name=container.name,
                               id=container.short_id,
                               status=container.status)
                    container.remove(force=True)
                except Exception as e:
                    logger.warning("failed_to_remove_container",
                                 name=container.name,
                                 error=str(e))
        else:
            logger.debug("no_stale_containers")
        
        # Find and remove stale networks with this project name
        try:
            all_networks = self.client.networks.list()
            stale_networks = [
                net for net in all_networks
                if self.project_name in net.name
            ]
            
            if stale_networks:
                logger.info("removing_stale_networks", count=len(stale_networks))
                for network in stale_networks:
                    try:
                        logger.debug("removing_network",
                                   name=network.name,
                                   id=network.short_id)
                        network.remove()
                    except Exception as e:
                        logger.warning("failed_to_remove_network",
                                     name=network.name,
                                     error=str(e))
            else:
                logger.debug("no_stale_networks")
        except Exception as e:
            logger.warning("failed_to_list_networks", error=str(e))
        
        logger.info("cleanup_completed")
    
    def generate_compose_for_nodes(
        self,
        nodes: List[NodeConfig],
        build_type: str = "debug",
        cellframe_version: str = "latest",
        cache_dir_relative: str = "cache",
        node_source_config: Optional[Dict[str, Any]] = None,
        network_settings: Optional[Dict[str, str]] = None,
        extra_services: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Generate docker-compose.yml dynamically for given nodes.
        
        Args:
            nodes: List of node configurations
            build_type: Build type (debug/release)
            cellframe_version: Cellframe version tag
            cache_dir_relative: Relative path to cache directory
            node_source_config: Node source configuration (type, url, local_path, etc.)
            network_settings: Dict with 'subnet' and 'base_ip' from config
            extra_services: Additional docker-compose services to merge (from suite descriptor)
        """
        if os.path.isabs(cache_dir_relative):
            cache_dir_relative = os.path.relpath(cache_dir_relative, str(self.project_dir))

        logger.info("generating_compose_file",
                   node_count=len(nodes),
                   build_type=build_type,
                   cache_dir=cache_dir_relative,
                   node_source_type=node_source_config.get('type', 'url') if node_source_config else 'url')
        
        # Read base template
        template_file = self.project_dir / "docker-compose.yml"
        
        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_file}")
        
        # Load base compose configuration
        with open(template_file, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        # Extract template from x-cf-node-template
        node_template = compose_data.get('x-cf-node-template')
        if not node_template:
            raise ValueError("No x-cf-node-template found in docker-compose.yml")
        
        # Override network config from stage-env.cfg (template has defaults)
        if network_settings:
            subnet = network_settings.get('subnet')
            if subnet:
                import ipaddress
                net = ipaddress.ip_network(subnet, strict=False)
                gateway = str(net.network_address + 1)
                network_settings['gateway'] = gateway
                compose_data.setdefault('networks', {}) \
                    .setdefault(self.network_name, {}) \
                    .setdefault('ipam', {})['config'] = [
                        {'subnet': subnet, 'gateway': gateway}
                    ]
                logger.info("network_config_injected",
                           subnet=subnet, gateway=gateway)
        
        # Clear existing node services (keep monitoring/test services)
        services_to_keep = {}
        for svc_name, svc_config in compose_data.get('services', {}).items():
            if svc_name not in ['cf-node']:
                services_to_keep[svc_name] = svc_config
        
        compose_data['services'] = services_to_keep
        
        # Ensure packages/ directory exists in build context (required for COPY in Dockerfile)
        # This directory will be empty for url/repository sources, but must exist
        build_context_packages_dir = self.project_dir / "packages"
        build_context_packages_dir.mkdir(exist_ok=True)
        
        # Determine node source configuration
        node_source_type = node_source_config.get('type', 'url') if node_source_config else 'url'
        
        # Clear stale .deb files from packages/ build context
        for item in build_context_packages_dir.iterdir():
            if item.is_file() and item.suffix == '.deb':
                logger.debug("removing_stale_package", path=str(item))
                item.unlink()
        (build_context_packages_dir / ".gitkeep").touch(exist_ok=True)
        
        # Copy extra packages into build context (installed after cellframe-node)
        from src.config.manager import get_config_loader
        try:
            extra_packages = get_config_loader().get_extra_packages()
        except Exception:
            extra_packages = []
        
        if extra_packages:
            import shutil as _shutil, tempfile as _tmpf
            for pkg_info in extra_packages:
                if pkg_info['type'] == 'local':
                    src = Path(pkg_info['path'])
                    dst = build_context_packages_dir / src.name
                    try:
                        if dst.exists() and dst.stat().st_size == src.stat().st_size:
                            continue
                    except OSError:
                        pass
                    try:
                        fd, tmp = _tmpf.mkstemp(dir=dst.parent, suffix='.tmp')
                        os.close(fd)
                        _shutil.copy2(src, tmp)
                        os.replace(tmp, dst)
                    except Exception:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        if not dst.exists():
                            raise
                    logger.info("extra_package_copied", name=src.name,
                               size_mb=round(src.stat().st_size / (1024 * 1024), 2))
                elif pkg_info['type'] == 'url':
                    import urllib.request
                    url = pkg_info['url']
                    fname = url.rsplit('/', 1)[-1]
                    dst = build_context_packages_dir / fname
                    logger.info("extra_package_downloading", url=url)
                    urllib.request.urlretrieve(url, str(dst))
                    logger.info("extra_package_downloaded", name=fname)
        
        local_package_path = None
        
        if node_source_type == 'local' and node_source_config:
            local_path = node_source_config.get('local_path')
            if local_path:
                import glob as _glob
                raw = Path(local_path)
                if not raw.is_absolute():
                    raw = self.project_dir / local_path
                matched = sorted(_glob.glob(str(raw)))
                if matched:
                    local_package_path = Path(matched[-1]).resolve()
                else:
                    resolved = raw.resolve()
                    if resolved.exists():
                        local_package_path = resolved
                    else:
                        logger.error("local_package_not_found", path=str(resolved), pattern=local_path)
                        raise FileNotFoundError(f"Local package not found: {resolved} (pattern: {local_path})")
                
                logger.info("using_local_package", path=str(local_package_path))
        
        # Resolve paths config (once, before node loop)
        from src.config.manager import get_config_loader
        paths_config = get_config_loader().get_paths_config()
        tools_base_url = paths_config.get('tools_base_url', 'https://pub.cellframe.net')
        node_var_subdirs = [
            s.strip() for s in paths_config.get(
                'node_var_subdirs',
                'log, lib/ca, lib/global_db, lib/wallet, lib/network'
            ).split(',')
        ]
        
        # Load [role_docker_*] / [node_docker_*] customizations from stage-env.cfg
        docker_customizations = get_config_loader().get_docker_customizations()

        # Generate service for each node
        for node in nodes:
            service_name = f"node-{node.node_id}"
            
            # Deep copy template
            node_service = yaml.safe_load(yaml.dump(node_template))
            
            # Update service configuration
            node_service['container_name'] = f"{self.project_name}-node-{node.node_id}"
            node_service['hostname'] = f"{self.project_name}-node-{node.node_id}"
            node_service['init'] = True
            
            # Set network IP
            node_service['networks'] = {
                self.network_name: {
                    'ipv4_address': node.ip_address
                }
            }
            
            # Set ports - Cellframe uses 8079 for HTTP/JSON-RPC/P2P
            node_service['ports'] = [
                f"{node.http_port}:8079",  # Cellframe HTTP/JSON-RPC/P2P
            ]
            
            data_prefix = f"./{cache_dir_relative}/data/node{node.node_id}"
            node_service['volumes'] = [
                f"./{cache_dir_relative}/configs/node{node.node_id}/cellframe-node.cfg:/opt/cellframe-node/etc/cellframe-node.cfg",
                f"./{cache_dir_relative}/configs/node{node.node_id}/cellframe-node.cfg.d:/opt/cellframe-node/etc/cellframe-node.cfg.d",
                f"./{cache_dir_relative}/configs/node{node.node_id}/network:/opt/cellframe-node/etc/network",
            ] + [
                f"{data_prefix}/{subdir}:/opt/cellframe-node/var/{subdir}"
                for subdir in node_var_subdirs
            ] + [
                f"./{cache_dir_relative}/configs/shared/ca:/opt/cellframe-node/share/ca:ro",
                f"./{cache_dir_relative}/crash-artifacts/node{node.node_id}:/crash-artifacts/node-{node.node_id}",
                f"./{cache_dir_relative}/cellframe-packages:/var/cache/cellframe-packages",
                f"./scripts/docker-entrypoint.sh:/usr/local/bin/docker-entrypoint.sh:ro",
            ]
            
            # Add local package volume mount if using local source
            if node_source_type == 'local' and local_package_path:
                # Mount local package directory to container
                package_dir = local_package_path.parent
                node_service['volumes'].append(
                    f"{package_dir}:/packages:ro"
                )
                logger.debug("added_local_package_volume",
                           node_id=node.node_id,
                           package_dir=str(package_dir))
            
            # Update build args based on node_source configuration
            if 'build' not in node_service:
                node_service['build'] = {}
            if 'args' not in node_service['build']:
                node_service['build']['args'] = {}
            
            # Set TOOLS_BASE_URL from paths config
            node_service['build']['args']['TOOLS_BASE_URL'] = tools_base_url
            node_service['build']['args']['BUILD_TYPE'] = build_type
            
            node_service['image'] = f"cf-node:{build_type}-{cellframe_version}"
            
            # Set build args for node source
            node_service['build']['args']['NODE_SOURCE_TYPE'] = node_source_type
            if node_source_type == 'local' and local_package_path:
                # For local packages, we need to:
                # 1. Set build context to include package directory
                # 2. Copy package to build context before build
                package_dir = local_package_path.parent
                package_name = local_package_path.name
                
                # Copy package to build context (packages/ directory)
                # Directory already created above
                # IMPORTANT: Use copy instead of symlink because Docker COPY doesn't follow
                # symlinks that point outside build context
                package_dest = self.project_dir / "packages" / package_name

                import shutil, tempfile
                needs_copy = True
                try:
                    if package_dest.exists() and package_dest.stat().st_size == local_package_path.stat().st_size:
                        needs_copy = False
                except OSError:
                    pass

                if needs_copy:
                    try:
                        fd, tmp = tempfile.mkstemp(
                            dir=package_dest.parent, suffix='.tmp',
                        )
                        os.close(fd)
                        shutil.copy2(local_package_path, tmp)
                        os.replace(tmp, package_dest)
                        logger.debug("copied_package_to_build_context",
                                   node_id=node.node_id,
                                   source=str(local_package_path),
                                   dest=str(package_dest),
                                   size_mb=round(local_package_path.stat().st_size / (1024*1024), 2))
                    except Exception as e:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        if package_dest.exists():
                            pass
                        else:
                            logger.error("failed_to_copy_package_to_build_context",
                                       node_id=node.node_id,
                                       source=str(local_package_path),
                                       dest=str(package_dest),
                                       error=str(e))
                            raise RuntimeError(f"Failed to copy package to build context: {e}")
                
                node_service['build']['args']['LOCAL_PACKAGE_NAME'] = package_name
                logger.debug("set_local_package_build_arg",
                           node_id=node.node_id,
                           package_name=package_name)
            elif node_source_type == 'url' and node_source_config:
                url = node_source_config.get('url')
                if url:
                    node_service['build']['args']['PACKAGE_URL'] = url
            elif node_source_type == 'repository' and node_source_config:
                repo_url = node_source_config.get('repository_url')
                branch = node_source_config.get('repository_branch', 'master')
                if repo_url:
                    node_service['build']['args']['REPOSITORY_URL'] = repo_url
                    node_service['build']['args']['REPOSITORY_BRANCH'] = branch
            
            # Add custom volumes if specified
            if hasattr(node, 'docker_volumes') and node.docker_volumes:
                node_service['volumes'].extend(node.docker_volumes)
                logger.debug("added_custom_volumes",
                           node_id=node.node_id,
                           volumes=node.docker_volumes)
            
            # Set environment variables
            env = {
                'NODE_ID': str(node.node_id),
                'NODE_ROLE': node.role,
                'NODE_TYPE': node.node_type,
                'NODE_IP': node.ip_address,
                'NETWORK_NAME': self.network_name,
                'DAP_DEBUG': '1',
                'CELLFRAME_DEBUG': '1',
            }
            if network_settings:
                env['DOCKER_SUBNET'] = network_settings.get('subnet', '172.20.0.0/16')
                env['DOCKER_GATEWAY'] = network_settings.get('gateway', '172.20.0.1')

            # Apply [role_docker_<role>] and [node_docker_<id>] from stage-env.cfg
            role_section = docker_customizations.get(f'role_docker_{node.role}', {})
            node_section = docker_customizations.get(f'node_docker_{node.node_id}', {})
            for section in (role_section, node_section):
                section_env = section.get('environment')
                if section_env:
                    env.update(section_env)
                section_caps = section.get('capabilities')
                if section_caps:
                    if 'cap_add' not in node_service:
                        node_service['cap_add'] = []
                    node_service['cap_add'].extend(section_caps)
                section_devices = section.get('devices')
                if section_devices:
                    existing_devices = node_service.get('devices', [])
                    node_service['devices'] = list(dict.fromkeys(existing_devices + section_devices))
                section_extra = section.get('extra_config')
                if section_extra:
                    for key, value in section_extra.items():
                        if isinstance(value, dict) and key in node_service and isinstance(node_service[key], dict):
                            node_service[key].update(value)
                        elif isinstance(value, list) and key in node_service and isinstance(node_service[key], list):
                            node_service[key].extend(value)
                        else:
                            node_service[key] = value

            node_service['environment'] = env

            # Add custom environment variables if specified (from NodeConfig)
            if hasattr(node, 'custom_env_vars') and node.custom_env_vars:
                node_service['environment'].update(node.custom_env_vars)
                logger.debug("added_custom_env_vars",
                           node_id=node.node_id,
                           vars=list(node.custom_env_vars.keys()))
            
            # Add custom capabilities if specified (from NodeConfig)
            if hasattr(node, 'docker_capabilities') and node.docker_capabilities:
                if 'cap_add' not in node_service:
                    node_service['cap_add'] = []
                node_service['cap_add'].extend(node.docker_capabilities)
                logger.debug("added_custom_capabilities",
                           node_id=node.node_id,
                           caps=node.docker_capabilities)
            
            # Add custom devices if specified (from NodeConfig)
            if hasattr(node, 'docker_devices') and node.docker_devices:
                node_service['devices'] = node.docker_devices
                logger.debug("added_custom_devices",
                           node_id=node.node_id,
                           devices=node.docker_devices)
            
            # Merge custom docker config if specified (from NodeConfig)
            if hasattr(node, 'docker_extra_config') and node.docker_extra_config:
                for key, value in node.docker_extra_config.items():
                    if isinstance(value, dict) and key in node_service and isinstance(node_service[key], dict):
                        node_service[key].update(value)
                    elif isinstance(value, list) and key in node_service and isinstance(node_service[key], list):
                        node_service[key].extend(value)
                    else:
                        node_service[key] = value
                logger.debug("merged_custom_docker_config",
                           node_id=node.node_id,
                           keys=list(node.docker_extra_config.keys()))
            
            # CRITICAL: Set pull_policy to never to use locally built image
            # This prevents Docker from trying to pull cf-node from Docker Hub
            node_service['pull_policy'] = 'never'
            
            # Add to services
            compose_data['services'][service_name] = node_service
        
        # Merge extra services from suite descriptor.
        # Auto-connect to the project network so they can reach cellframe nodes.
        if extra_services:
            for svc_name, svc_config in extra_services.items():
                if isinstance(svc_config, dict) and 'networks' not in svc_config:
                    svc_config['networks'] = [self.network_name]
                compose_data['services'][svc_name] = svc_config
                logger.info("extra_service_added", name=svc_name)
        
        # Write generated compose file (respect pre-set compose_file for shards)
        if self.compose_file.name.startswith("docker-compose.shard-"):
            generated_file = self.compose_file
        else:
            generated_file = self.project_dir / "docker-compose.generated.yml"
            self.compose_file = generated_file

        with open(generated_file, 'w') as f:
            yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)

        logger.info("compose_file_generated",
                   path=str(generated_file),
                   services=len(compose_data.get('services', {})))
    
    def add_extra_node_services(
        self,
        extra_nodes: List[Dict[str, Any]],
        network_settings: Optional[Dict[str, str]] = None,
        cache_dir_relative: str = "cache",
        suite_env: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Add extra cellframe node services to the generated compose file.

        Each entry reuses the x-cf-node-template from the base compose and
        follows the same volume/network conventions as base topology nodes.

        Args:
            extra_nodes: List of dicts with keys: id, role, ip_address, http_port,
                         and optional: cap_add, docker_devices, environment
            network_settings: subnet/gateway overrides
            cache_dir_relative: relative cache directory
            suite_env: suite-level env vars (from env_file) applied to all nodes
        """
        if os.path.isabs(cache_dir_relative):
            cache_dir_relative = os.path.relpath(cache_dir_relative, str(self.project_dir))

        if not self.compose_file.exists():
            raise FileNotFoundError(f"Generated compose file not found: {self.compose_file}")

        with open(self.compose_file, 'r') as f:
            compose_data = yaml.safe_load(f)

        node_template = compose_data.get('x-cf-node-template')
        if not node_template:
            existing_svc = next(
                (v for k, v in compose_data.get('services', {}).items() if k.startswith('node-')),
                None,
            )
            if not existing_svc:
                raise ValueError("Cannot determine node template from compose file")
            node_template = existing_svc

        from src.config.manager import get_config_loader
        paths_config = get_config_loader().get_paths_config()
        node_var_subdirs = [
            s.strip() for s in paths_config.get(
                'node_var_subdirs',
                'log, lib/ca, lib/global_db, lib/wallet, lib/network'
            ).split(',')
        ]

        for node_spec in extra_nodes:
            node_id = node_spec['id']
            service_name = node_spec.get('service_name', f"node-{node_id}")

            if service_name in compose_data.get('services', {}):
                existing_svc = compose_data['services'][service_name]
                existing_nets = existing_svc.get('networks')
                desired_ip = node_spec['ip_address']
                has_static = (
                    isinstance(existing_nets, dict)
                    and isinstance(existing_nets.get(self.network_name), dict)
                    and existing_nets[self.network_name].get('ipv4_address') == desired_ip
                )
                if has_static:
                    logger.info("extra_node_already_exists", service=service_name)
                    continue
                existing_svc['networks'] = {
                    self.network_name: {'ipv4_address': desired_ip}
                }
                logger.info("extra_node_ip_updated",
                           service=service_name, ip=desired_ip)
                continue

            svc = yaml.safe_load(yaml.dump(node_template))
            svc['container_name'] = f"{self.project_name}-{service_name}"
            svc['hostname'] = f"{self.project_name}-{service_name}"
            svc['init'] = True

            svc['networks'] = {
                self.network_name: {'ipv4_address': node_spec['ip_address']}
            }
            svc['ports'] = [f"{node_spec['http_port']}:8079"]

            data_prefix = f"./{cache_dir_relative}/data/node{node_id}"
            svc['volumes'] = [
                f"./{cache_dir_relative}/configs/node{node_id}/cellframe-node.cfg:/opt/cellframe-node/etc/cellframe-node.cfg",
                f"./{cache_dir_relative}/configs/node{node_id}/cellframe-node.cfg.d:/opt/cellframe-node/etc/cellframe-node.cfg.d",
                f"./{cache_dir_relative}/configs/node{node_id}/network:/opt/cellframe-node/etc/network",
            ] + [
                f"{data_prefix}/{subdir}:/opt/cellframe-node/var/{subdir}"
                for subdir in node_var_subdirs
            ] + [
                f"./{cache_dir_relative}/configs/shared/ca:/opt/cellframe-node/share/ca:ro",
                f"./{cache_dir_relative}/crash-artifacts/node{node_id}:/crash-artifacts/node-{node_id}",
                f"./{cache_dir_relative}/cellframe-packages:/var/cache/cellframe-packages",
                f"./scripts/docker-entrypoint.sh:/usr/local/bin/docker-entrypoint.sh:ro",
            ]

            env = {
                'NODE_ID': str(node_id),
                'NODE_ROLE': node_spec.get('role', 'full'),
                'NODE_TYPE': 'node',
                'NODE_IP': node_spec['ip_address'],
                'NETWORK_NAME': self.network_name,
                'DAP_DEBUG': '1',
                'CELLFRAME_DEBUG': '1',
            }
            if network_settings:
                env['DOCKER_SUBNET'] = network_settings.get('subnet', '172.20.0.0/16')
                env['DOCKER_GATEWAY'] = network_settings.get('gateway', '172.20.0.1')
            if suite_env:
                env.update(suite_env)
            node_env = node_spec.get('environment')
            if node_env:
                env.update(node_env)
            svc['environment'] = env

            existing_image = next(
                (v.get('image') for k, v in compose_data.get('services', {}).items()
                 if k.startswith('node-') and v.get('image')),
                None,
            )
            if existing_image:
                svc.pop('build', None)
                svc['image'] = existing_image
                svc['pull_policy'] = 'never'
            elif 'build' not in svc:
                raise ValueError(
                    f"Cannot determine image for extra node {service_name}: "
                    "no existing node has 'image' and template has no 'build'"
                )

            extra_caps = node_spec.get('cap_add')
            if extra_caps:
                existing_caps = svc.get('cap_add', [])
                merged = list(dict.fromkeys(existing_caps + extra_caps))
                svc['cap_add'] = merged

            extra_devices = node_spec.get('docker_devices')
            if extra_devices:
                existing_devices = svc.get('devices', [])
                merged_devices = list(dict.fromkeys(existing_devices + extra_devices))
                svc['devices'] = merged_devices

            compose_data['services'][service_name] = svc
            logger.info("extra_node_service_added",
                       service=service_name, role=node_spec.get('role', 'full'),
                       ip=node_spec['ip_address'])

        with open(self.compose_file, 'w') as f:
            yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)

        logger.info("extra_nodes_added_to_compose", count=len(extra_nodes))

    def add_docker_compose_services(self, services: Dict[str, Any]) -> None:
        """Add arbitrary docker-compose service definitions to the generated compose file.

        Services that don't specify ``networks`` are automatically connected
        to the project network so they can reach cellframe nodes.
        """
        if not self.compose_file or not self.compose_file.exists():
            logger.warning("add_docker_compose_services_no_file",
                           path=str(self.compose_file))
            return

        with open(self.compose_file) as f:
            compose_data = yaml.safe_load(f) or {}

        added = 0
        for svc_name, svc_config in services.items():
            if svc_name in compose_data.get('services', {}):
                logger.debug("docker_compose_service_exists", service=svc_name)
                continue
            if isinstance(svc_config, dict) and 'networks' not in svc_config:
                svc_config['networks'] = [self.network_name]
            compose_data.setdefault('services', {})[svc_name] = svc_config
            added += 1
            logger.info("docker_compose_service_added", name=svc_name)

        if added:
            with open(self.compose_file, 'w') as f:
                yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)
            logger.info("docker_compose_services_written", count=added)

    def merge_compose_file(self, compose_file_path: 'Path') -> None:
        """Merge an external docker-compose file into the generated compose.

        Imports ``services``, ``volumes``, and ``networks`` from
        *compose_file_path* into ``docker-compose.generated.yml``.
        Services without an explicit ``networks`` key are connected to the
        project network automatically (same behaviour as
        :meth:`add_docker_compose_services`).
        """
        from pathlib import Path
        compose_file_path = Path(compose_file_path)

        if not compose_file_path.exists():
            logger.error("merge_compose_file_not_found",
                         path=str(compose_file_path))
            return
        if not self.compose_file or not self.compose_file.exists():
            logger.warning("merge_compose_file_no_generated",
                           path=str(self.compose_file))
            return

        with open(compose_file_path) as f:
            external = yaml.safe_load(f) or {}

        with open(self.compose_file) as f:
            compose_data = yaml.safe_load(f) or {}

        added_svc = 0
        for svc_name, svc_config in (external.get('services') or {}).items():
            if svc_name in compose_data.get('services', {}):
                logger.debug("merge_compose_service_exists", service=svc_name)
                continue
            if isinstance(svc_config, dict) and 'networks' not in svc_config:
                svc_config['networks'] = [self.network_name]
            compose_data.setdefault('services', {})[svc_name] = svc_config
            added_svc += 1
            logger.info("merge_compose_service_added", name=svc_name,
                        source=compose_file_path.name)

        for vol_name, vol_def in (external.get('volumes') or {}).items():
            compose_data.setdefault('volumes', {}).setdefault(vol_name, vol_def)

        for net_name, net_def in (external.get('networks') or {}).items():
            compose_data.setdefault('networks', {}).setdefault(net_name, net_def)

        if added_svc:
            with open(self.compose_file, 'w') as f:
                yaml.dump(compose_data, f, default_flow_style=False,
                          sort_keys=False)
            logger.info("merge_compose_file_done",
                        source=compose_file_path.name,
                        services=added_svc)

    def set_service_images(self, image_map: Dict[str, str]) -> None:
        """
        Override service images in the generated compose file.
        
        Replaces 'build' directive with 'image' for specified services,
        allowing containers to start from committed snapshot images instead
        of rebuilding from Dockerfile.
        
        Args:
            image_map: {"node-9": "snapshot-cdb_ready-node-9", ...}
        """
        if not self.compose_file.exists():
            logger.warning("set_service_images_no_compose_file",
                          path=str(self.compose_file))
            return
        
        with open(self.compose_file, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        services = compose_data.get('services', {})
        applied = 0
        
        for service_name, image_tag in image_map.items():
            if service_name not in services:
                logger.debug("set_service_images_skip_missing",
                           service=service_name)
                continue
            
            svc = services[service_name]
            svc.pop('build', None)
            svc['image'] = image_tag
            svc['pull_policy'] = 'never'
            applied += 1
        
        with open(self.compose_file, 'w') as f:
            yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)
        
        logger.info("service_images_updated",
                   applied=applied,
                   total=len(image_map))
    
    def up(
        self,
        services: Optional[List[str]] = None,
        detach: bool = True,
        wait: bool = True,
        no_build: bool = False,
    ) -> None:
        """
        Start services.
        
        If containers already exist, uses 'start' instead of 'up' to avoid conflicts.
        
        Args:
            services: List of service names (None = all)
            detach: Run in background
            wait: Wait for services to be ready
            no_build: Skip building images (use existing)
        """
        logger.info("starting_services", services=services or "all")
        
        from src.utils.cli import run_command
        import subprocess
        
        # Check if containers already exist (by label and by name pattern)
        # We need to clean up potential stale/colliding containers before starting
        # This is critical for phased startup (Phase 2) where we add new services
        # to an existing project.
        
        target_containers = []
        if services:
            # Find existing containers for the requested services
            all_containers = self.ps()
            for container in all_containers:
                svc_label = container.labels.get("com.docker.compose.service")
                if svc_label and svc_label in services:
                    target_containers.append(container)
            
            # Also check for name collisions for requested services
            # This handles "zombie" containers that might block the new ones
            for service in services:
                # Expected container name pattern: {project}-{service}
                # Note: This is a heuristic, names might differ in compose file
                # but standard node naming follows this.
                potential_name = f"{self.project_name}-{service}"
                try:
                    # Check if container exists by name (even if not part of project)
                    container = self.client.containers.get(potential_name)
                    if container not in target_containers:
                        target_containers.append(container)
                        logger.warning("found_colliding_container_by_name", 
                                     name=potential_name, 
                                     id=container.short_id)
                except NotFound:
                    pass
        
        if target_containers:
            logger.info("removing_conflicting_containers_before_up", 
                       count=len(target_containers),
                       names=[c.name for c in target_containers])
            
            for container in target_containers:
                try:
                    logger.debug("removing_container", name=container.name)
                    container.remove(force=True)
                except Exception as e:
                    logger.warning("failed_to_remove_container", 
                                 name=container.name, 
                                 error=str(e))
            
            # Brief wait to ensure Docker daemon processes removal
            time.sleep(1)
        
        # Build missing images before starting services
        # Check ALL services with build directives, not just the first one
        if not no_build:
            import os
            try:
                with open(self.compose_file, 'r') as f:
                    compose_data = yaml.safe_load(f)

                built_images = set()
                target_services = services or list(compose_data.get('services', {}).keys())

                for svc_name in target_services:
                    svc_data = compose_data.get('services', {}).get(svc_name, {})
                    if 'build' not in svc_data:
                        continue

                    image_template = svc_data.get('image', '')
                    image_name = image_template
                    image_name = image_name.replace('${BUILD_TYPE:-debug}', os.environ.get('BUILD_TYPE', 'debug'))
                    image_name = image_name.replace('${CELLFRAME_VERSION:-latest}', os.environ.get('CELLFRAME_VERSION', 'latest'))

                    if not image_name or image_name in built_images:
                        continue

                    try:
                        self.client.images.get(image_name)
                        logger.info("image_already_exists", image=image_name)
                        continue
                    except NotFound:
                        logger.info("image_not_found_will_build", image=image_name)

                    logger.info("building_image_once", service=svc_name)
                    build_cmd = ["docker", "compose", "-f", str(self.compose_file),
                               "-p", self.project_name, "build", svc_name]
                    try:
                        run_command(build_cmd, cwd=self.project_dir)
                        logger.info("image_built_successfully", image=image_name)
                        built_images.add(image_name)
                    except Exception as e:
                        logger.warning("image_build_failed_will_retry_on_up",
                                     service=svc_name, error=str(e))
            except Exception as e:
                logger.info("failed_to_check_image_existence", error=str(e))
        
        # Now start all services WITHOUT building (image already exists)
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "up", "--no-build"]
        
        if detach:
            cmd.append("-d")
        
        if services:
            cmd.extend(services)
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                run_command(cmd, cwd=self.project_dir)
                break
            except subprocess.CalledProcessError as e:
                stderr_text = getattr(e, 'stderr', '') or ''
                if isinstance(stderr_text, bytes):
                    stderr_text = stderr_text.decode('utf-8', errors='replace')
                is_transient = 'Address already in use' in stderr_text
                if is_transient and attempt < max_retries:
                    wait_secs = 3 * attempt
                    logger.warning("docker_up_transient_failure",
                                   attempt=attempt, retry_in=wait_secs,
                                   error=str(e))
                    time.sleep(wait_secs)
                    continue
                logger.error("docker_up_failed", error=str(e))
                raise
            except Exception as e:
                logger.error("docker_up_failed", error=str(e))
                raise
        
        if wait:
            self.wait_for_services(services)
        
        logger.info("services_started")
    
    def down(self, volumes: bool = False, remove_images: bool = False) -> None:
        """
        Stop and remove services.
        
        Args:
            volumes: Remove volumes
            remove_images: Remove images
        """
        logger.info("stopping_services", volumes=volumes, remove_images=remove_images)
        
        from src.utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "down"]
        
        if volumes:
            cmd.append("--volumes")
        
        if remove_images:
            cmd.append("--rmi all")
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_stopped")
    
    def stop(self, services: Optional[List[str]] = None) -> None:
        """
        Stop running containers without removing them.
        
        Args:
            services: List of service names (None = all)
        """
        logger.info("stopping_services", services=services or "all")
        
        from src.utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "stop"]
        
        if services:
            cmd.extend(services)
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_stopped")
    
    def kill(self, timeout: int = 10) -> None:
        """
        Stop containers gracefully with SIGTERM (docker stop).
        
        Args:
            timeout: Timeout in seconds before force kill
        """
        logger.info("killing_services", timeout=timeout)
        
        from src.utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "stop", "-t", str(timeout)]
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_killed")
    
    def terminate(self) -> None:
        """
        Force kill containers with SIGKILL (docker kill).
        """
        logger.info("terminating_services")
        
        # Get all containers for this project
        containers = self.ps()
        
        if not containers:
            logger.info("no_containers_to_terminate")
            return
        
        # Kill each container directly
        for container in containers:
            try:
                logger.debug("killing_container", name=container.name, id=container.short_id)
                container.kill()
            except Exception as e:
                logger.warning("failed_to_kill_container",
                             name=container.name,
                             error=str(e))
        
        logger.info("services_terminated", count=len(containers))
    
    def restart(self, services: Optional[List[str]] = None) -> None:
        """
        Restart services (stop + start).
        
        If containers don't exist, they will be created first via 'up'.
        This handles the case when containers were removed but need to be restarted.
        
        Args:
            services: List of service names (None = all)
        """
        logger.info("restarting_services", services=services or "all")
        
        from src.utils.cli import run_command
        
        # First, ensure all requested services exist by running 'up -d'
        # This creates containers that don't exist yet, and does nothing for running ones
        up_cmd = ["docker", "compose", "-f", str(self.compose_file),
                  "-p", self.project_name, "up", "-d", "--no-recreate"]
        
        if services:
            up_cmd.extend(services)
        
        run_command(up_cmd, cwd=self.project_dir)
        logger.info("services_ensured_exist")
        
        # Now restart all the services (they all exist now)
        restart_cmd = ["docker", "compose", "-f", str(self.compose_file),
                       "-p", self.project_name, "restart"]
        
        if services:
            restart_cmd.extend(services)
        
        run_command(restart_cmd, cwd=self.project_dir)
        logger.info("services_restarted")
    
    def pause(self, services: Optional[List[str]] = None) -> None:
        """
        Pause running containers (freeze processes).
        
        Args:
            services: List of service names (None = all)
        """
        logger.info("pausing_services", services=services or "all")
        
        from src.utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "pause"]
        
        if services:
            cmd.extend(services)
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_paused")
    
    def unpause(self, services: Optional[List[str]] = None) -> None:
        """
        Unpause containers (resume processes).
        
        Args:
            services: List of service names (None = all)
        """
        logger.info("unpausing_services", services=services or "all")
        
        from src.utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "unpause"]
        
        if services:
            cmd.extend(services)
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_unpaused")
    
    def ps(self) -> List[Container]:
        """
        List running containers for this project.
        
        Returns:
            List of Container objects
        """
        filters = {"label": f"com.docker.compose.project={self.project_name}"}
        containers = self.client.containers.list(filters=filters, all=True)
        
        logger.debug("containers_listed", count=len(containers))
        return containers
    
    def logs(
        self,
        service: str,
        follow: bool = False,
        tail: int = 100,
    ) -> str:
        """
        Get logs for a service.
        
        Args:
            service: Service name
            follow: Follow log output
            tail: Number of lines from end
            
        Returns:
            Log output as string
        """
        containers = self.ps()
        
        for container in containers:
            labels = container.labels
            if labels.get("com.docker.compose.service") == service:
                logger.debug("fetching_logs", service=service, tail=tail)
                
                if follow:
                    # For follow, return generator
                    return container.logs(stream=True, follow=True, tail=tail)
                else:
                    return container.logs(tail=tail).decode("utf-8")
        
        raise NotFound(f"Service '{service}' not found")
    
    def exec(
        self,
        service: str,
        command: List[str],
    ) -> tuple[int, str]:
        """
        Execute command in service container.
        
        Args:
            service: Service name
            command: Command to execute
            
        Returns:
            Tuple of (exit_code, output)
        """
        containers = self.ps()
        
        for container in containers:
            labels = container.labels
            if labels.get("com.docker.compose.service") == service:
                logger.debug("executing_command", 
                           service=service,
                           command=" ".join(command))
                
                result = container.exec_run(command)
                return result.exit_code, result.output.decode("utf-8")
        
        raise NotFound(f"Service '{service}' not found")
    
    def _check_container_logs_for_errors(self, container: Container) -> Optional[str]:
        """
        Check container logs for critical errors.
        
        Args:
            container: Container to check
            
        Returns:
            Error message if found, None otherwise
        """
        try:
            # Get last 50 lines of logs
            logs = container.logs(tail=50).decode("utf-8", errors="ignore")
            
            # Critical error patterns
            critical_patterns = [
                "CRITICAL",
                "FATAL",
                "Segmentation fault",
                "core dumped",
                "Cannot allocate memory",
                "Address already in use",
                "Permission denied",
            ]
            
            # Check "No such file or directory" only for non-cert files
            # SDK tries /var/lib/ca first, then /share/ca - ERR is expected and not critical
            if "No such file or directory" in logs and "/opt/cellframe-node" in logs:
                # Exclude cert file errors if followed by successful "Initialized auth cert"
                if "/ca/" in logs and "Initialized auth cert" in logs:
                    pass  # Not critical - cert loaded from alternative path
                else:
                    critical_patterns.append("No such file or directory")
            
            for pattern in critical_patterns:
                if pattern and pattern in logs:
                    # Extract context around error
                    lines = logs.split('\n')
                    for i, line in enumerate(lines):
                        if pattern in line:
                            # Get 3 lines before and after
                            context_start = max(0, i - 3)
                            context_end = min(len(lines), i + 4)
                            context = '\n'.join(lines[context_start:context_end])
                            return f"Critical error found: {pattern}\n{context}"
            
            return None
        except Exception as e:
            logger.warning("failed_to_check_logs", container=container.name, error=str(e))
            return None
    
    def _check_network_status(self, container: Container) -> Optional[str]:
        """
        Check network status in Cellframe node logs.
        
        Returns network state: "SYNC", "OFFLINE", "ONLINE", or None if unknown
        """
        try:
            logs = container.logs(tail=200).decode("utf-8", errors="ignore")
            
            # Find LAST occurrence of state (most recent state wins)
            last_online_pos = max(logs.rfind("NET_STATE_ONLINE"), logs.rfind("state ONLINE"))
            last_sync_pos = max(logs.rfind("NET_STATE_SYNC_CHAINS"), logs.rfind("Synchronizing"))
            last_offline_pos = max(logs.rfind("NET_STATE_OFFLINE"), logs.rfind("state OFFLINE"))
            
            # Determine which state appeared last in logs
            positions = {
                "ONLINE": last_online_pos,
                "SYNC": last_sync_pos,
                "OFFLINE": last_offline_pos
            }
            
            # Filter out -1 (not found) and get max position
            valid_positions = {state: pos for state, pos in positions.items() if pos >= 0}
            if valid_positions:
                return max(valid_positions, key=valid_positions.get)
            
            return None
        except Exception as e:
            logger.warning("failed_to_check_network_status",
                         container=container.name,
                         error=str(e))
            return None
    
    def _check_port_listening(self, container: Container, port: int = 8079) -> bool:
        """
        Check if node is listening on specified port.
        
        Args:
            container: Container to check
            port: Port number to check
            
        Returns:
            True if port is listening, False otherwise
        """
        try:
            # Check if port is listening using netstat or ss
            result = container.exec_run(
                f"sh -c 'netstat -tuln 2>/dev/null | grep :{port} || ss -tuln 2>/dev/null | grep :{port}'",
                demux=False
            )
            
            if result.exit_code == 0 and result.output:
                output = result.output.decode("utf-8", errors="ignore")
                # Check if listening on 0.0.0.0 or specific IP
                if f":{port}" in output and ("LISTEN" in output or "0.0.0.0" in output):
                    logger.debug("port_listening",
                               container=container.name,
                               port=port)
                    return True
            
            logger.warning("port_not_listening",
                         container=container.name,
                         port=port)
            return False
        except Exception as e:
            logger.warning("failed_to_check_port",
                         container=container.name,
                         port=port,
                         error=str(e))
            return False
    
    def _check_peer_connectivity(self, container: Container) -> Dict[str, bool]:
        """
        Check if node can connect to its configured peers.
        
        Args:
            container: Container to check
            
        Returns:
            Dict mapping peer addresses to connectivity status
        """
        try:
            # Get logs to find seed nodes and check connection attempts
            logs = container.logs(tail=100).decode("utf-8", errors="ignore")
            
            connectivity = {}
            
            # Look for connection refused errors
            connection_errors = []
            for line in logs.split('\n'):
                if "Connection refused" in line or "errno 111" in line:
                    # Extract peer address from error message
                    import re
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+):(\d+)', line)
                    if match:
                        peer = f"{match.group(1)}:{match.group(2)}"
                        connection_errors.append(peer)
                        connectivity[peer] = False
            
            if connection_errors:
                logger.warning("peer_connection_failures",
                             container=container.name,
                             failed_peers=connection_errors)
                return connectivity
            
            # If no errors found, assume connectivity is OK
            return connectivity
        except Exception as e:
            logger.warning("failed_to_check_peer_connectivity",
                         container=container.name,
                         error=str(e))
            return {}
    
    def _perform_early_diagnostics(self, containers: List[Container]) -> Optional[str]:
        """
        Perform early diagnostics to catch common issues quickly.
        
        This runs after a short grace period (15-20s) to detect:
        - Ports not listening
        - Connection refused errors between nodes
        - Missing configuration
        
        Args:
            containers: List of containers to check
            
        Returns:
            Error message if critical issue found, None otherwise
        """
        issues = []
        
        for container in containers:
            service_name = container.labels.get("com.docker.compose.service", "unknown")
            container.reload()
            
            if container.status != "running":
                continue
            
            # Check if port 8079 is listening
            if not self._check_port_listening(container, 8079):
                issues.append(
                    f"{service_name}: Port 8079 not listening (check listen_address/listen_port_tcp in config)"
                )
            
            # Check peer connectivity
            peer_issues = self._check_peer_connectivity(container)
            if peer_issues:
                failed_peers = [peer for peer, status in peer_issues.items() if not status]
                if failed_peers:
                    issues.append(
                        f"{service_name}: Cannot connect to peers: {', '.join(failed_peers)}"
                    )
        
        if issues:
            error_msg = (
                "Early diagnostics detected critical issues:\n" +
                "\n".join(f"  • {issue}" for issue in issues) +
                "\n\nCommon fixes:\n" +
                "  1. Check listen_address=[0.0.0.0:8079] in cellframe-node.cfg\n" +
                "  2. Ensure all nodes have correct seed_nodes_hosts configuration\n" +
                "  3. Verify Docker network connectivity between containers"
            )
            return error_msg
        
        return None
    
    def _get_node_loading_status(self, container: Container) -> str:
        """
        Get detailed node loading status with progress information.
        
        Returns:
            Status string like: "NET_STATE_ONLINE" or "LINKS_CONNECTING (2/3)" or "Initializing consensus"
        """
        try:
            # Use cellframe-node-cli to get current state (most reliable)
            cli_result = container.exec_run(
                f'cellframe-node-cli net get status -net {self.network_name}',
                demux=False
            )
            
            if cli_result.exit_code == 0:
                output = cli_result.output.decode("utf-8")
                # Try JSON format (6.0+)
                try:
                    import json
                    parsed = json.loads(output.strip())
                    if isinstance(parsed, list) and len(parsed) > 0:
                        item = parsed[0]
                        if isinstance(item, dict):
                            status = item.get("status", item)
                            states = status.get("states", {})
                            state = states.get("current", "")
                            if state:
                                links = status.get("links", {})
                                active = links.get("active", 0)
                                required = links.get("required", 0)
                                if "NET_STATE_LINKS_CONNECTING" in state:
                                    return f"NET_STATE_LINKS_CONNECTING ({active}/{required} links)"
                                return state
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
                # Fall back to text format (5.x)
                for line in output.split('\n'):
                    line = line.strip()
                    if 'current:' in line and 'NET_STATE_' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            state = parts[1].strip()
                            if "NET_STATE_LINKS_CONNECTING" in state or "NET_STATE_ONLINE" in state:
                                for info_line in output.split('\n'):
                                    if 'active:' in info_line:
                                        try:
                                            active = int(info_line.split(':')[1].strip())
                                            for req_line in output.split('\n'):
                                                if 'required:' in req_line:
                                                    required = int(req_line.split(':')[1].strip())
                                                    if "NET_STATE_LINKS_CONNECTING" in state:
                                                        return f"NET_STATE_LINKS_CONNECTING ({active}/{required} links)"
                                                    break
                                        except:
                                            pass
                            return state
                return "Loading"
            
            # Fallback to log parsing
            logs = container.logs(tail=200).decode("utf-8", errors="ignore")
            
            # Check for CURRENT state first (most recent messages)
            # Split by lines and check from bottom to top
            lines = logs.split('\n')
            for line in reversed(lines[-50:]):  # Check last 50 lines
                if "NET_STATE_ONLINE" in line and "target:" not in line.lower():
                    return "NET_STATE_ONLINE"
                if "NET_STATE_SYNC_CHAINS" in line and "target:" not in line.lower():
                    return "Syncing chains"
                if "NET_STATE_LINKS_CONNECTING" in line and "target:" not in line.lower():
                    return "Connecting to peers"
                if "NET_STATE_OFFLINE" in line and "target:" not in line.lower():
                    return "NET_STATE_OFFLINE"
            
            # Check for initialization phases (only if no state found above)
            if "Initializing consensus" in logs or "consensus.state: SYNC" in logs:
                return "Initializing consensus"
            if "Loading chain" in logs or "Loaded chain files" in logs:
                return "Loading chains"
            
            return "Starting"
            
        except Exception as e:
            logger.warning("failed_to_get_loading_status",
                         container=container.name,
                         error=str(e))
            return "Unknown"
    
    def _check_node_online_status(self, container: Container) -> bool:
        """
        Check if Cellframe node is actually ONLINE by examining logs and network state.
        
        Args:
            container: Container to check
            
        Returns:
            True if node is online, False otherwise
        """
        try:
            # Get recent logs
            logs = container.logs(tail=200).decode("utf-8", errors="ignore")
            
            # Check for critical network initialization
            if "No networks initialized!" in logs:
                logger.warning("no_networks_initialized",
                             container=container.name)
                return False
            
            if "Can't find any nets" in logs:
                logger.warning("no_nets_found",
                             container=container.name)
                return False
            
            # Use cellframe-node-cli to check ONLINE status
            cli_result = container.exec_run(
                f'cellframe-node-cli net get status -net {self.network_name}',
                demux=False
            )
            
            if cli_result.exit_code == 0:
                output = cli_result.output.decode("utf-8")
                current_state = None
                for line in output.split('\n'):
                    line = line.strip()
                    if 'current:' in line and 'NET_STATE_' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            current_state = parts[1].strip()
                            break
                if current_state:
                    logger.debug("cli_state_check", container=container.name, state=current_state)
                    if current_state in ["NET_STATE_ONLINE", "NET_STATE_SYNC_CHAINS"]:
                        logger.info("network_ready_via_cli",
                                   container=container.name,
                                   state=current_state)
                        return True
                    logger.debug("network_not_ready_via_cli",
                               container=container.name,
                               state=current_state)
                    return False
                logger.debug("no_state_in_cli_output", container=container.name)
                return False
            
            # Fallback: Check network status via logs
            net_status = self._check_network_status(container)
            if net_status in ["ONLINE", "SYNC"]:
                logger.debug("network_ready_via_logs",
                           container=container.name,
                           status=net_status)
                return True
            
            logger.debug("network_not_ready",
                       container=container.name,
                       status=net_status or "UNKNOWN")
            return False
            
        except Exception as e:
            logger.warning("failed_to_check_node_status",
                         container=container.name,
                         error=str(e))
            return False
    
    def _register_root_nodes(self, containers: List[Container]) -> None:
        """
        Register root nodes in node list using CLI command.
        
        Root nodes need to register themselves in the node list to act as balancers
        for other nodes (master and full nodes).
        
        Similar to tests-in-docker-example: one root node (node-1) registers all root nodes.
        
        Args:
            containers: List of containers to check and register
        """
        import re
        
        # Collect info about all root nodes (first 3 nodes)
        root_nodes = []
        for container in containers:
            service_name = container.labels.get("com.docker.compose.service", "unknown")
            
            if not service_name.startswith("node-"):
                continue
            
            try:
                node_num = int(service_name.split("-")[1])
            except (IndexError, ValueError):
                continue
            
            if node_num > 3:
                continue
            
            try:
                # Get node address
                dump_result = container.exec_run(
                    f"/opt/cellframe-node/bin/cellframe-node-cli node dump -net {self.network_name}",
                    demux=True
                )
                
                if dump_result.exit_code != 0:
                    logger.warning("failed_to_get_node_address",
                                 node=service_name)
                    continue
                
                output = dump_result.output[0].decode('utf-8') if dump_result.output[0] else ""
                match = re.search(r'Node addr:\s*([0-9A-F:]+)', output)
                if not match:
                    continue
                
                node_addr = match.group(1)
                
                # Get container IP
                container.reload()
                networks = container.attrs['NetworkSettings']['Networks']
                container_ip = None
                for net_name, net_settings in networks.items():
                    if net_settings.get('IPAddress'):
                        container_ip = net_settings['IPAddress']
                        break
                
                if not container_ip:
                    continue
                
                root_nodes.append({
                    'container': container,
                    'service_name': service_name,
                    'node_num': node_num,
                    'addr': node_addr,
                    'ip': container_ip
                })
            except Exception as e:
                logger.error("failed_to_collect_root_node_info",
                           node=service_name,
                           error=str(e))
        
        if not root_nodes:
            logger.warning("no_root_nodes_found")
            return
        
        # Wait for node-1 to become ROOT (has authorization)
        # Then use it to register all root nodes
        node1 = next((n for n in root_nodes if n['node_num'] == 1), None)
        if not node1:
            logger.warning("node_1_not_found_for_registration")
            return
        
        # Wait up to 30 seconds for node-1 to have ROOT role
        logger.info("waiting_for_node1_root_role")
        max_wait = 30
        wait_interval = 2
        
        for attempt in range(max_wait // wait_interval):
            # Try to execute node list to check if we have ROOT rights
            test_result = node1['container'].exec_run(
                f"/opt/cellframe-node/bin/cellframe-node-cli node list -net {self.network_name}",
                demux=True
            )
            
            output = test_result.output[0].decode('utf-8') if test_result.output and test_result.output[0] else ""
            
            if "You have no access rights" not in output:
                logger.info("node1_has_root_role", elapsed=f"{attempt * wait_interval}s")
                break
            
            time.sleep(wait_interval)
        else:
            logger.warning("node1_root_role_timeout", waited=f"{max_wait}s")
            # Continue anyway - balancer will handle it
            return
        
        # Now register all root nodes via node-1
        for node_info in root_nodes:
            try:
                exec_result = node1['container'].exec_run(
                    f"/opt/cellframe-node/bin/cellframe-node-cli node add -net {self.network_name} -addr {node_info['addr']} -host {node_info['ip']} -port 8079",
                    demux=True
                )
                
                if exec_result.exit_code == 0:
                    output = exec_result.output[0].decode('utf-8').strip() if exec_result.output[0] else ""
                    
                    # Check if actually succeeded (not "You have no access rights")
                    if "You have no access rights" in output:
                        logger.debug("root_registration_no_rights",
                                   registered_by="node-1",
                                   target=node_info['service_name'])
                    else:
                        logger.info("root_node_registered",
                                  registered_by="node-1",
                                  target_node=node_info['service_name'],
                                  addr=node_info['addr'],
                                  ip=node_info['ip'],
                                  output=output)
                else:
                    error_msg = exec_result.output[1].decode('utf-8').strip() if exec_result.output[1] else "Unknown error"
                    logger.debug("root_node_registration_failed",
                               registered_by="node-1",
                               target_node=node_info['service_name'],
                               error=error_msg)
            except Exception as e:
                logger.debug("failed_to_register_root_node",
                           registered_by="node-1",
                           target_node=node_info['service_name'],
                           error=str(e))
    
    def wait_for_services(
        self,
        services: Optional[List[str]] = None,
        timeout: int = 300,
        check_logs: bool = True,
    ) -> None:
        """
        Wait for services to be healthy and online.
        
        This method performs comprehensive checks:
        1. Container is running
        2. No critical errors in logs
        3. Node has transitioned to ONLINE state
        4. Immediate failure detection
        5. Early diagnostics after 15-20s (port listening, peer connectivity)
        
        Args:
            services: List of service names (None = all)
            timeout: Timeout in seconds
            check_logs: Whether to check logs for errors
        """
        logger.info("waiting_for_services", timeout=timeout, check_logs=check_logs)
        
        start_time = time.time()
        last_status_log = 0
        early_diagnostics_run = False
        
        while time.time() - start_time < timeout:
            containers = self.ps()  # Get all containers including stopped
            
            # Run early diagnostics after 15-20 seconds to catch configuration issues early
            current_time = time.time()
            if not early_diagnostics_run and (current_time - start_time) >= 15:
                logger.info("running_early_diagnostics", elapsed=f"{int(current_time - start_time)}s")
                diagnostic_error = self._perform_early_diagnostics(containers)
                if diagnostic_error:
                    logger.error("early_diagnostics_failed", error=diagnostic_error)
                    raise RuntimeError(f"Early diagnostics failed:\n{diagnostic_error}")
                else:
                    logger.info("early_diagnostics_passed")
                # Wait a bit more for nodes to fully initialize server components
                time.sleep(10)
                # Register root nodes immediately after diagnostics pass
                # This breaks the circular dependency: nodes need registered root nodes to go ONLINE
                self._register_root_nodes(containers)
                early_diagnostics_run = True
            
            if not containers:
                logger.debug("no_containers_found")
                time.sleep(2)
                continue
            
            all_healthy = True
            failed_containers = []
            pending_containers = []
            
            for container in containers:
                # Check if this is one of our target services
                service_name = container.labels.get("com.docker.compose.service")
                
                if services and service_name not in services:
                    continue
                
                # Refresh container state
                container.reload()
                
                # CRITICAL: Check if container has exited
                if container.status in ["exited", "dead", "removing"]:
                    exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                    
                    # Get last logs before failure
                    try:
                        logs = container.logs(tail=30).decode("utf-8", errors="ignore")
                    except Exception:
                        logs = "(unable to fetch logs)"
                    
                    error_msg = (
                        f"Container {service_name} has FAILED!\n"
                        f"Status: {container.status}\n"
                        f"Exit code: {exit_code}\n"
                        f"Last logs:\n{logs}"
                    )
                    
                    logger.error("container_failed",
                               service=service_name,
                               status=container.status,
                               exit_code=exit_code)
                    
                    raise RuntimeError(error_msg)
                
                # Check if running
                if container.status != "running":
                    all_healthy = False
                    pending_containers.append(service_name)
                    continue
                
                # Check for critical errors in logs
                if check_logs:
                    error = self._check_container_logs_for_errors(container)
                    if error:
                        logger.error("critical_error_in_logs",
                                   service=service_name,
                                   error=error)
                        raise RuntimeError(
                            f"Critical error detected in {service_name}:\n{error}"
                        )
                
                # If container has health check, verify it
                health = container.attrs.get("State", {}).get("Health", {})
                if health:
                    health_status = health.get("Status")
                    if health_status == "unhealthy":
                        all_healthy = False
                        failed_containers.append(f"{service_name} (unhealthy)")
                        continue
                    elif health_status != "healthy":
                        all_healthy = False
                        pending_containers.append(f"{service_name} ({health_status})")
                        continue
                
                # Check if node is actually ONLINE and get detailed status
                if not self._check_node_online_status(container):
                    all_healthy = False
                    # Get detailed loading status for better visibility
                    loading_status = self._get_node_loading_status(container)
                    pending_containers.append(f"{service_name} ({loading_status})")
                    continue
            
            # Log status periodically
            current_time = time.time()
            if current_time - last_status_log >= 5:
                elapsed = int(current_time - start_time)
                if pending_containers:
                    logger.info("waiting_progress",
                              elapsed=f"{elapsed}s",
                              pending=", ".join(pending_containers))
                last_status_log = current_time
            
            if all_healthy and containers:
                logger.info("services_ready", elapsed=f"{int(time.time() - start_time)}s")
                return
            
            time.sleep(2)
        
        # Timeout reached
        containers = self.ps()
        status_info = []
        for container in containers:
            service_name = container.labels.get("com.docker.compose.service", "unknown")
            container.reload()
            status_info.append(f"{service_name}: {container.status}")
        
        error_msg = (
            f"Services not ready after {timeout}s\n"
            f"Status: {', '.join(status_info)}"
        )
        logger.error("services_timeout", timeout=timeout, status=status_info)
        raise TimeoutError(error_msg)
    
    def get_service_status(self) -> Dict[str, str]:
        """
        Get status of all services.
        
        Returns:
            Dict mapping service name to status
        """
        containers = self.ps()
        
        status = {}
        for container in containers:
            service = container.labels.get("com.docker.compose.service", "unknown")
            status[service] = container.status
        
        return status
    
    def are_services_running(self, services: List[str]) -> bool:
        """
        Check if all specified services are running.
        
        Args:
            services: List of service names to check (e.g., ['node-4', 'node-5'])
            
        Returns:
            True if ALL specified services are running, False otherwise
        """
        status = self.get_service_status()
        for service in services:
            if service not in status or status[service] != "running":
                return False
        return True
    
    def clean_cache_data(self, cache_path: Path) -> None:
        """
        Clean cache/data directory using temporary Docker container.
        
        This method runs a minimal Alpine container to remove cache/data/
        directory. Using Docker ensures proper permissions for files created
        by other containers (owned by root inside containers).
        
        Args:
            cache_path: Path to cache directory (parent of data/)
            
        Raises:
            RuntimeError: If cleanup fails
        """
        data_dir = cache_path / "data"
        
        if not data_dir.exists():
            logger.debug("cache_data_not_exists", path=str(data_dir))
            return
        
        logger.info("cleaning_cache_data_with_docker", path=str(data_dir))
        
        try:
            target_path = f"{CLEANUP_MOUNT_PATH}/data"
            cleanup_cmd = CLEANUP_CMD_TEMPLATE.format(target=target_path)
            
            container = self.client.containers.run(
                image=CLEANUP_IMAGE,
                command=["sh", "-c", cleanup_cmd],
                volumes={
                    str(cache_path.absolute()): {
                        'bind': CLEANUP_MOUNT_PATH,
                        'mode': 'rw'
                    }
                },
                remove=True,
                detach=False,
            )
            
            logger.info("cache_data_cleaned", 
                       output=container.decode('utf-8').strip() if isinstance(container, bytes) else str(container))
            
        except Exception as e:
            logger.error("cache_data_cleanup_failed", error=str(e))
            raise RuntimeError(f"Failed to clean cache data: {e}")

