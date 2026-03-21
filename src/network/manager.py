"""
Network manager for cellframe test environment.

Manages the lifecycle of test network:
- Dynamic node creation based on topology
- Node startup/shutdown
- Network readiness checking
- Node discovery and configuration
- Snapshot-based suite isolation for fast environment restoration
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import traceback

from ..config.loader import NetworkTopology
from ..config.generator import ConfigGenerator
from ..docker.compose import DockerComposeManager
from ..monitoring.health import HealthChecker, HealthStatus
from ..monitoring.network_consensus import NetworkConsensusMonitor
from src.utils.logger import get_logger
from src.utils.artifacts import ArtifactsManager
from src.utils.project import get_project_name
from ..snapshots.manager import SnapshotManager, SnapshotMode
from .models import NodeConfig
from .genesis import GenesisInitializer
from .node_lifecycle import NodeLifecycleManager
from .node_states import NodeStateManager

logger = get_logger(__name__)


class NetworkManager:
    """Manage cellframe test network lifecycle."""
    
    def __init__(self, base_path: Path, topology_name: str = "default", config_path: Optional[Path] = None):
        """
        Initialize network manager.
        
        Args:
            base_path: Base path to stage-env directory
            topology_name: Name of topology to use
            config_path: Optional path to stage-env.cfg
        """
        self.base_path = base_path
        self.topology_name = topology_name
        self.config_path = config_path
        
        # Keep containers running after tests (for debugging)
        self.keep_running = False

        # prepare()/start() phase tracking
        self._prepared = False
        self._snapshot_clean_state_restored = False
        self._snapshot_phase1_restored = False

        # Docker-compose services from suite descriptor
        self.docker_compose: Dict[str, Any] = {}
        
        # CLI path for node commands
        self.node_cli_path = "cellframe-node-cli"
        
        # Load configuration using global config manager
        from ..config.manager import get_config_loader
        self.config_loader = get_config_loader()
        self.topology = self.config_loader.load_topology(topology_name)
        
        # Config generator
        self.config_generator = ConfigGenerator(base_path, config_path)
        
        # Docker compose manager
        self.compose = DockerComposeManager(
            base_path,
            project_name=get_project_name(),
            network_name=self.topology.network.name
        )
        
        # Health checker
        self.health_checker = HealthChecker()
        
        # Genesis initializer
        self.genesis = GenesisInitializer(
            base_path,
            network_name=self.topology.network.name,
            config_path=config_path
        )
        
        # Node lifecycle manager for graceful restarts
        self.lifecycle = NodeLifecycleManager(project_name=self.compose.project_name)
        
        # Node state manager for intelligent waiting
        self.state_manager = NodeStateManager(
            docker_client=self.genesis.docker_client,
            project_name=self.compose.project_name,
            cli_path=self.node_cli_path,
            network_name=self.topology.network.name
        )
        
        # Inject state_manager into genesis managers for intelligent state waiting
        self.genesis.registration_mgr.state_manager = self.state_manager
        
        # Node configurations
        self.nodes: Dict[str, NodeConfig] = {}
        
        # Load timeouts from config
        self.timeouts = self.config_loader.get_timeouts()
        
        # Load paths from config
        self.paths_config = self.config_loader.get_paths_config()
        
        # Initialize artifacts manager
        artifacts_config = self.config_loader.get_artifacts_config()
        self.artifacts_manager = ArtifactsManager(base_path, artifacts_config)
        
        suite_isolation_config = self.config_loader.get_suite_isolation_config()

        snapshot_config = dict(suite_isolation_config)
        snapshot_config['cache_dir'] = self.paths_config.get('cache_dir', '../../cache')

        disabled = suite_isolation_config.get('mode', '').lower() == 'disabled'

        self.snapshot_manager = SnapshotManager(
            base_path,
            config=snapshot_config,
            compose_manager=self.compose,
            mode=SnapshotMode.DISABLED if disabled else None,
        )
        
        self.suite_isolation_config = suite_isolation_config
        
        # Initialize global scenario context
        from ..scenarios.global_context import ScenarioGlobalContext
        self.scenario_context = ScenarioGlobalContext(
            network_name=self.topology.network.name,
            topology_name=topology_name,
            docker_client=self.genesis.docker_client,
            native_ticker=getattr(self.topology.network, 'native_ticker', 'TCELL')
        )
        
        # Detect node major version for versioned genesis scenarios
        self._genesis_version_dir = self._detect_genesis_version()
        
        logger.info("network_manager_initialized",
                   topology=topology_name,
                   network=self.topology.network.name,
                   timeouts=self.timeouts,
                   cache_dir=self.paths_config.get('cache_dir'),
                   snapshot_mode=self.snapshot_manager.mode.value)
    
    def generate_node_configs(self) -> List[NodeConfig]:
        """
        Generate node configurations from topology.
        
        Returns:
            List of NodeConfig objects
        """
        logger.info("generating_node_configs")
        
        configs = []
        node_counter = 1
        
        # Base settings from topology
        settings = self.topology.network_settings
        
        for node_type, node_spec in self.topology.topology.items():
            for i in range(node_spec.count):
                # Determine if seed node and balancer based on topology spec
                is_seed = getattr(node_spec, 'is_seed_node', node_spec.role == 'root')
                balancer_enabled = getattr(node_spec, 'balancer_enabled', node_spec.role == 'root')
                consensus_participation = getattr(node_spec, 'consensus_participation', False)
                
                config = NodeConfig(
                    node_id=node_counter,
                    role=node_spec.role,
                    node_type=node_type,
                    rpc_port=settings.base_rpc_port + node_counter - 1,
                    p2p_port=settings.base_p2p_port + node_counter - 1,
                    cf_port=settings.base_cf_port + node_counter - 1,
                    http_port=settings.base_http_port + node_counter - 1,
                    ip_address=self._calculate_ip(
                        settings.base_ip,
                        node_counter
                    ),
                    is_seed_node=is_seed,
                    balancer_enabled=balancer_enabled,
                    consensus_participation=consensus_participation
                )
                
                configs.append(config)
                self.nodes[f"node{node_counter}"] = config
                node_counter += 1
        
        logger.info("node_configs_generated",
                   count=len(configs),
                   seed_nodes=sum(1 for c in configs if c.is_seed_node),
                   validators=sum(1 for c in configs if c.consensus_participation))
        return configs
    
    def _calculate_ip(self, base_ip: str, node_id: int) -> str:
        """
        Calculate node IP address.
        
        Args:
            base_ip: Base IP (e.g., "172.20.0.10")
            node_id: Node ID
            
        Returns:
            IP address string
        """
        parts = base_ip.split(".")
        last_octet = int(parts[3]) + node_id - 1
        return f"{parts[0]}.{parts[1]}.{parts[2]}.{last_octet}"
    
    def _detect_genesis_version(self) -> str:
        """Choose genesis scenario directory version.

        Priority:
          1. ``[build] genesis_version`` from stage-env config (e.g. ``v5.8``)
          2. ``stable`` symlink in scenarios/genesis/ (default)
          3. Auto-detect from available ``vN.x`` directories (lowest first)
        """
        default_dir = "stable"
        genesis_base = self.base_path / "scenarios" / "genesis"

        stage_config = self.config_loader.load_stage_config()
        configured = stage_config.get('genesis_version')
        if configured:
            configured = str(configured).strip()
            if (genesis_base / configured).is_dir():
                logger.info("genesis_version_from_config", version_dir=configured)
                return configured
            logger.warning("genesis_version_config_dir_missing",
                           configured=configured, fallback=default_dir)

        if (genesis_base / "stable").exists():
            logger.info("genesis_version_stable_symlink", version_dir="stable")
            return "stable"

        available = sorted(
            d.name for d in genesis_base.iterdir()
            if d.is_dir() and d.name.startswith("v")
        ) if genesis_base.is_dir() else []

        if available:
            default_dir = available[0]
            logger.info("genesis_version_auto_selected", version_dir=default_dir, available=available)
        else:
            logger.warning("genesis_no_version_dirs", path=str(genesis_base))

        return default_dir

    def _sdk_branch_for_tools(self) -> str:
        """Derive dap-sdk git branch from genesis version (v5.8 -> release-5.8)."""
        ver = self._genesis_version_dir
        if ver and ver.startswith("v"):
            return f"release-{ver[1:]}"
        return "release-6.0"

    async def prepare(self, rebuild: bool = False) -> None:
        """Restore snapshot, generate configs and compose — but do NOT start containers.

        After calling ``prepare()`` the host data directories contain
        consistent, static data that can be safely cloned by
        ``_provision_node_compose``.  Call ``start()`` afterwards to
        bring the containers up.
        """
        logger.info("preparing_network",
                   topology=self.topology_name,
                   rebuild=rebuild)

        try:
            self.compose.down(volumes=False, remove_images=False)
        except Exception:
            pass
        self.compose.cleanup_stale_resources()

        await self._restore_snapshots()

        if not self.nodes:
            node_configs = self.generate_node_configs()
        else:
            node_configs = list(self.nodes.values())

        snapshot_restored = self._snapshot_clean_state_restored or self._snapshot_phase1_restored
        if not snapshot_restored:
            self.config_generator.generate_all(self.topology, node_configs, force=rebuild)
        else:
            self._remap_seed_nodes_for_shard(node_configs)

        cache_dir_relative = self.paths_config.get('cache_dir', 'cache')
        node_source_config = self.config_loader.get_node_source_config()
        settings = self.topology.network_settings
        self.compose.generate_compose_for_nodes(
            node_configs,
            build_type=node_source_config.get('build_type', 'debug') if node_source_config else 'debug',
            cache_dir_relative=cache_dir_relative,
            node_source_config=node_source_config,
            network_settings={
                'subnet': settings.subnet,
                'base_ip': settings.base_ip,
            },
            extra_services=self.docker_compose or None,
        )
        if rebuild:
            self.compose.build(no_cache=rebuild)

        self._prepared = True

    def _default_phase1_name(self) -> str:
        return f"phase1_zerochain_genesis_{self.topology.network.name}"

    def _remap_seed_nodes_for_shard(self, node_configs) -> None:
        """Adapt snapshot data for the current shard subnet.

        Snapshot data originates from the genesis shard (shard-0).  In parallel
        mode every shard uses a shifted subnet, so we remap
        ``seed_nodes_hosts`` IPs in **all** network configs (not just the
        primary network).  Nodes may be configured for multiple networks
        (e.g. ``vpntest`` + ``stagenet``); leaving any config un-remapped
        causes TCP SYN hangs to unreachable shard-0 IPs.

        GDB is intentionally preserved: the balancer requires the node list
        stored there to return peers (HTTP 204 otherwise).  Stale shard-0 IPs
        in GDB entries are corrected by nodes re-registering on startup.
        """
        import re as _re

        settings = self.topology.network_settings
        base_ip_parts = settings.base_ip.split('.')
        new_prefix = '.'.join(base_ip_parts[:3])

        cache_dir = self.paths_config.get('cache_dir', 'cache')
        configs_cache = (self.base_path / cache_dir / 'configs').resolve()

        seed_re = _re.compile(r'(?m)^(seed_nodes_hosts\s*=\s*)\[([^\]]*)\]')

        def _remap(hosts_str):
            remapped = []
            for entry in hosts_str.split(','):
                entry = entry.strip()
                if not entry:
                    continue
                ip_port = entry.split(':')
                if len(ip_port) == 2:
                    old_octets = ip_port[0].split('.')
                    remapped.append(f"{new_prefix}.{old_octets[3]}:{ip_port[1]}")
                else:
                    remapped.append(entry)
            return '[' + ','.join(remapped) + ']'

        patched = 0
        for node in node_configs:
            net_dir = configs_cache / f"node{node.node_id}" / "network"
            if not net_dir.is_dir():
                continue
            for net_cfg in net_dir.glob("*.cfg"):
                content = net_cfg.read_text()
                new_content = seed_re.sub(
                    lambda m: m.group(1) + _remap(m.group(2)),
                    content,
                )
                if new_content != content:
                    net_cfg.write_text(new_content)
                    patched += 1

        if patched:
            logger.info("remapped_seed_nodes_for_shard",
                       new_prefix=new_prefix, patched_files=patched)

    def _fix_stale_node_list(self, node_configs) -> None:
        """Overwrite stale IPs in ``nodes.list`` BEFORE starting containers.

        Runs ``dap-gdb-tool node-rehost`` directly on the GDB files on disk.
        Node addresses are read from ``node-addr.dcert`` via ``dap-cert``.
        Everything happens in a single ``docker run`` — no running nodes,
        no CLI sockets, no network cycling required.
        """
        import subprocess
        from ..certs.generator import CertGenerator, CERT_BUILDER_IMAGE

        tools_image = CERT_BUILDER_IMAGE
        sdk_branch = self._sdk_branch_for_tools()
        cg = CertGenerator(self.base_path, dap_sdk_branch=sdk_branch)
        if not cg.build_docker_image():
            logger.error("gdb_tool_image_not_available")
            return

        cache_dir = self.paths_config.get('cache_dir', 'cache')
        cache_path = (self.base_path / cache_dir).resolve()
        net_name = self.topology.network.name
        settings = self.topology.network_settings
        base_ip_parts = settings.base_ip.split('.')

        volumes: list[str] = []
        ip_map: dict[int, str] = {}

        for nc in node_configs:
            data_path = cache_path / "data" / f"node{nc.node_id}"
            volumes.extend(["-v", f"{data_path}:/nodes/node{nc.node_id}"])
            ip_map[nc.node_id] = (
                f"{'.'.join(base_ip_parts[:3])}"
                f".{int(base_ip_parts[3]) + nc.node_id - 1}"
            )

        script_lines = ["set -e", ""]

        for nc in node_configs:
            script_lines.append(
                f'ADDR_{nc.node_id}=$('
                f'/usr/local/bin/dap-cert node-addr '
                f'/nodes/node{nc.node_id}/lib/ca/node-addr.dcert 2>/dev/null'
                f') || ADDR_{nc.node_id}=""'
            )

        script_lines.append("")

        for target in node_configs:
            gdb = f"/nodes/node{target.node_id}/lib/global_db"
            for src in node_configs:
                ip = ip_map[src.node_id]
                script_lines.append(
                    f'[ -n "$ADDR_{src.node_id}" ] && '
                    f'/usr/local/bin/dap-gdb-tool '
                    f'--db-path {gdb} '
                    f'node-rehost {net_name} "$ADDR_{src.node_id}" {ip} 8079 '
                    f'|| true'
                )

        script = "\n".join(script_lines)

        docker_cmd = [
            "docker", "run", "--rm",
            "--entrypoint", "sh",
        ] + volumes + [
            tools_image,
            "-c", script,
        ]

        try:
            result = subprocess.run(
                docker_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                ok_count = result.stdout.count("OK ")
                logger.info("stale_node_list_fixed",
                            nodes=len(node_configs),
                            entries_updated=ok_count)
            else:
                logger.error("gdb_tool_failed",
                             rc=result.returncode,
                             stderr=result.stderr[-500:] if result.stderr else "")
        except subprocess.TimeoutExpired:
            logger.error("gdb_tool_timeout")
        except Exception as exc:
            logger.error("gdb_tool_exception", exc=str(exc))

    async def _restore_snapshots(self) -> None:
        """Restore clean_state or phase1 snapshot if available."""
        self._snapshot_clean_state_restored = False
        self._snapshot_phase1_restored = False

        clean_state_name = self.suite_isolation_config.get('snapshot_name', 'clean_state')
        phase1_snapshot_name = self.suite_isolation_config.get('phase1_snapshot_name', self._default_phase1_name())

        if self.snapshot_manager.mode == SnapshotMode.DISABLED:
            self._clean_node_data()
            return

        _snap = self.snapshot_manager.snapshot

        if _snap.exists(clean_state_name):
            if await self.snapshot_manager.restore_snapshot(clean_state_name):
                self._snapshot_clean_state_restored = True
                return
        if _snap.exists(phase1_snapshot_name):
            if await self.snapshot_manager.restore_snapshot(phase1_snapshot_name):
                self._snapshot_phase1_restored = True
                return
            raise RuntimeError(
                f"Snapshot restore failed for '{phase1_snapshot_name}'. "
                "Run './clean.sh' to remove root-owned files and try again."
            )

        self._clean_node_data()

    async def start(
        self,
        rebuild: bool = False,
        wait_ready: bool = True,
    ) -> None:
        """
        Start the test network.
        
        Args:
            rebuild: Rebuild Docker images before starting
            wait_ready: Wait for all nodes to be ready
        """
        logger.info("starting_network",
                   topology=self.topology_name,
                   rebuild=rebuild)

        if not getattr(self, '_prepared', False):
            # Full legacy path — stop, restore, config, compose
            logger.info("stopping_previous_environment")
            try:
                self.compose.down(volumes=False, remove_images=False)
                logger.info("previous_environment_stopped")
            except Exception as e:
                logger.debug("no_previous_environment", error=str(e))
            self.compose.cleanup_stale_resources()
        
        if not getattr(self, '_prepared', False):
            # Full legacy path — snapshot restore + config/compose generation
            await self._restore_snapshots()

            if not self.nodes:
                node_configs = self.generate_node_configs()
            else:
                node_configs = list(self.nodes.values())

            snapshot_restored = self._snapshot_clean_state_restored or self._snapshot_phase1_restored
            if not snapshot_restored:
                self.config_generator.generate_all(self.topology, node_configs, force=rebuild)
            else:
                self._remap_seed_nodes_for_shard(node_configs)

            cache_dir_relative = self.paths_config.get('cache_dir', 'cache')
            node_source_config = self.config_loader.get_node_source_config()
            settings = self.topology.network_settings
            self.compose.generate_compose_for_nodes(
                node_configs,
                build_type=node_source_config.get('build_type', 'debug') if node_source_config else 'debug',
                cache_dir_relative=cache_dir_relative,
                node_source_config=node_source_config,
                network_settings={
                    'subnet': settings.subnet,
                    'base_ip': settings.base_ip,
                },
                extra_services=self.docker_compose or None,
            )
            if rebuild:
                self.compose.build(no_cache=rebuild)
        else:
            # prepare() already ran — just re-read state
            node_configs = list(self.nodes.values())

        clean_state_name = self.suite_isolation_config.get('snapshot_name', 'clean_state')
        phase1_snapshot_name = self.suite_isolation_config.get('phase1_snapshot_name', self._default_phase1_name())
        clean_state_restored = getattr(self, '_snapshot_clean_state_restored', False)
        phase1_snapshot_exists = getattr(self, '_snapshot_phase1_restored', False)
        
        # Separate nodes by role for phased startup
        root_nodes = [n for n in node_configs if n.role == 'root']
        master_nodes = [n for n in node_configs if n.role == 'master']
        full_nodes = [n for n in node_configs if n.role == 'full']
        
        root_node_ids = [n.node_id for n in root_nodes]
        master_node_ids = [n.node_id for n in master_nodes]
        full_node_ids = [n.node_id for n in full_nodes]
        
        logger.info("node_distribution", 
                   root=len(root_nodes), 
                   master=len(master_nodes), 
                   full=len(full_nodes))
        
        # Initialize emission_hash variable (will be set in PHASE 1 or after snapshot restore)
        emission_hash: Optional[str] = None
        
        # =================================================================
        # PHASE 1: START ROOT NODES WITH SEED_MODE FOR DAG GENESIS
        # (SKIP if any snapshot was restored - clean_state or phase1)
        # =================================================================
        if clean_state_restored:
            logger.info("=== ALL PHASES SKIPPED: Full genesis snapshot restored ===",
                       snapshot=clean_state_name,
                       note="Starting containers from clean_state snapshot")
            
            # Fix stale node list in GDB BEFORE starting containers
            self._fix_stale_node_list(node_configs)

            # Start ALL containers from restored clean_state
            all_services = [f"node-{i}" for i in range(1, len(root_nodes) + len(master_nodes) + len(full_nodes) + 1)]
            logger.info("starting_all_containers_from_clean_state", services=all_services)
            self.compose.up(services=all_services, detach=True, wait=False, no_build=False)
            
            # Wait for all nodes to come online
            await self.state_manager.wait_for_nodes_online(node_configs, timeout=self.timeouts.get('startup', 600))
            
            # Verify fee_addr is configured (should be set during genesis)
            first_root = root_nodes[0]
            fee_addr = self.genesis.config_mgr.read_fee_addr_from_config(first_root.node_id)
            logger.info("fee_addr_verified_in_config",
                      fee_addr=fee_addr[:16],
                      node_id=first_root.node_id,
                      note="fee_addr is configured (set during genesis)")
            
            # Network is ready - no phases needed
            logger.info("network_started",
                       nodes=len(node_configs),
                       topology=self.topology.network.name,
                       source="clean_state_snapshot")
            return  # Skip all phases - already completed in snapshot
            
        elif not phase1_snapshot_exists:
            logger.info("=== PHASE 1: ROOT Nodes Startup (DAG-PoA Genesis) ===")
            
            try:
                # Create consensus monitor for root nodes
                from ..monitoring.network_consensus import NetworkConsensusMonitor
                root_nodes_dict = {f"node{n.node_id}": n for n in root_nodes}
                consensus_monitor = NetworkConsensusMonitor(
                    nodes=root_nodes_dict,
                    node_cli_path=self.node_cli_path,
                    network_name=self.topology.network.name
                )
                
                # Use YAML scenario for phase1 genesis
                # CLI parser will be initialized automatically in executor after setup phase
                from ..scenarios.executor import ScenarioExecutor
                from ..scenarios.parser import ScenarioParser
                
                scenario_parser = ScenarioParser(self.base_path / "scenarios")
                phase1_scenario = scenario_parser.load_scenario(f"genesis/{self._genesis_version_dir}/phase1_zerochain.yml")
                
                # Get scenario debug setting from config
                scenarios_config = self.config_loader.get_scenarios_config()
                
                executor = ScenarioExecutor(
                    node_cli_path=self.node_cli_path,
                    log_file=None,
                    debug=scenarios_config.get('debug', False),
                    base_path=self.base_path
                )
                
                # Execute phase1 scenario
                # Pass ALL node_configs for automatic IP collection after setup
                # Scenario needs IPs for all nodes (ROOT, MASTER, FULL) to add them to nodelist
                
                logger.info("executing_phase1_scenario")
                
                ctx = await executor.execute_scenario(
                    phase1_scenario,
                    compose_manager=self.compose,
                    snapshot_manager=self.snapshot_manager,
                    genesis_config_manager=self.genesis.config_mgr,
                    initial_variables={},
                    global_context=self.scenario_context,
                    node_configs=node_configs  # All nodes, not just root
                )
                
                # Extract results from context
                emission_hash = ctx.get_variable('emission_hash') if 'emission_hash' in ctx.variables else None
                fee_addr = ctx.get_variable('fee_addr') if 'fee_addr' in ctx.variables else None
                
                # Extract root node addresses dynamically (count from topology)
                root_count = ctx.variables.get('root_count', 0)
                root_addrs = {}
                for i in range(root_count):
                    var_name = f'root_addr_{i}'
                    if var_name in ctx.variables:
                        root_addrs[i] = ctx.get_variable(var_name)
                
                genesis_event_hash = ctx.get_variable('genesis_event_hash') if 'genesis_event_hash' in ctx.variables else None
                
                # Store Phase 1 context for Phase 2
                self._phase1_ctx = ctx
                
                logger.info("zerochain_genesis_complete",
                           emission_hash=emission_hash[:16] if emission_hash else None,
                           fee_addr=fee_addr,
                           root_addrs_count=len(root_addrs),
                           note="Phase1 genesis completed - emission ready for Phase2 transfers")
                
                # =================================================================
                # PHASE 1.5: CREATE PHASE 1 SNAPSHOT (zerochain + genesis LN + emission + transfer)
                # =================================================================
                # Create snapshot after PHASE 1 completion (zerochain genesis ready)
                # This allows fast restoration to phase1 state for different genesis scenarios
                genesis_stage = self.suite_isolation_config.get('genesis_stage', 'full')
                if genesis_stage in ['phase1', 'full']:
                    if self.suite_isolation_config.get('auto_create_on_startup', True):
                        if self.snapshot_manager.mode != SnapshotMode.DISABLED:
                            logger.info("creating_phase1_snapshot_after_zerochain_genesis")
                            containers_shutdown = False
                            try:
                                # CRITICAL: Gracefully shutdown ROOT containers before snapshot
                                # This ensures all data (GDB, chain files, configs) are flushed to disk
                                # Graceful shutdown ensures:
                                # - GDB flush completes (node list, validator orders)
                                # - Chain files are saved (zerochain events)
                                # - Configs are written to disk (static_genesis_event)
                                logger.info("gracefully_shutting_down_root_containers_for_phase1_snapshot")
                                root_services = [f"node-{nid}" for nid in root_node_ids]
                                await self.lifecycle.graceful_shutdown_with_gdb_flush(
                                    service_names=root_services,
                                    flush_timeout=60
                                )
                                containers_shutdown = True
                                
                                # CRITICAL: Verify that chain files and configs exist before creating snapshot
                                logger.info("verifying_chain_files_and_configs_before_snapshot")
                                from pathlib import Path
                                cache_dir = (self.genesis.base_path / self.paths_config.get('cache_dir', 'cache')).resolve()
                                
                                chain_files_found = 0
                                configs_found = 0
                                for node_id in root_node_ids:
                                    # Check chain files
                                    # On host: cache/data/node{id}/lib/network/stagenet/zerochain/
                                    # Inside container: /opt/cellframe-node/var/lib/network/stagenet/zerochain/
                                    # (volume mount: cache/data/node{id} -> /opt/cellframe-node/var)
                                    chain_files_path = cache_dir / "data" / f"node{node_id}" / "lib" / "network" / self.topology.network.name / "zerochain"
                                    if chain_files_path.exists():
                                        chain_files = list(chain_files_path.glob("*.dchaincell"))
                                        if chain_files:
                                            chain_files_found += 1
                                            logger.info("chain_files_found_before_snapshot",
                                                       node_id=node_id,
                                                       count=len(chain_files),
                                                       files=[f.name for f in chain_files[:3]])
                                        else:
                                            logger.warning("chain_files_directory_empty",
                                                         node_id=node_id,
                                                         path=str(chain_files_path))
                                    else:
                                        logger.error("chain_files_directory_missing",
                                                   node_id=node_id,
                                                   path=str(chain_files_path))
                                    
                                    # Check zerochain config
                                    zerochain_config_path = cache_dir / "configs" / f"node{node_id}" / "network" / self.topology.network.name / "zerochain.cfg"
                                    if zerochain_config_path.exists():
                                        configs_found += 1
                                        # Verify static_genesis_event is set using centralized config manager
                                        from ..config.manager import get_config_loader
                                        config_loader = get_config_loader()
                                        config = config_loader.load_config_file(zerochain_config_path)
                                        static_genesis = config.get('dag', 'static_genesis_event', fallback='').strip() if 'dag' in config else ''
                                        if static_genesis:
                                            logger.info("zerochain_config_verified_before_snapshot",
                                                       node_id=node_id,
                                                       static_genesis_hash=static_genesis[:16],
                                                       path=str(zerochain_config_path))
                                        else:
                                            logger.error("static_genesis_event_not_set_in_config",
                                                       node_id=node_id,
                                                       path=str(zerochain_config_path))
                                    else:
                                        logger.error("zerochain_config_missing_before_snapshot",
                                                   node_id=node_id,
                                                   path=str(zerochain_config_path))
                                
                                if chain_files_found == 0:
                                    raise RuntimeError(
                                        f"CRITICAL: No chain files found for any ROOT node before snapshot creation! "
                                        f"This means zerochain events were not saved to disk. "
                                        f"Chain files checked in: {[str(cache_dir / 'data' / f'node{nid}' / 'lib' / 'network' / self.topology.network.name / 'zerochain') for nid in root_node_ids]}. "
                                        f"This is a critical error - cannot proceed with snapshot creation. "
                                        f"Check if zerochain events were actually created and if storage_dir is correctly configured."
                                    )
                                if configs_found == 0:
                                    raise RuntimeError(f"CRITICAL: No zerochain configs found for any ROOT node before snapshot creation! "
                                                     f"This means configs were not written to disk.")
                                
                                logger.info("chain_files_and_configs_verified",
                                          chain_files_nodes=chain_files_found,
                                          configs_nodes=configs_found,
                                          total_nodes=len(root_node_ids))
                                
                                # CRITICAL: Do NOT clean data before snapshot!
                                # Squashfs snapshot automatically captures all mounted directories including GDB
                                # Cleaning data would remove critical GDB data (node list, validator orders)
                                # Snapshot will preserve current state including all GDB data
                                logger.info("preserving_data_for_phase1_snapshot",
                                           note="Squashfs snapshot captures all mounted directories automatically")
                                
                                # Create snapshot of phase1 state (with GDB data preserved)
                                phase1_snapshot_name = self.suite_isolation_config.get('phase1_snapshot_name', self._default_phase1_name())
                                phase1_meta = {}
                                if emission_hash:
                                    phase1_meta["emission_hash"] = emission_hash
                                if genesis_event_hash:
                                    phase1_meta["genesis_event_hash"] = genesis_event_hash
                                await self.create_clean_snapshot(name=phase1_snapshot_name, extra_metadata=phase1_meta or None)
                                logger.info("phase1_snapshot_created", 
                                           name=phase1_snapshot_name,
                                           note="zerochain genesis and LN ready")
                                
                                # CRITICAL: After graceful shutdown, containers are stopped
                                # Need to restart them to continue with PHASE 2
                                # They will use configs from snapshot (seed_mode=false, static_genesis_event set)
                                logger.info("restarting_root_containers_after_snapshot_creation")
                                root_services = [f"node-{nid}" for nid in root_node_ids]
                                self.compose.up(services=root_services, detach=True, wait=False)
                                
                                # If genesis_stage is 'phase1', stop here (containers remain stopped)
                                if genesis_stage == 'phase1':
                                    logger.info("genesis_stage_phase1_complete",
                                               snapshot=phase1_snapshot_name,
                                               note="Network ready with zerochain genesis only. Containers stopped.")
                                    return
                                
                                # CRITICAL: Containers are already running after restart (with configs from snapshot)
                                # No need for another hard restart - seed_mode is already disabled
                                # Wait for ROOT nodes to be ONLINE before proceeding to PHASE 2
                                logger.info("waiting_for_root_nodes_online_for_phase2")
                                await self.state_manager.wait_for_nodes_online(root_nodes, timeout=60.0)
                                logger.info("root_nodes_online_for_phase2")
                                
                            except Exception as e:
                                # CRITICAL: Check for fatal errors that require immediate exit
                                error_msg = str(e)
                                
                                # Fatal errors - do NOT continue, do NOT restart containers
                                fatal_errors = [
                                    "No chain files found",
                                    "zerochain events were not saved",
                                    "Network not found",
                                    "CRITICAL: Network not found",
                                    "configs may be corrupted"
                                ]
                                
                                is_fatal = any(pattern.lower() in error_msg.lower() for pattern in fatal_errors)
                                if is_fatal:
                                    logger.error("phase1_snapshot_creation_failed_critical",
                                               error=error_msg,
                                               note="FATAL ERROR: Cannot proceed - immediate exit required")
                                    raise  # Re-raise the error - this is fatal
                                
                                # If containers were shutdown, they need to be restarted even on error
                                # BUT only if error is NOT fatal
                                if containers_shutdown:
                                    try:
                                        logger.info("restarting_containers_after_snapshot_error")
                                        root_services = [f"node-{nid}" for nid in root_node_ids]
                                        self.compose.up(services=root_services, detach=True, wait=False)
                                        await self.state_manager.wait_for_nodes_online(root_nodes, timeout=60.0)
                                    except Exception as restart_err:
                                        logger.error("failed_to_restart_containers_after_error",
                                                   error=str(restart_err))
                                logger.warning("phase1_snapshot_creation_failed",
                                              error=error_msg,
                                              note="Continuing with PHASE 2, snapshot will be created at end")
            
            except Exception as e:
                logger.error("root_nodes_genesis_failed", error=str(e), traceback=traceback.format_exc())
                if not self.keep_running:
                    self.compose.down(volumes=False, remove_images=False)
                raise RuntimeError(f"ROOT nodes genesis failed: {e}") from e
        else:
            logger.info("=== PHASE 1 SKIPPED: Using restored phase1 snapshot ===",
                       snapshot=phase1_snapshot_name,
                       note="ROOT nodes already initialized with zerochain genesis")
            
            # CRITICAL: Read static_genesis_event and fee_addr from restored configs BEFORE starting containers
            # These values MUST be in configs after snapshot restore for nodes to load network correctly
            # If they are missing, nodes will fail to load network (error: "Network stagenet not found")
            logger.info("reading_genesis_event_and_fee_addr_from_restored_configs_before_start")
            
            # CRITICAL: First, verify config files exist after snapshot restore
            # This helps diagnose if configs were not restored correctly
            from ..config.manager import get_config_loader
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            cache_dir_relative = paths_config.get('cache_dir', 'cache')
            cache_dir = (self.base_path / cache_dir_relative).resolve()
            
            first_root_node = root_nodes[0]
            zerochain_config_path = cache_dir / "configs" / f"node{first_root_node.node_id}" / "network" / self.topology.network.name / "zerochain.cfg"
            main_config_path = cache_dir / "configs" / f"node{first_root_node.node_id}" / "network" / self.topology.network.name / "main.cfg"
            
            # Diagnostic: Check if config files exist
            if not zerochain_config_path.exists():
                logger.error("zerochain_config_not_found_after_snapshot_restore",
                           path=str(zerochain_config_path),
                           note="CRITICAL: zerochain.cfg not found after snapshot restore! "
                                "Configs may not have been restored correctly from snapshot.")
                raise RuntimeError(
                    f"CRITICAL: zerochain.cfg not found after snapshot restore! "
                    f"Path: {zerochain_config_path}. "
                    f"Configs may not have been restored correctly from snapshot. "
                    f"Check snapshot restoration process."
                )
            
            if not main_config_path.exists():
                logger.error("main_config_not_found_after_snapshot_restore",
                           path=str(main_config_path),
                           note="CRITICAL: main.cfg not found after snapshot restore! "
                                "Configs may not have been restored correctly from snapshot.")
                raise RuntimeError(
                    f"CRITICAL: main.cfg not found after snapshot restore! "
                    f"Path: {main_config_path}. "
                    f"Configs may not have been restored correctly from snapshot. "
                    f"Check snapshot restoration process."
                )
            
            logger.info("config_files_exist_after_snapshot_restore",
                       zerochain_config=str(zerochain_config_path),
                       main_config=str(main_config_path),
                       note="Config files found after snapshot restore - proceeding to read values")
            
            # Read static_genesis_event from zerochain config
            static_genesis_hash = None
            fee_addr = None
            
            for root_node in root_nodes[:1]:  # Check first ROOT node (configs are same for all nodes)
                # Read static_genesis_event from zerochain.cfg
                static_genesis_hash = self.genesis.config_mgr.read_static_genesis_event_from_config(
                    chain_name="zerochain",
                    node_id=root_node.node_id
                )
                
                # Read fee_addr from main.cfg
                fee_addr = self.genesis.config_mgr.read_fee_addr_from_config(
                    node_id=root_node.node_id
                )
                
                break  # Only need to check first node
            
            # CRITICAL: Verify values were read from configs BEFORE starting containers
            # If these values are missing, nodes will fail to load network
            if not static_genesis_hash:
                logger.error("static_genesis_event_not_read_from_config_after_snapshot_restore",
                           config_path=str(zerochain_config_path),
                           note="CRITICAL: static_genesis_event could not be read from restored configs! "
                                "This means configs were not properly restored or are missing genesis event hash. "
                                "Nodes will fail to load network without this value. "
                                "Check snapshot restoration process.")
                # Diagnostic: Try to read config file directly to see what's in it using centralized config manager
                try:
                    config_loader = get_config_loader()
                    config = config_loader.load_config_file(zerochain_config_path)
                    logger.error("zerochain_config_diagnostic",
                               sections=list(config.sections()),
                               dag_section_exists='dag' in config,
                               static_genesis_event_in_config=config.get('dag', 'static_genesis_event', fallback='EMPTY') if 'dag' in config else 'NO_DAG_SECTION',
                               note="Config file exists but static_genesis_event is missing or empty")
                except Exception as diag_err:
                    logger.error("zerochain_config_diagnostic_failed",
                               error=str(diag_err),
                               note="Could not read config file for diagnostic")
                
                raise RuntimeError(
                    f"CRITICAL: static_genesis_event not found in restored configs! "
                    f"Config path: {zerochain_config_path}. "
                    f"Snapshot may be corrupted or configs were not restored correctly. "
                    f"Cannot start nodes without static_genesis_event - they will fail to load network."
                )
            
            if not fee_addr:
                # fee_addr is not in phase1 snapshot - it's created in Phase 2
                # This is expected when restoring phase1 snapshot
                logger.info("fee_addr_not_in_phase1_snapshot",
                           config_path=str(main_config_path),
                           note="fee_addr not found in restored configs - this is expected for phase1 snapshot. "
                                "Phase 2 will create fee_addr during ESBocs genesis.")
            
            logger.info("genesis_event_read_from_configs",
                       static_genesis_hash=static_genesis_hash[:16],
                       fee_addr=fee_addr[:16] if fee_addr else "NOT_SET (will be created in Phase 2)",
                       zerochain_config=str(zerochain_config_path),
                       main_config=str(main_config_path),
                       note="static_genesis_event read from restored configs. "
                            "fee_addr may be created in Phase 2 if not present.")
            
            # Diagnostic - read config contents if debugging needed
            if fee_addr:
                try:
                    config_loader = get_config_loader()
                    zerochain_config = config_loader.load_config_file(zerochain_config_path)
                    main_config = config_loader.load_config_file(main_config_path)
                    
                    logger.debug("config_contents_diagnostic_after_snapshot_restore",
                                   zerochain_sections=list(zerochain_config.sections()),
                                   main_sections=list(main_config.sections()),
                                   zerochain_dag_section_exists='dag' in zerochain_config,
                                   main_esbocs_section_exists='esbocs' in main_config,
                                   note="Config contents after snapshot restore")
                except Exception as diag_err:
                    logger.warning("config_contents_diagnostic_failed",
                                 error=str(diag_err))
            
            # CRITICAL: Start ROOT containers after snapshot restore
            # Snapshot contains data but containers are stopped
            # ROOT nodes must be running for MASTER nodes to sync node list via GDB
            # Configs are now validated - nodes should be able to load network
            logger.info("starting_root_containers_after_snapshot_restore",
                       static_genesis_hash=static_genesis_hash[:16],
                       fee_addr=fee_addr[:16] if fee_addr else "NOT_SET",
                       note="Starting containers with restored configs")
            root_services = [f"node-{nid}" for nid in root_node_ids]
            self.compose.up(services=root_services, detach=True, wait=False)
            logger.info("root_containers_started_from_snapshot", services=root_services)
            
            # Wait for ROOT nodes to be ONLINE before proceeding to PHASE 2
            # This ensures GDB is accessible for MASTER nodes to sync node list
            # Configs are validated, so nodes should load network successfully
            logger.info("waiting_for_root_nodes_online_after_snapshot_restore",
                       static_genesis_hash=static_genesis_hash[:16],
                       note="Waiting for nodes to load network with validated configs")
            await self.state_manager.wait_for_nodes_online(root_nodes, timeout=60.0)
            logger.info("root_nodes_online_after_snapshot_restore")
            
            # CRITICAL: Set fee_addr on network level if it exists in config
            # This is needed for arbitrage transactions after snapshot restore
            # The fee_addr is in config but must also be set at runtime via CLI
            if fee_addr:
                logger.info("setting_fee_addr_on_network_level_after_snapshot_restore",
                          fee_addr=fee_addr[:16],
                          note="Executing: net -net stagenet fee_addr <addr>")
                try:
                    first_root = root_nodes[0]
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        first_root.node_id,
                        f"net -net {self.topology.network.name} fee_addr {fee_addr}",
                        check_output=False
                    )
                    if exit_code == 0:
                        logger.info("fee_addr_set_on_network_level",
                                  fee_addr=fee_addr[:16],
                                  note="fee_addr successfully set for arbitrage transactions")
                    else:
                        logger.error("fee_addr_set_failed",
                                   exit_code=exit_code,
                                   stderr=stderr,
                                   note="Failed to set fee_addr on network level")
                except Exception as e:
                    logger.error("fee_addr_set_error",
                               error=str(e),
                               note="Exception while setting fee_addr on network level")
            else:
                logger.warning("fee_addr_not_set_on_network_level",
                             note="fee_addr not found in config ")
            
            # Verify node list is available in GDB after restore
            logger.info("verifying_node_list_in_gdb_after_snapshot_restore")
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            root_nodes_dict = {f"node{n.node_id}": n for n in root_nodes}
            consensus_monitor = NetworkConsensusMonitor(
                nodes=root_nodes_dict,
                node_cli_path=self.node_cli_path,
                network_name=self.topology.network.name
            )
            
            # Wait for ROOT nodes to establish links (they should have node list from snapshot)
            logger.info("waiting_for_root_nodes_links_after_snapshot_restore")
            await consensus_monitor.wait_for_links_connecting_state(timeout=60.0)
            logger.info("root_nodes_links_established_after_snapshot_restore")
            
            # CRITICAL: Get emission_hash (DATUM hash) from zerochain after snapshot restore
            # Prefer snapshot metadata (saved when phase1 snapshot was created); fallback to CLI retrieval
            logger.info("getting_emission_hash_after_snapshot_restore")
            import re
            emission_hash = None
            phase1_snapshot_name = self.suite_isolation_config.get('phase1_snapshot_name', self._default_phase1_name())
            snapshot_meta = self.snapshot_manager.get_snapshot_metadata(phase1_snapshot_name)
            if snapshot_meta and snapshot_meta.get('emission_hash'):
                emission_hash = snapshot_meta['emission_hash']
                logger.info("emission_hash_loaded_from_snapshot_metadata",
                           emission_hash=emission_hash[:16],
                           note="Skipping CLI retrieval")
            if not emission_hash:
                # Method 1: Get emission_hash from dag event dump (CORRECT approach)
                # This mirrors what phase1_zerochain.yml does
                for root_node in root_nodes[:1]:  # Check first ROOT node
                    # Step 1: Get last event hash from zerochain
                    exit_code, stdout, _ = self.genesis._exec_cli(
                        root_node.node_id,
                        f"dag event last -net {self.topology.network.name} -chain zerochain",
                        check_output=False
                    )
                    logger.info("dag_event_last_check",
                               node_id=root_node.node_id,
                               exit_code=exit_code,
                               stdout_preview=stdout[:500] if stdout else "EMPTY")
                
                    if exit_code != 0 or not stdout:
                        logger.warning("dag_event_last_failed", exit_code=exit_code)
                        continue
                
                    # Extract event hash from "dag event last" output
                    # Format: "last_event_hash: 0x..." or just "0x..."
                    event_hash_match = re.search(r'(?:last_event_hash:\s*)?(0x[A-Fa-f0-9]{64})', stdout)
                    if not event_hash_match:
                        logger.warning("event_hash_not_found_in_dag_event_last", output=stdout[:200])
                        continue
                    
                    last_event_hash = event_hash_match.group(1)
                    logger.info("last_event_hash_found", hash=last_event_hash[:20])
                
                    # Step 2: Dump the event to get emission_hash
                    exit_code, dump_stdout, _ = self.genesis._exec_cli(
                        root_node.node_id,
                        f"dag event dump -net {self.topology.network.name} -chain zerochain -event {last_event_hash} -from events",
                        check_output=False
                    )
                    logger.info("dag_event_dump_check",
                               node_id=root_node.node_id,
                               exit_code=exit_code,
                               event_hash=last_event_hash[:20],
                               stdout_preview=dump_stdout[:1000] if dump_stdout else "EMPTY")
                
                    if exit_code != 0 or not dump_stdout:
                        logger.warning("dag_event_dump_failed", event_hash=last_event_hash[:20])
                        continue
                
                    # Step 3: Extract emission_hash from dump output
                    # Format: "emission_hash: 0x..." (inside nested datum section)
                    emission_match = re.search(r'emission_hash:\s*(0x[A-Fa-f0-9]+)', dump_stdout, re.IGNORECASE)
                    if emission_match:
                        emission_hash = emission_match.group(1)
                        logger.info("emission_hash_extracted_from_event_dump",
                                   emission_hash=emission_hash[:20],
                                   event_hash=last_event_hash[:20])
                        break
                    else:
                        logger.info("emission_hash_not_in_last_event_trying_previous",
                                   note="Last event might be token_decl, not emission")
                    
                        # Get event list to find emission event
                        exit_code, list_stdout, _ = self.genesis._exec_cli(
                            root_node.node_id,
                            f"dag event list -net {self.topology.network.name} -chain zerochain -from events -limit 10",
                            check_output=False
                        )
                        if exit_code == 0 and list_stdout:
                            # Find all event hashes
                            all_event_hashes = re.findall(r'event_hash:\s*(0x[A-Fa-f0-9]{64})', list_stdout)
                            logger.info("dag_events_list_for_emission",
                                       event_count=len(all_event_hashes),
                                       hashes=all_event_hashes[:5])
                        
                            # Try each event to find one with emission_hash
                            for evt_hash in all_event_hashes:
                                exit_code2, dump2, _ = self.genesis._exec_cli(
                                    root_node.node_id,
                                    f"dag event dump -net {self.topology.network.name} -chain zerochain -event {evt_hash} -from events",
                                    check_output=False
                                )
                                if exit_code2 == 0 and dump2:
                                    em_match = re.search(r'emission_hash:\s*(0x[A-Fa-f0-9]+)', dump2, re.IGNORECASE)
                                    if em_match:
                                        emission_hash = em_match.group(1)
                                        logger.info("emission_hash_found_in_event",
                                                   emission_hash=emission_hash[:20],
                                                   event_hash=evt_hash[:20])
                                        break
                            if emission_hash:
                                break
            
                # Method 2: Fallback - try ledger list emis (list emissions with hashes)
                if not emission_hash:
                    logger.info("emission_hash_not_found_in_dag_trying_ledger_emis")
                    for root_node in root_nodes[:1]:
                        # List emissions specifically
                        exit_code, stdout, _ = self.genesis._exec_cli(
                            root_node.node_id,
                            f"ledger list emis -net {self.topology.network.name}",
                            check_output=False
                        )
                        logger.info("ledger_list_emis_check",
                                   node_id=root_node.node_id,
                                   exit_code=exit_code,
                                   stdout_preview=stdout[:1000] if stdout else "EMPTY")
                    
                        if exit_code == 0 and stdout:
                            # Look for emission hash in output
                            # Format: "hash: 0x..." or "emission_hash: 0x..."
                            hash_matches = re.findall(r'(?:emission_)?hash:\s*(0x[A-Fa-f0-9]{64})', stdout, re.IGNORECASE)
                            if hash_matches:
                                emission_hash = hash_matches[-1]  # Use last emission hash
                                logger.info("emission_hash_found_in_ledger_emis",
                                           hash=emission_hash[:20],
                                           total_emissions=len(hash_matches))
                                break
                            # Try any 64-char hex hashes
                            all_hashes = re.findall(r'(0x[A-Fa-f0-9]{64})', stdout)
                            if all_hashes:
                                emission_hash = all_hashes[-1]
                                logger.info("emission_hash_found_from_ledger_hashes",
                                           hash=emission_hash[:20],
                                           total_hashes=len(all_hashes))
                                break
            
                # Method 3: Fallback - try token show/info to get emission datum hash
                if not emission_hash:
                    logger.info("emission_hash_not_found_trying_token_show")
                    for root_node in root_nodes[:1]:
                        # Try token show command
                        exit_code, stdout, _ = self.genesis._exec_cli(
                            root_node.node_id,
                            f"token show -net {self.topology.network.name} -token TCELL",
                            check_output=False
                        )
                        logger.info("token_show_check",
                                   node_id=root_node.node_id,
                                   exit_code=exit_code,
                                   stdout_length=len(stdout) if stdout else 0,
                                   stdout_preview=stdout[:500] if stdout else "EMPTY")
                    
                        if exit_code == 0 and stdout:
                            # Look for emission datum hash in token info
                            hash_matches = re.findall(r'(?:emission|datum)\s+(?:hash|datum):\s*(0x[A-Fa-f0-9]{64})', stdout, re.IGNORECASE)
                            if hash_matches:
                                emission_hash = hash_matches[0]
                                logger.info("emission_hash_found_in_token_show",
                                           hash=emission_hash[:16])
                                break
                            # Try finding any hash
                            all_hashes = re.findall(r'(0x[A-Fa-f0-9]{64})', stdout, re.IGNORECASE)
                            if all_hashes:
                                emission_hash = all_hashes[-1]
                                logger.info("emission_hash_found_from_token_show_hashes",
                                           hash=emission_hash[:16],
                                           total_hashes=len(all_hashes),
                                           note="Using last hash from token show")
                                break
            
                # Method 4: Fallback - try token list to verify emission exists
                if not emission_hash:
                    logger.info("emission_hash_not_found_trying_token_list")
                    for root_node in root_nodes[:1]:
                        exit_code, stdout, _ = self.genesis._exec_cli(
                            root_node.node_id,
                            f"token list -net {self.topology.network.name}",
                            check_output=False
                        )
                        logger.info("token_list_check",
                                   node_id=root_node.node_id,
                                   exit_code=exit_code,
                                   stdout_length=len(stdout) if stdout else 0,
                                   stdout_preview=stdout[:500] if stdout else "EMPTY")
                    
                        if exit_code == 0 and stdout and "TCELL" in stdout.upper():
                            logger.info("tcell_token_found_but_emission_hash_missing",
                                       note="Emission may have been lost - snapshot may be incomplete")
            
                if not emission_hash:
                    # Log detailed diagnostic info before failing
                    logger.error("emission_hash_retrieval_failed",
                               note="Tried DAG events, ledger, token show, and token list - snapshot may be corrupted")
                    raise RuntimeError("Failed to retrieve emission_hash from zerochain after snapshot restore. "
                                     "Snapshot may be corrupted or emission not found in DAG events/ledger. "
                                     "Check logs for detailed command outputs.")
            
            logger.info("emission_hash_retrieved_after_snapshot_restore", hash=emission_hash[:16])
            
            # CRITICAL: After snapshot restore, emission_hash should already exist
            # (emission was created and transferred before snapshot creation)
            # No need to create emission again - it's already in the snapshot
            logger.info("emission_hash_available_from_snapshot",
                       emission_hash=emission_hash[:16],
                       note="Emission and transfer already exist in snapshot - no need to create them again")
        
        # =================================================================
        # PHASE 2: START MASTER NODES FOR ESBOCS GENESIS
        # =================================================================
        
        # CRITICAL: Check if mainchain genesis block already exists
        # If yes, Phase 2 was already completed - skip it entirely
        mainchain_genesis_exists = False
        for root_node in root_nodes[:1]:
            exit_code, stdout, _ = self.genesis._exec_cli(
                root_node.node_id,
                f"block list -net {self.topology.network.name} -chain main",
                check_output=False
            )
            if exit_code == 0 and stdout:
                # Check for "have blocks:" with count > 0
                import re
                blocks_match = re.search(r'have blocks:\s*(\d+)', stdout, re.IGNORECASE)
                if blocks_match and int(blocks_match.group(1)) > 0:
                    mainchain_genesis_exists = True
                    logger.info("mainchain_genesis_already_exists",
                               blocks=blocks_match.group(1),
                               note="Phase 2 already completed - skipping")
                    break
        
        # Check if we should skip Phase 2 (genesis already exists)
        skip_phase2 = mainchain_genesis_exists
        
        if skip_phase2:
            logger.info("=== PHASE 2 SKIPPED: Mainchain genesis block already exists ===")
            # Start remaining nodes if not running
            master_full_services = [f"node-{n.node_id}" for n in master_nodes + full_nodes]
            if not self.compose.are_services_running(master_full_services):
                logger.info("starting_remaining_nodes_after_phase2_skip", services=master_full_services)
                all_services = [f"node-{i}" for i in range(1, len(root_nodes) + len(master_nodes) + len(full_nodes) + 1)]
                self.compose.up(services=all_services, detach=True, wait=False, no_build=False)
                await self.state_manager.wait_for_nodes_online(node_configs, timeout=self.timeouts.get('startup', 600))
        else:
            logger.info("=== PHASE 2: Start MASTER (ESBocs Genesis with Single Validator) ===")
        
        try:
            if skip_phase2:
                # Skip Phase 2 execution - genesis already exists
                pass
            else:
                # Define all validator nodes (ROOT + MASTER)
                all_validator_nodes = root_nodes + master_nodes
            
                # Create consensus monitor for all validator nodes
                from ..monitoring.network_consensus import NetworkConsensusMonitor
                all_validator_nodes_dict = {f"node{n.node_id}": n for n in all_validator_nodes}
                consensus_monitor_all = NetworkConsensusMonitor(
                    nodes=all_validator_nodes_dict,
                    node_cli_path=self.node_cli_path,
                    network_name=self.topology.network.name
                )
                
                # CRITICAL: Verify emission_hash is set before proceeding to PHASE 2
                if emission_hash is None:
                    raise RuntimeError(
                        f"CRITICAL: emission_hash is None before PHASE 2! "
                        f"This should not happen - emission_hash must be set either: "
                        f"1. After phase1 YAML scenario execution, or "
                        f"2. After snapshot restore (via restore_emission_hash_from_snapshot). "
                        f"Cannot proceed to ESBocs genesis without emission_hash."
                    )
                
                # Use YAML scenario for phase2 genesis
                # CLI parser should already be initialized after phase1, but executor will reinitialize if needed
                from ..scenarios.executor import ScenarioExecutor
                from ..scenarios.parser import ScenarioParser
                
                scenario_parser = ScenarioParser(self.base_path / "scenarios")
                phase2_scenario = scenario_parser.load_scenario(f"genesis/{self._genesis_version_dir}/phase2_esbocs.yml")
                
                # Get scenario debug setting from config
                scenarios_config = self.config_loader.get_scenarios_config()
                
                executor = ScenarioExecutor(
                    node_cli_path=self.node_cli_path,
                    log_file=None,
                    debug=scenarios_config.get('debug', False),
                    base_path=self.base_path
                )
                
                # Execute phase2 scenario with all variables from phase1
                # CRITICAL: Pass node_ip map (via global_context) and all context variables
                phase2_initial_variables = {}
                
                # Get variables from stored Phase 1 context or restored snapshot
                if hasattr(self, '_phase1_ctx') and self._phase1_ctx:
                    phase1_ctx = self._phase1_ctx
                    # Copy all Phase 1 variables to Phase 2
                    base_vars = ['emission_hash', 'fee_addr', 'genesis_event_hash', 'token_hash',
                                 'root_count', 'master_count', 'full_count']
                    for var_name in base_vars:
                        if var_name in phase1_ctx.variables:
                            phase2_initial_variables[var_name] = phase1_ctx.get_variable(var_name)
                    
                    # Copy dynamic root/master/full addresses
                    root_count = phase1_ctx.variables.get('root_count', 0)
                    master_count = phase1_ctx.variables.get('master_count', 0)
                    for i in range(root_count):
                        var_name = f'root_addr_{i}'
                        if var_name in phase1_ctx.variables:
                            phase2_initial_variables[var_name] = phase1_ctx.get_variable(var_name)
                    for i in range(master_count):
                        var_name = f'master_addr_{i}'
                        if var_name in phase1_ctx.variables:
                            phase2_initial_variables[var_name] = phase1_ctx.get_variable(var_name)
                else:
                    # Fallback: use local variables if Phase 1 context not stored
                    if emission_hash:
                        phase2_initial_variables['emission_hash'] = emission_hash
                
                logger.info("phase2_initial_variables", 
                           variables=list(phase2_initial_variables.keys()),
                           emission_hash=phase2_initial_variables.get('emission_hash', '?')[:16] if phase2_initial_variables.get('emission_hash') else None)
                
                ctx = await executor.execute_scenario(
                    phase2_scenario,
                    compose_manager=self.compose,
                    snapshot_manager=self.snapshot_manager,
                    genesis_config_manager=self.genesis.config_mgr,
                    initial_variables=phase2_initial_variables,
                    global_context=self.scenario_context,
                    node_configs=node_configs
                )
                
                logger.info("esbocs_genesis_complete_with_pos_master_nodes",
                           note="Phase2 genesis completed via YAML scenario")
            
        except Exception as e:
            # Only handle errors if we actually ran Phase 2
            if not skip_phase2:
                # Dump logs before tearing down
                try:
                    logger.error("master_nodes_genesis_failed", error=str(e), traceback=traceback.format_exc())
                    # Dump logs for all running containers
                    import docker
                    docker_client = docker.from_env()
                    for container in docker_client.containers.list(all=True):
                        if f"{self.compose.project_name}-node" in container.name:
                            log_path = f"/tmp/{container.name}.log"
                            try:
                                with open(log_path, "wb") as f:
                                    f.write(container.logs())
                                logger.info(f"Dumped log for {container.name} to {log_path}")
                            except Exception as log_err:
                                logger.error(f"Failed to dump log for {container.name}: {log_err}")
                except Exception as dump_err:
                    logger.error(f"Failed to dump container logs: {dump_err}")

                if not self.keep_running:
                    self.compose.down(volumes=False, remove_images=False)
                raise RuntimeError(f"MASTER nodes genesis failed: {e}") from e
        
        # =================================================================
        # PHASE 3: START FULL NODES
        # =================================================================
        logger.info("=== PHASE 3: Start FULL Nodes ===")
        
        try:
            # ROOT + MASTER already restarted in PHASE 2 with:
            # - seed_mode=false
            # - static_genesis_block set
            # - GDB node list preserved
            
            # Start FULL nodes
            full_services = [f"node-{nid}" for nid in full_node_ids]
            logger.info("starting_full_nodes", services=full_services)
            self.compose.up(services=full_services, detach=True, wait=False)
            
            # Wait for ALL nodes to be ready (ROOT + MASTER + FULL)
            logger.info("waiting_for_all_nodes_ready")
            
            # Use existing self.nodes (should include all nodes)
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            final_consensus_monitor = NetworkConsensusMonitor(
                nodes=self.nodes,
                node_cli_path=self.node_cli_path,
                network_name=self.topology.network.name
            )
            
            consensus_timeout = float(self.timeouts.get('startup', 600))
            try:
                await final_consensus_monitor.wait_for_network_ready(timeout=consensus_timeout)
                logger.info("all_nodes_ready_for_snapshot")
            except TimeoutError as e:
                logger.error("full_network_not_ready", error=str(e))
                raise RuntimeError(f"Full network failed to reach consensus: {e}")
            
        except Exception as e:
            logger.error("full_nodes_startup_failed", error=str(e), traceback=traceback.format_exc())
            if not self.keep_running:
                self.compose.down(volumes=False, remove_images=False)
            raise RuntimeError(f"FULL nodes startup failed: {e}") from e
        
        # =================================================================
        # PHASE 4: NODE ALIASES REGISTRATION
        # =================================================================
        logger.info("=== PHASE 4: Node Aliases Registration ===")
        
        try:
            # Register node aliases in GDB
            # Node registration via CLI already done in PHASE 1 (pre-populated for all nodes)
            await self.genesis.registration_mgr.register_node_aliases(node_configs)
            logger.info("node_aliases_registered")
        except Exception as e:
            logger.error("node_alias_registration_failed", error=str(e))
            # Non-critical - continue
        
        # PHASE 5: Wait for network consensus
        logger.info("=== PHASE 5: Network Consensus Verification ===")
        from ..monitoring.network_consensus import NetworkConsensusMonitor
        
        consensus_monitor = NetworkConsensusMonitor(
            nodes=self.nodes,
            node_cli_path=self.node_cli_path,
            network_name=self.topology.network.name,
            check_interval=2.0
        )
        
        try:
            await consensus_monitor.wait_for_network_ready(timeout=float(self.timeouts.get('startup', 600)))
            logger.info("network_consensus_achieved")
        except TimeoutError as e:
            logger.error("network_consensus_timeout_critical",
                        error=str(e),
                        note="Network failed to reach consensus - stopping all containers")
            
            # Collect metrics for diagnosis
            try:
                metrics = await consensus_monitor.collect_all_metrics()
                logger.error("final_network_state_before_shutdown",
                           metrics={
                               node_id: {
                                   "online": m.is_online,
                                   "error": m.error,
                                   "node_list_count": m.node_list_count,
                                   "blocks": m.main_chain_blocks,
                               }
                               for node_id, m in metrics.items()
                           })
            except Exception as diag_error:
                logger.warning("failed_to_collect_diagnostic_metrics",
                             error=str(diag_error))
            
            # Stop all containers (unless keep_running is set for debugging)
            if not self.keep_running:
                logger.info("stopping_failed_network")
                try:
                    self.compose.down(volumes=False, remove_images=False)
                except Exception as stop_error:
                    logger.warning("failed_to_stop_network",
                                 error=str(stop_error))
            else:
                logger.info("keeping_containers_running_for_debugging", note="--keep-running flag is set")
            
            # Re-raise with clear message
            raise RuntimeError(
                f"Network failed to reach consensus within 60s. "
                f"All nodes must be online with synchronized node lists and chains. "
                f"Check logs above for details. Network has been stopped."
            ) from e
        
        # =================================================================
        # PHASE 6: CREATE FULL SNAPSHOT (if genesis_stage == 'full')
        # =================================================================
        # Create final snapshot after all phases complete (if not already created in phase1)
        genesis_stage = self.suite_isolation_config.get('genesis_stage', 'full')
        if genesis_stage == 'full':
            if self.suite_isolation_config.get('auto_create_on_startup', True):
                if self.snapshot_manager.mode != SnapshotMode.DISABLED:
                    logger.info("creating_final_snapshot_after_all_phases")
                    containers_paused = False
                    try:
                        # Pause all containers to freeze state
                        logger.info("pausing_containers_for_final_snapshot")
                        self.compose.pause()
                        containers_paused = True
                        
                        # Create snapshot of final state
                        snapshot_name = self.suite_isolation_config.get('snapshot_name', 'clean_state')
                        await self.create_clean_snapshot(name=snapshot_name)
                        logger.info("final_snapshot_created", name=snapshot_name)
                        
                        # Unpause containers - ready for first suite
                        logger.info("unpausing_containers")
                        self.compose.unpause()
                        containers_paused = False
                        logger.info("containers_unpaused_ready_for_first_suite")
                        
                    except Exception as e:
                        # Only unpause if we actually paused
                        if containers_paused:
                            try:
                                self.compose.unpause()
                            except:
                                pass
                        logger.warning("final_snapshot_creation_failed",
                                  error=str(e),
                                  note="Will fallback to traditional cleanup")
        
        logger.info("network_started",
                   nodes=len(self.nodes),
                   topology=self.topology.network.name)
    
    def _clean_node_data(self):
        """
        Clean node data directories on host.
        
        WARNING: This method removes ALL data including GDB (node list, validator orders).
        Use ONLY when preparing for a fresh start (e.g., after stopping old network).
        DO NOT call before creating snapshot - snapshot system automatically captures
        all mounted directories including GDB data.
        
        This method removes and recreates data directories mounted into containers,
        ensuring that wallets, chains, and other runtime data from previous runs
        don't pollute the next run.
        
        Called ONLY before initial network setup (after stopping old network).
        NOT called before snapshot creation - snapshot preserves current state.
        
        Implementation: Uses temporary Docker container (Alpine) to clean files.
        This ensures proper permissions for root-owned files created by node containers.
        """
        cache_dir = self.paths_config.get('cache_dir', '../../cache')
        cache_path = (self.base_path / cache_dir).resolve()
        data_dir = cache_path / "data"
        
        if not data_dir.exists():
            logger.debug("node_data_dir_not_exists", path=str(data_dir))
            return
        
        logger.info("removing_node_data_directories", path=str(data_dir))
        
        # Use Docker container to remove files (handles root-owned files)
        try:
            self.compose.clean_cache_data(cache_path)
            logger.info("node_data_removed")
        except Exception as e:
            logger.error("failed_to_remove_node_data", error=str(e))
            raise
        
        # Recreate data directory structure matching granular volume mounts
        data_dir.mkdir(parents=True, exist_ok=True)
        
        node_var_subdirs = [
            s.strip() for s in self.paths_config.get(
                'node_var_subdirs',
                'log, lib/ca, lib/global_db, lib/wallet, lib/network'
            ).split(',')
        ]
        for node_id in range(1, len(self.nodes) + 1):
            for subdir in node_var_subdirs:
                (data_dir / f"node{node_id}" / subdir).mkdir(parents=True, exist_ok=True)
            logger.debug("recreated_node_data_dir", node_id=node_id,
                        path=str(data_dir / f"node{node_id}"))
        
        logger.info("node_data_cleaned_and_recreated", nodes=len(self.nodes))
    
    async def stop(self, remove_volumes: bool = False) -> None:
        """
        Stop the test network.
        
        Args:
            remove_volumes: Remove data volumes
        """
        logger.info("stopping_network", remove_volumes=remove_volumes)
        
        # Stop Docker services
        self.compose.down(volumes=remove_volumes)
        
        logger.info("network_stopped")
    
    async def restart(self, node_name: Optional[str] = None) -> None:
        """
        Restart network or specific node.
        
        Args:
            node_name: Node to restart (None = all)
        """
        if node_name:
            logger.info("restarting_node", node=node_name)
            # Restart specific container
            containers = self.compose.ps()
            for container in containers:
                service = container.labels.get("com.docker.compose.service")
                if service == node_name:
                    container.restart()
                    logger.info("node_restarted", node=node_name)
                    return
            
            logger.warning("node_not_found", node=node_name)
        else:
            logger.info("restarting_network")
            await self.stop(remove_volumes=False)
            await self.start(rebuild=False, wait_ready=True)
    
    async def get_status(self) -> Dict[str, any]:
        """
        Get network status.
        
        Returns:
            Status information dict
        """
        logger.debug("getting_network_status")
        
        # Get container status
        service_status = self.compose.get_service_status()
        
        # Get health status via JSON-RPC (CLI)
        health_status = {}
        for node_name, config in self.nodes.items():
            try:
                # Convert node_name to container name (node1 -> node-1)
                if node_name.startswith('node'):
                    container_name = f"{self.compose.project_name}-node-{node_name[4:]}"
                else:
                    container_name = f"{self.compose.project_name}-{node_name}"
                
                container = self.compose.client.containers.get(container_name)
                network_name = self.topology.network.name
                cli_result = container.exec_run(
                    f'cellframe-node-cli net get status -net {network_name}',
                    demux=False
                )
                
                if cli_result.exit_code == 0:
                    output = cli_result.output.decode("utf-8")
                    # Parse state
                    current_state = "unknown"
                    for line in output.split('\n'):
                        if 'current:' in line and 'NET_STATE_' in line:
                            parts = line.split(':', 1)
                            if len(parts) == 2:
                                current_state = parts[1].strip()
                                break
                    
                    health_status[node_name] = {
                        "healthy": current_state == "NET_STATE_ONLINE",
                        "state": current_state,
                        "response_time_ms": 0,  # Not applicable for CLI
                    }
                else:
                    health_status[node_name] = {
                        "healthy": False,
                        "state": "unavailable",
                        "response_time_ms": 0,
                    }
            except Exception as e:
                logger.warning("failed_to_get_node_health", node=node_name, error=str(e))
                health_status[node_name] = {
                    "healthy": False,
                    "state": "error",
                    "response_time_ms": 0,
                }
        
        # Build nodes array with combined info
        nodes_data = []
        for node_name, config in self.nodes.items():
            # Convert node_name to docker service name (node1 -> node-1)
            if node_name.startswith('node'):
                docker_service = f"node-{node_name[4:]}"
            else:
                docker_service = node_name
            
            # Get container status (service_status values are strings, not dicts)
            container_status = service_status.get(docker_service, "unknown")
            # Get health status
            health = health_status.get(node_name, {})
            
            nodes_data.append({
                "name": node_name,
                "role": config.role,
                "container_status": container_status,
                "health_status": health.get("state", "unknown"),
                "healthy": health.get("healthy", False),
                "rpc_port": config.rpc_port,
                "p2p_port": config.p2p_port,
            })
        
        return {
            "topology": self.topology_name,
            "network_name": self.topology.network.name,
            "total_nodes": len(self.nodes),
            "nodes": nodes_data,
            "containers": service_status,
            "health": health_status,
        }
    
    async def _wait_for_network_ready(self) -> None:
        """
        Wait for all nodes to be ready.
        
        Uses timeout from config [timeouts] section.
        """
        timeout = self.timeouts.get('health_check', 300)
        logger.info("waiting_for_network_ready", timeout=timeout)
        
        # Wait for Docker containers and nodes to reach ONLINE state
        # This is now handled entirely by compose.wait_for_services()
        # which uses CLI to check node state
        self.compose.wait_for_services(timeout=int(timeout))
        
        logger.info("network_ready", nodes=len(self.nodes))
    
    def get_node_logs(
        self,
        node_name: str,
        tail: int = 100,
        follow: bool = False,
    ) -> str:
        """
        Get logs for a node.
        
        Args:
            node_name: Node identifier
            tail: Number of lines from end
            follow: Follow log output
            
        Returns:
            Log output
        """
        logger.debug("fetching_logs", node=node_name, tail=tail)
        
        return self.compose.logs(node_name, follow=follow, tail=tail)
    
    def exec_in_node(
        self,
        node_name: str,
        command: List[str],
    ) -> tuple[int, str]:
        """
        Execute command in node container.
        
        Args:
            node_name: Node identifier
            command: Command to execute
            
        Returns:
            Tuple of (exit_code, output)
        """
        logger.debug("executing_in_node",
                    node=node_name,
                    command=" ".join(command))
        
        return self.compose.exec(node_name, command)
    
    def list_nodes(self) -> List[Dict[str, any]]:
        """
        List all configured nodes.
        
        Returns:
            List of node information dicts
        """
        return [
            {
                "name": name,
                "id": config.node_id,
                "role": config.role,
                "type": config.node_type,
                "rpc_port": config.rpc_port,
                "p2p_port": config.p2p_port,
                "ip": config.ip_address,
            }
            for name, config in self.nodes.items()
        ]
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.health_checker.close()
    
    async def create_clean_snapshot(
        self,
        name: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Create a snapshot of current clean environment state.

        CRITICAL: This method does NOT clean data before creating snapshot.
        Snapshot system (squashfs/filesystem) automatically captures all mounted
        directories including GDB data. Cleaning data before snapshot would
        remove critical GDB data (node list, validator orders) needed for
        network operation.

        Should be called after network is fully initialized and ready,
        before any tests are run.

        Args:
            name: Optional snapshot name (defaults to config snapshot_name)
            extra_metadata: Optional dict to store in snapshot (e.g. emission_hash for phase1)

        Returns:
            True if snapshot created successfully
        """
        snapshot_name = name or self.suite_isolation_config.get('snapshot_name', 'clean_state')

        logger.info("creating_clean_snapshot",
                   name=snapshot_name,
                   mode=self.snapshot_manager.mode.value)

        result = await self.snapshot_manager.create_snapshot(snapshot_name, extra_metadata=extra_metadata)
        
        if result and self.suite_isolation_config.get('auto_cleanup', True):
            # Cleanup old snapshots
            keep_count = self.suite_isolation_config.get('keep_snapshot_count', 5)
            await self.snapshot_manager.cleanup_old_snapshots(keep_count)
        
        return result
    
    async def restore_clean_state(self, name: Optional[str] = None) -> bool:
        """
        Restore environment to clean snapshot state.
        
        Uses lightweight compose.up() instead of full start() to preserve
        committed Docker images set by the hybrid snapshot system. The full
        start() would regenerate the compose file, overwriting image overrides.
        
        Args:
            name: Optional snapshot name (defaults to config snapshot_name)
            
        Returns:
            True if restore successful
        """
        snapshot_name = name or self.suite_isolation_config.get('snapshot_name', 'clean_state')
        
        logger.info("restoring_clean_state",
                   name=snapshot_name,
                   mode=self.snapshot_manager.mode.value)
        
        if self.snapshot_manager.mode == SnapshotMode.DISABLED:
            logger.info("snapshot_mode_disabled_skipping_restore")
            return True
        
        if self.snapshot_manager.mode == SnapshotMode.RECREATE:
            logger.info("recreate_mode_using_clean_test_data")
            await self.clean_test_data()
            return True
        
        # Remove containers+networks so compose.up() creates fresh ones
        # with correct bind mounts (compose.stop() would leave stale mounts
        # after _docker_cleanup replaces host directories)
        logger.info("stopping_containers_before_snapshot_restore")
        self.compose.down(volumes=False)
        
        result = await self.snapshot_manager.restore_snapshot(snapshot_name)
        
        if not result:
            logger.error("snapshot_restore_failed",
                        name=snapshot_name,
                        hint="Run './clean.sh' to fix permission issues, then retry")
            raise RuntimeError(
                f"Snapshot restore failed for '{snapshot_name}'. "
                "This is usually caused by permission issues with Docker files. "
                "Run './clean.sh' to remove root-owned files and try again."
            )
        
        # Start node services only (docker_compose services are started by suite setup)
        node_configs = list(self.nodes.values())
        node_services = [f"node-{n.node_id}" for n in node_configs]
        
        logger.info("starting_containers_after_snapshot_restore",
                   services=node_services)
        self.compose.up(
            services=node_services,
            detach=True, wait=False, no_build=False,
        )
        
        startup_timeout = self.timeouts.get('startup', 600)
        await self.state_manager.wait_for_nodes_online(
            node_configs, timeout=startup_timeout,
        )
        
        return result
    
    async def clean_test_data(self) -> None:
        """
        Clean test data from all nodes (traditional approach).
        
        This is the original cleanup method, now used as fallback or for 'recreate' mode.
        Removes user-generated data while preserving system files.
        """
        logger.info("cleaning_test_data_traditional_method")
        
        for node_name in self.nodes.keys():
            try:
                # Execute cleanup inside container to avoid permission issues
                cleanup_script = """
                # Clean user-generated data
                rm -f /opt/cellframe-node/var/lib/wallet/*.dwallet 2>/dev/null || true
                rm -rf /opt/cellframe-node/var/lib/chains/* 2>/dev/null || true
                rm -rf /opt/cellframe-node/var/lib/gdb/* 2>/dev/null || true
                rm -f /opt/cellframe-node/var/log/*.log 2>/dev/null || true
                
                # Preserve:
                # - /opt/cellframe-node/var/lib/ca/ (validator certificates)
                # - /opt/cellframe-node/var/run/ (PID files, sockets)
                
                echo "Cleanup complete for $(hostname)"
                """
                
                exit_code, output = self.compose.exec(
                    node_name,
                    ["sh", "-c", cleanup_script]
                )
                
                if exit_code == 0:
                    logger.debug("node_data_cleaned", node=node_name)
                else:
                    logger.warning("node_cleanup_failed",
                                  node=node_name,
                                  exit_code=exit_code,
                                  output=output)
            except Exception as e:
                logger.error("node_cleanup_error",
                            node=node_name,
                            error=str(e))
    
    async def _wait_for_master_containers_running(
        self,
        master_nodes: List[NodeConfig],
        timeout: float = 60.0,
        poll_interval: float = 2.0
    ) -> None:
        """
        Wait for master node containers to be running after restart.
        
        Some containers may crash after hard restart (e.g., MDBX assert failure)
        and need to be restarted. This method ensures all containers are running.
        
        Args:
            master_nodes: List of master nodes to check
            timeout: Maximum time to wait (seconds)
            poll_interval: Time between checks (seconds)
            
        Raises:
            RuntimeError: If containers don't start within timeout
        """
        import time
        
        start_time = time.time()
        logger.info("waiting_for_master_containers", node_count=len(master_nodes), timeout=timeout)
        
        while time.time() - start_time < timeout:
            all_running = True
            crashed_containers = []
            
            for node in master_nodes:
                container_name = f"{self.compose.project_name}-node-{node.node_id}"
                try:
                    container = self.compose.client.containers.get(container_name)
                    container.reload()
                    
                    if container.status == 'running':
                        continue
                    elif container.status in ['exited', 'dead']:
                        exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                        logger.warning("container_crashed_restarting",
                                     node_id=node.node_id,
                                     status=container.status,
                                     exit_code=exit_code)
                        
                        # Attempt to restart crashed container
                        try:
                            container.restart(timeout=30)
                            logger.info("container_restarted", node_id=node.node_id)
                            all_running = False  # Wait for restart to complete
                            crashed_containers.append(node.node_id)
                        except Exception as e:
                            logger.error("container_restart_failed",
                                       node_id=node.node_id,
                                       error=str(e))
                            # Try docker-compose restart as fallback
                            service_name = f"node-{node.node_id}"
                            try:
                                self.compose.restart(services=[service_name])
                                logger.info("container_restarted_via_compose", node_id=node.node_id)
                                all_running = False
                                crashed_containers.append(node.node_id)
                            except Exception as e2:
                                logger.error("container_restart_via_compose_failed",
                                           node_id=node.node_id,
                                           error=str(e2))
                    else:
                        logger.debug("container_not_running_yet",
                                   node_id=node.node_id,
                                   status=container.status)
                        all_running = False
                        
                except Exception as e:
                    logger.warning("container_check_failed",
                                node_id=node.node_id,
                                error=str(e))
                    all_running = False
            
            if all_running:
                if crashed_containers:
                    logger.info("crashed_containers_restarted", nodes=crashed_containers)
                    # Give restarted containers time to start
                    await asyncio.sleep(5.0)
                logger.info("all_master_containers_running", elapsed=time.time() - start_time)
                return
            
            await asyncio.sleep(poll_interval)
        
        # Timeout reached - check final status
        failed_nodes = []
        for node in master_nodes:
            container_name = f"{self.compose.project_name}-node-{node.node_id}"
            try:
                container = self.compose.client.containers.get(container_name)
                container.reload()
                if container.status != 'running':
                    exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                    failed_nodes.append(f"node-{node.node_id} (status={container.status}, exit={exit_code})")
            except Exception:
                failed_nodes.append(f"node-{node.node_id} (not found)")
        
        error_msg = f"Master containers failed to start within {timeout}s: {', '.join(failed_nodes)}"
        logger.error("master_containers_startup_timeout", timeout=timeout, failed=failed_nodes)
        raise RuntimeError(error_msg)
