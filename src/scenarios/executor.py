"""
YAML scenario executor with runtime context and error handling.

Executes test scenarios step-by-step with variable substitution,
CLI command execution, and result validation.
"""

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.utils.logger import get_logger
from ..monitoring import MonitoringManager, DatumMonitorResult
from .parser import ScenarioParser
from .schema import (
    CLIStep, RPCStep, WaitStep, WaitForDatumStep, PythonStep, PrintStep, BashStep, ToolStep, LoopStep, StepGroup,
    NetworkWaitStep, DockerOpStep, SnapshotStep,
    SetStep, IfStep, WhileStep, SwitchStep, ForStep,
    ConfigStep, DpkgStep, CustomOperandStep,
    MetricStep, MetricsTableStep,
    CLICheck, RPCCheck, PythonCheck, BashCheck,
    TestScenario, SuiteSetupScenario, TestStep, CheckSpec, StepDefaults, SectionConfig, DatumStatus
)
from .operand_registry import OperandRegistry

logger = get_logger(__name__)


class ScenarioExecutionError(Exception):
    """Error during scenario execution."""
    
    def __init__(self, message: str, step: Optional[Any] = None, context: Optional[Dict] = None):
        self.step = step
        self.context = context
        super().__init__(self._format_message(message))
    
    def _format_message(self, message: str) -> str:
        """Format error with context."""
        parts = [message]
        if self.step:
            parts.append(f"Step: {self.step}")
        if self.context:
            parts.append(f"Context: {self.context}")
        return "\n".join(parts)


class RuntimeContext:
    """Runtime context for scenario execution."""
    
    def __init__(self, scenario: Union[TestScenario, SuiteSetupScenario]):
        """Initialize runtime context."""
        self.scenario = scenario
        self.variables: Dict[str, Any] = scenario.variables.copy() if hasattr(scenario, 'variables') else {}
        
        # Add network_name from network configuration
        if hasattr(scenario, 'network') and scenario.network:
            if hasattr(scenario.network, 'name') and scenario.network.name:
                self.variables['network_name'] = scenario.network.name
                logger.debug(f"Set network_name from scenario.network.name: {scenario.network.name}")
            else:
                logger.warning(f"scenario.network exists but has no 'name' attribute or it's None")
        else:
            logger.warning(f"scenario has no 'network' attribute or it's None")
        
        self.step_results: List[Dict[str, Any]] = []
        self._metrics: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.parser = ScenarioParser(Path.cwd())
    
    def set_variable(self, name: str, value: Any):
        """Set runtime variable."""
        self.variables[name] = value
        logger.debug(f"Set variable: {name} = {value}")
    
    def get_variable(self, name: str) -> Any:
        """Get runtime variable."""
        if name not in self.variables:
            raise ScenarioExecutionError(f"Undefined variable: {name}")
        return self.variables[name]

    def has_variable(self, name: str) -> bool:
        return name in self.variables

    def delete_variable(self, name: str) -> None:
        self.variables.pop(name, None)
    
    def get(self, name: str, default: Any = None) -> Any:
        """Get runtime variable with optional default (dict-like interface)."""
        return self.variables.get(name, default)

    def __getattr__(self, name: str) -> Any:
        """Allow accessing variables as attributes."""
        try:
            return self.get_variable(name)
        except ScenarioExecutionError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    
    def substitute(self, text: str) -> str:
        """Substitute variables in text."""
        return self.parser.substitute_variables(text, self.variables)
    
    def add_result(self, step_type: str, success: bool, details: Dict[str, Any]):
        """Record step execution result."""
        result = {
            "type": step_type,
            "success": success,
            "timestamp": time.time() - self.start_time,
            **details
        }
        self.step_results.append(result)

    def add_metric(self, entry: Dict[str, Any]):
        """Record a metric entry (from ``metric:`` step)."""
        self._metrics.append(entry)

    def get_metrics(self) -> List[Dict[str, Any]]:
        """Return all collected metrics."""
        return list(self._metrics)

    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        total = len(self.step_results)
        passed = sum(1 for r in self.step_results if r["success"])
        failed = total - passed
        duration = time.time() - self.start_time
        
        summary = {
            "scenario": self.scenario.name,
            "total_steps": total,
            "passed": passed,
            "failed": failed,
            "duration_seconds": round(duration, 2),
            "success_rate": round(passed / total * 100, 1) if total > 0 else 0,
        }
        if self._metrics:
            summary["metrics"] = self._metrics
        return summary


class ScenarioExecutor:
    """Execute test scenarios with full lifecycle management."""
    
    def __init__(self, node_cli_path: str = "cellframe-node-cli", log_file: Optional[Path] = None, debug: bool = False, base_path: Optional[Path] = None, custom_templates_dirs=None):
        """
        Initialize executor.
        
        Args:
            node_cli_path: Path to cellframe-node-cli binary
            log_file: Optional path to detailed log file
            debug: Enable debug logging
            base_path: Base path to stage-env directory (for artifacts collection)
            custom_templates_dirs: List of paths to search for J2 config templates
        """
        self.node_cli_path = node_cli_path
        self.log_file = log_file
        self.debug = debug
        self._custom_templates_dirs = custom_templates_dirs or []
        self._running = False
        # Monitoring manager будет получен через синглтон при старте сценария
        # Node role to ID mapping cache (populated from topology)
        self._node_role_mapping: Optional[Dict[str, str]] = None
        # Base path for artifacts collection (default to log_file parent or current dir)
        if base_path:
            self.base_path = Path(base_path)
        elif log_file:
            self.base_path = log_file.parent
        else:
            self.base_path = Path.cwd()
        self.current_scenario_name: Optional[str] = None
        # Docker container manager for fail-fast container operations
        from ..docker.container import DockerContainerManager
        self.container_manager = DockerContainerManager(self.base_path, node_cli_path)
        # Step executors
        from .step import (
            CLIStepExecutor, RPCStepExecutor, PythonStepExecutor, PrintStepExecutor,
            BashStepExecutor, ToolStepExecutor, WaitStepExecutor,
            WaitForDatumStepExecutor, LoopStepExecutor,
            NetworkWaitStepExecutor, DockerOpStepExecutor, SnapshotStepExecutor,
            SetStepExecutor, IfStepExecutor, WhileStepExecutor, SwitchStepExecutor, ForStepExecutor,
            ConfigStepExecutor, DpkgStepExecutor
        )
        self.cli_executor = CLIStepExecutor(self.container_manager, log_file, debug)
        self.cli_executor._executor_ref = self  # Pass executor reference for retry support
        self.rpc_executor = RPCStepExecutor(self.container_manager, log_file, debug)
        self.python_executor = PythonStepExecutor(self.container_manager, log_file, debug)
        self.print_executor = PrintStepExecutor(self.container_manager, log_file, debug)
        self.bash_executor = BashStepExecutor(self.container_manager, log_file, debug)
        self.tool_executor = ToolStepExecutor(self.container_manager, log_file, debug)
        self.wait_executor = WaitStepExecutor(
            self.container_manager, log_file, debug, node_cli_path,
            resolve_node_alias_callback=self._resolve_node_alias,
            get_node_config_callback=self._get_node_config,
            create_exec_cli_callback=self._create_exec_cli_for_waiter
        )
        self.wait_for_datum_executor = WaitForDatumStepExecutor(
            self.container_manager, log_file, debug, node_cli_path
        )
        self.loop_executor = LoopStepExecutor(
            self.container_manager, log_file, debug,
            execute_steps_callback=self._execute_steps
        )
        self.network_wait_executor = NetworkWaitStepExecutor(
            self.container_manager, log_file, debug, node_cli_path,
            resolve_node_alias_callback=self._resolve_node_alias,
            get_node_config_callback=self._get_node_config
        )
        self.docker_op_executor = DockerOpStepExecutor(
            self.container_manager, log_file, debug,
            resolve_node_alias_callback=self._resolve_node_alias,
            wait_executor=self.wait_executor
        )
        self.snapshot_executor = SnapshotStepExecutor(
            self.container_manager, log_file, debug, compose_manager=None,
            base_path=self.base_path if hasattr(self, 'base_path') else None,
            config_loader=self.config_loader if hasattr(self, 'config_loader') else None,
        )
        self.set_executor = SetStepExecutor(self.container_manager, log_file, debug)
        self.if_executor = IfStepExecutor(
            self.container_manager, log_file, debug,
            execute_steps_callback=self._execute_steps
        )
        self.while_executor = WhileStepExecutor(
            self.container_manager, log_file, debug,
            execute_steps_callback=self._execute_steps
        )
        self.for_executor = ForStepExecutor(
            self.container_manager, log_file, debug,
            execute_steps_callback=self._execute_steps
        )
        self.switch_executor = SwitchStepExecutor(
            self.container_manager, log_file, debug,
            execute_steps_callback=self._execute_steps
        )
        self.config_executor = ConfigStepExecutor(
            self.container_manager, log_file, debug,
            resolve_node_alias_callback=self._resolve_node_alias,
            custom_templates_dirs=self._custom_templates_dirs,
        )
        self.dpkg_executor = DpkgStepExecutor(self.container_manager, log_file, debug)

        from .step.metrics import MetricStepExecutor, MetricsTableStepExecutor
        self.metric_executor = MetricStepExecutor(self.container_manager, log_file, debug)
        self.metrics_table_executor = MetricsTableStepExecutor(self.container_manager, log_file, debug)

        # Custom operand support
        self._operand_registry = OperandRegistry()
        from .step.custom_operand import CustomOperandStepExecutor
        self.custom_operand_executor = CustomOperandStepExecutor(
            self.container_manager, log_file, debug,
            registry=self._operand_registry,
            execute_steps_callback=self._execute_steps,
        )

        # Check executors
        from .check import (
            CLICheckExecutor, RPCCheckExecutor,
            PythonCheckExecutor, BashCheckExecutor
        )
        self.cli_check_executor = CLICheckExecutor(self.container_manager, log_file, debug)
        self.rpc_check_executor = RPCCheckExecutor(self.container_manager, log_file, debug)
        self.python_check_executor = PythonCheckExecutor(self.container_manager, log_file, debug)
        self.bash_check_executor = BashCheckExecutor(self.container_manager, log_file, debug)
    
    def load_operands(self, *dirs: Path) -> None:
        """Load custom operand definitions from directories."""
        for d in dirs:
            self._operand_registry.load_directory(Path(d))

    @property
    def operand_registry(self) -> OperandRegistry:
        return self._operand_registry

    def _resolve_node_alias(self, node_alias: str) -> str:
        """
        Resolve node alias to actual node ID.
        
        Supports formats:
        - node1, node2, ... -> node1, node2 (passthrough)
        - node-1, node-2 -> node1, node2
        - root-1, root-2 -> first/second root node
        - master-1, master-2 -> first/second master node
        - full-1, full-2 -> first/second full node
        
        Args:
            node_alias: Node alias from scenario
            
        Returns:
            Actual node ID (e.g., "node1")
        """
        # Direct node ID (node1, node2, etc.)
        if node_alias.startswith("node") and len(node_alias) > 4 and node_alias[4:].isdigit():
            return node_alias
        
        # node-N format -> nodeN
        if node_alias.startswith("node-"):
            node_num = node_alias[5:]
            if node_num.isdigit():
                return f"node{node_num}"

        # Custom service names added via node_compose_gen (e.g. cdb-node-1,
        # kelvpn-client-3).  These are direct docker-compose service names —
        # return as-is so that container_manager can map them.
        if re.match(r'^[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*-\d+$', node_alias):
            return node_alias

        _KNOWN_ROLES = {"root", "master", "full"}

        # Role-based aliases (root-1, master-2, full-1)
        if "-" in node_alias:
            parts = node_alias.rsplit("-", 1)
            if len(parts) == 2:
                role, index_str = parts
                if index_str.isdigit():
                    index = int(index_str)
                    
                    # Try to resolve from topology mapping first
                    if self._node_role_mapping:
                        role_nodes = [
                            node_id for node_id, node_role in self._node_role_mapping.items()
                            if node_role == role
                        ]
                        if role_nodes and 1 <= index <= len(role_nodes):
                            return role_nodes[index - 1]  # 1-indexed
                    
                    if role in _KNOWN_ROLES:
                        if not self._global_context:
                            raise RuntimeError(
                                f"Cannot resolve node alias '{node_alias}': global_context not initialized. "
                                "Ensure topology is loaded before using role-based aliases."
                            )
                        
                        root_count = getattr(self._global_context, 'root_count', None)
                        master_count = getattr(self._global_context, 'master_count', None)
                        
                        if root_count is None or master_count is None:
                            raise RuntimeError(
                                f"Cannot resolve node alias '{node_alias}': root_count or master_count not set in global_context. "
                                f"root_count={root_count}, master_count={master_count}"
                            )
                        
                        if role == "root":
                            return f"node{index}"
                        elif role == "master":
                            return f"node{index + root_count}"
                        elif role == "full":
                            return f"node{index + root_count + master_count}"
        
        # Fallback: return as-is (will fail later if invalid)
        return node_alias
    
    def _lookup_compose_node_id(self, service_name: str):
        """Resolve NODE_ID from docker-compose.generated.yml for custom services."""
        try:
            compose_file = self.base_path / "docker-compose.generated.yml"
            if not compose_file.exists():
                return None
            import yaml
            with open(compose_file) as f:
                data = yaml.safe_load(f)
            svc = (data or {}).get("services", {}).get(service_name)
            if not svc:
                return None
            nid = svc.get("environment", {}).get("NODE_ID")
            if nid is not None:
                return int(nid)
        except Exception:
            pass
        return None

    def _resolve_node_to_container(self, node: str) -> str:
        """Convert node ID/alias to Docker container name (delegates to container manager)."""
        # First resolve alias to node ID, then convert to container name
        node_id = self._resolve_node_alias(node)
        return self.container_manager.resolve_node_to_container(node_id)
    
    def _log_to_file(self, message: str):
        """Write message to log file if enabled."""
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + '\n')
    
    def _merge_defaults(
        self,
        *defaults_list: Optional[StepDefaults]
    ) -> Optional[StepDefaults]:
        """
        Merge multiple StepDefaults objects with priority (last wins).
        
        Args:
            *defaults_list: List of StepDefaults to merge (global → section → group → step)
            
        Returns:
            Merged StepDefaults or None
        """
        merged = {}
        merged_cli = {}
        
        for defaults in defaults_list:
            if defaults:
                if defaults.node is not None:
                    merged['node'] = defaults.node
                if defaults.wait is not None:
                    merged['wait'] = defaults.wait
                if defaults.expect is not None:
                    merged['expect'] = defaults.expect
                if defaults.timeout is not None:
                    merged['timeout'] = defaults.timeout
                if defaults.cli is not None:
                    # Merge CLI defaults (later overrides earlier)
                    merged_cli.update(defaults.cli)
        
        if merged_cli:
            merged['cli'] = merged_cli
        
        return StepDefaults(**merged) if merged else None
    
    def _apply_defaults(self, step: TestStep, defaults: Optional[StepDefaults]) -> TestStep:
        """
        Apply defaults to a step if not already set.
        
        Args:
            step: Original step
            defaults: Defaults to apply
            
        Returns:
            Step with defaults applied
        """
        if not defaults:
            return step
        
        # Universal approach: apply all defaults to all steps that have these attributes
        # No type checking - just check if attribute exists and has default value
        
        # node
        if defaults.node and hasattr(step, 'node'):
            if step.node == "node1":  # Default value
                step.node = defaults.node
        
        # wait
        if defaults.wait and hasattr(step, 'wait'):
            if not isinstance(defaults.wait, str):
                 logger.error(f"defaults.wait IS NOT A STRING: {type(defaults.wait)}: {defaults.wait}")
            
            if not step.wait:  # None or empty
                step.wait = defaults.wait
        
        # expect
        if defaults.expect and hasattr(step, 'expect'):
            if step.expect == "success":  # Default value
                step.expect = defaults.expect
        
        # timeout
        if defaults.timeout and hasattr(step, 'timeout'):
            if step.timeout == 30:  # Default value
                step.timeout = defaults.timeout
        
        # Special handling for WaitForDatumStep timeouts
        if isinstance(step, WaitForDatumStep) and defaults.timeout:
            # Apply timeout to all WaitForDatumStep timeout fields if they have default values
            if step.timeout_total == 300:
                step.timeout_total = defaults.timeout
            if step.timeout_mempool == 60:
                step.timeout_mempool = defaults.timeout
            if step.timeout_verification == 120:
                step.timeout_verification = defaults.timeout
            if step.timeout_in_blocks == 180:
                step.timeout_in_blocks = defaults.timeout
        
        return step
    
    async def execute_scenario(
        self, 
        scenario: Union[TestScenario, SuiteSetupScenario],
        compose_manager=None,
        snapshot_manager=None,
        genesis_config_manager=None,
        initial_variables: Optional[Dict[str, Any]] = None,
        global_context=None,
        node_configs: Optional[List[Any]] = None
    ) -> RuntimeContext:
        """
        Execute complete test scenario or suite setup.
        
        Args:
            scenario: Parsed test scenario or suite setup scenario
            compose_manager: Optional DockerComposeManager for docker_op steps
            snapshot_manager: Optional SnapshotManager for snapshot steps
            genesis_config_manager: Optional GenesisConfigManager for config updates
            initial_variables: Optional dict of initial variables to set in context
            global_context: Optional ScenarioGlobalContext for automatic IP collection
            node_configs: Optional list of NodeConfig objects for IP collection
            
        Returns:
            Runtime context with results
            
        Raises:
            ScenarioExecutionError: If execution fails
        """
        logger.info(f"Starting scenario: {scenario.name}")
        if hasattr(scenario, 'description') and scenario.description:
            logger.info(f"Description: {scenario.description}")
        
        ctx = RuntimeContext(scenario)
        
        # Set managers in context for docker_op and snapshot steps
        if compose_manager:
            ctx.compose_manager = compose_manager
            # Update snapshot executor with compose_manager for container stop/start
            self.snapshot_executor.compose_manager = compose_manager
        if snapshot_manager:
            ctx.snapshot_manager = snapshot_manager
        if genesis_config_manager:
            ctx.genesis_config_manager = genesis_config_manager
        if node_configs:
            ctx.node_configs = node_configs
        
        # Store global context and node configs for post-setup IP collection
        self._global_context = global_context
        self._node_configs = node_configs
        
        # Set initial variables if provided
        if initial_variables:
            for key, value in initial_variables.items():
                ctx.set_variable(key, value)
        
        # CRITICAL: Pre-inject static node lists BEFORE setup phase
        # These variables (all_nodes, root_nodes, etc.) are needed by docker_op: start
        # IPs will be refreshed AFTER containers are running
        if global_context and node_configs:
            # Set counts and static IPs from topology
            global_context.set_static_node_info(node_configs)
            
            # Inject all static variables (node lists, counts, static IPs)
            static_vars = global_context.to_dict()
            for key, value in static_vars.items():
                ctx.set_variable(key, value)
            
            logger.info("static_context_pre_injected",
                       all_nodes_count=len(static_vars.get('all_nodes', [])),
                       root_count=global_context.root_count,
                       master_count=global_context.master_count,
                       static_ips=len(static_vars.get('node_ip', {})))
        
        self._running = True
        
        try:
            # Global defaults (applied to all phases)
            global_defaults = scenario.defaults if hasattr(scenario, 'defaults') else None
            
            # Debug: log defaults
            if self.debug and global_defaults:
                self._log_to_file(f"\n[DEBUG] Global defaults: {global_defaults}")
                if global_defaults.cli:
                    self._log_to_file(f"[DEBUG] CLI defaults: {global_defaults.cli}")
            
            # Install runtime packages/files before setup phase
            if hasattr(scenario, 'packages') and scenario.packages:
                from .step.package import PackageInstaller
                pkg_installer = PackageInstaller(
                    self.container_manager, self.log_file, self.debug,
                    resolve_node_alias_callback=self._resolve_node_alias,
                    base_path=self.base_path
                )
                logger.info("installing_runtime_packages", count=len(scenario.packages))
                await pkg_installer.install_packages(scenario.packages)

            if hasattr(scenario, 'files') and scenario.files:
                from .step.file import FileInstaller
                file_installer = FileInstaller(
                    self.container_manager, self.log_file, self.debug,
                    resolve_node_alias_callback=self._resolve_node_alias,
                    base_path=self.base_path
                )
                logger.info("installing_runtime_files", count=len(scenario.files))
                await file_installer.install_files(scenario.files)

            # Setup phase
            if hasattr(scenario, 'setup') and scenario.setup:
                logger.info("Executing setup phase...")
                section_defaults = self._merge_defaults(global_defaults, scenario.setup.defaults)
                await self._execute_steps(scenario.setup.steps, ctx, section_defaults)
                
                # CRITICAL: After setup phase, collect node IPs into global context
                # Setup phase typically starts containers, so IPs should now be available
                if self._global_context and self._node_configs:
                    logger.info("collecting_node_ips_after_setup", 
                               nodes=len(self._node_configs))
                    try:
                        self._global_context.collect_node_ips(self._node_configs, wait_for_ips=True)
                        
                        # Re-inject global variables with IPs now available
                        global_vars = self._global_context.to_dict()
                        for key, value in global_vars.items():
                            ctx.set_variable(key, value)
                        
                        logger.info("global_context_with_ips_injected",
                                   node_count=self._global_context.node_count,
                                   node_ip_count=len(self._global_context._node_ip_map))
                    except Exception as e:
                        logger.warning("failed_to_collect_node_ips", 
                                     error=str(e),
                                     note="Continuing without node IPs")
            
            # Initialize CLI parser after setup (containers should be running now)
            # This ensures CLI defaults can be applied to commands in test phase
            if compose_manager:
                from src.utils.cli_parser import get_cli_parser
                from pathlib import Path
                
                cli_parser = get_cli_parser()
                if not cli_parser._parsed:
                    logger.info("initializing_cli_parser_after_setup")
                    # Try to find a running node container
                    try:
                        # Find first running node container using container manager
                        containers = self.container_manager.docker_client.containers.list(filters={"name": "cellframe-stage-node-"})
                        if containers:
                            container_name = containers[0].name
                            cache_file = Path(__file__).parent.parent.parent / ".cache" / "cli_commands.json"
                            cache_file.parent.mkdir(parents=True, exist_ok=True)
                            cli_parser.cache_file = cache_file
                            parser_success = await cli_parser.parse_cli_help(container_name, use_cache=True)
                            if parser_success:
                                stats = cli_parser.get_stats()
                                logger.info("cli_parser_initialized_after_setup", 
                                           commands=stats['total_commands'],
                                           note="CLI defaults will be applied to commands")
                            else:
                                logger.warning("cli_parser_init_failed_after_setup",
                                             note="CLI defaults may not be applied")
                        else:
                            logger.warning("no_running_containers_for_cli_parser",
                                         note="Cannot initialize CLI parser - no containers running")
                    except Exception as e:
                        logger.warning("failed_to_initialize_cli_parser", error=str(e),
                                     note="CLI defaults may not be applied")
            
            # Detect node version and inject cf_version* variables
            await self._detect_node_version(ctx)
            
            # Test phase (only for TestScenario, not for SuiteSetupScenario)
            if hasattr(scenario, 'test') and scenario.test:
                logger.info("Executing test phase...")
                section_defaults = self._merge_defaults(global_defaults, scenario.test.defaults)
                await self._execute_steps(scenario.test.steps, ctx, section_defaults)
            
            # Check phase (only for TestScenario)
            if hasattr(scenario, 'check') and scenario.check:
                logger.info("Executing check phase...")
                section_defaults = self._merge_defaults(global_defaults, scenario.check.defaults)
                await self._execute_checks(scenario.check.steps, ctx, section_defaults)
            
            summary = ctx.get_summary()
            logger.info(f"Scenario completed: {summary['passed']}/{summary['total_steps']} steps passed")
            
            if summary['failed'] > 0:
                raise ScenarioExecutionError(
                    f"Scenario failed: {summary['failed']} step(s) failed",
                    context=summary
                )
            
            return ctx
            
        except KeyboardInterrupt:
            logger.warning("Scenario execution interrupted by user")
            raise
        except ScenarioExecutionError:
            raise
        except Exception as e:
            raise ScenarioExecutionError(
                f"Unexpected error during execution: {str(e)}",
                context=ctx.get_summary()
            ) from e
        finally:
            self._running = False
    
    async def _detect_node_version(self, ctx: RuntimeContext) -> None:
        """Detect cellframe-node version and inject cf_version* variables into context."""
        try:
            containers = self.container_manager.docker_client.containers.list(
                filters={"name": "cellframe-stage-node-"}
            )
            if not containers:
                logger.warning("no_containers_for_version_detection")
                return

            container_name = containers[0].name
            result = await self.container_manager.exec_cli_command("version", container_name)
            version_output = result.get("stdout", "").strip()

            if not version_output:
                logger.warning("empty_version_output")
                return

            ctx.set_variable("cf_version", version_output)

            # Parse "X.Y-BUILD" or "X.Y.Z" or "X.Y-SOMETHING" patterns
            m = re.search(r'(\d+)\.(\d+)(?:[.\-](\S+))?', version_output)
            if m:
                ctx.set_variable("cf_version_major", int(m.group(1)))
                ctx.set_variable("cf_version_minor", int(m.group(2)))
                ctx.set_variable("cf_version_build", m.group(3) or "")
            else:
                ctx.set_variable("cf_version_major", 0)
                ctx.set_variable("cf_version_minor", 0)
                ctx.set_variable("cf_version_build", "")

            logger.info("node_version_detected",
                       cf_version=version_output,
                       major=ctx.variables.get("cf_version_major"),
                       minor=ctx.variables.get("cf_version_minor"),
                       build=ctx.variables.get("cf_version_build"))
        except Exception as e:
            logger.warning("version_detection_failed", error=str(e))
            ctx.set_variable("cf_version", "unknown")
            ctx.set_variable("cf_version_major", 0)
            ctx.set_variable("cf_version_minor", 0)
            ctx.set_variable("cf_version_build", "")

    async def _execute_steps(
        self,
        steps: List[TestStep],
        ctx: RuntimeContext,
        defaults: Optional[StepDefaults] = None
    ):
        """
        Execute list of test steps with defaults.
        
        Args:
            steps: List of steps to execute
            ctx: Runtime context
            defaults: Default parameters to apply
        """
        for i, step in enumerate(steps, 1):
            # Generate step description for logging
            step_type = type(step).__name__
            step_desc = step_type
            
            # Add details for specific step types
            if isinstance(step, WaitForDatumStep):
                datum_count = len(step.wait_for_datum) if isinstance(step.wait_for_datum, list) else 1
                step_desc = f"WaitForDatumStep ({datum_count} datum{'s' if datum_count > 1 else ''})"
            elif isinstance(step, StepGroup) and step.name:
                step_desc = f"StepGroup: {step.name}"
            elif isinstance(step, ConfigStep):
                step_desc = f"ConfigStep ({step.config})"
            elif isinstance(step, DpkgStep):
                step_desc = f"DpkgStep ({step.dpkg} {step.package})"
            elif isinstance(step, MetricStep):
                step_desc = f"MetricStep ({step.metric}={step.value})"
            elif isinstance(step, MetricsTableStep):
                step_desc = f"MetricsTableStep ({step.metrics_table})"
            elif isinstance(step, CustomOperandStep):
                step_desc = f"CustomOperand ({step.operand_name}.{step.operand_action})"

            logger.info(f"Step {i}/{len(steps)}: {step_desc}")
            
            # Handle StepGroup
            if isinstance(step, StepGroup):
                # Merge group defaults with section defaults
                group_defaults = self._merge_defaults(defaults, step.defaults)
                
                # Recursively execute group steps
                await self._execute_steps(step.steps, ctx, group_defaults)
                
                if step.name:
                    logger.info(f"Exited group: {step.name}")
                continue
            
            # Apply defaults to step
            step = self._apply_defaults(step, defaults)
            
            if isinstance(step, CLIStep):
                await self.cli_executor.execute(step, ctx, defaults)
            elif isinstance(step, RPCStep):
                await self.rpc_executor.execute(step, ctx)
            elif isinstance(step, WaitStep):
                step_dump = step.model_dump() if hasattr(step, 'model_dump') else str(step)
                logger.info(f"Executing WaitStep. Dump: {step_dump}")
                if defaults and defaults.cli:
                    ctx.variables["_cli_defaults"] = defaults.cli
                await self.wait_executor.execute(step, ctx)
            elif isinstance(step, WaitForDatumStep):
                await self.wait_for_datum_executor.execute(step, ctx)
            elif isinstance(step, PythonStep):
                await self.python_executor.execute(step, ctx)
            elif isinstance(step, PrintStep):
                await self.print_executor.execute(step, ctx)
            elif isinstance(step, BashStep):
                await self.bash_executor.execute(step, ctx)
            elif isinstance(step, ToolStep):
                await self.tool_executor.execute(step, ctx)
            elif isinstance(step, LoopStep):
                await self.loop_executor.execute(step, ctx, defaults)
            elif isinstance(step, NetworkWaitStep):
                await self.network_wait_executor.execute(step, ctx)
            elif isinstance(step, DockerOpStep):
                await self.docker_op_executor.execute(step, ctx)
            elif isinstance(step, SnapshotStep):
                await self.snapshot_executor.execute(step, ctx)
            elif isinstance(step, SetStep):
                await self.set_executor.execute(step, ctx)
            elif isinstance(step, IfStep):
                await self.if_executor.execute(step, ctx, defaults)
            elif isinstance(step, WhileStep):
                await self.while_executor.execute(step, ctx, defaults)
            elif isinstance(step, ForStep):
                await self.for_executor.execute(step, ctx, defaults)
            elif isinstance(step, SwitchStep):
                await self.switch_executor.execute(step, ctx, defaults)
            elif isinstance(step, ConfigStep):
                await self.config_executor.execute(step, ctx)
            elif isinstance(step, DpkgStep):
                await self.dpkg_executor.execute(step, ctx)
            elif isinstance(step, MetricStep):
                await self.metric_executor.execute(step, ctx)
            elif isinstance(step, MetricsTableStep):
                await self.metrics_table_executor.execute(step, ctx)
            elif isinstance(step, CustomOperandStep):
                await self.custom_operand_executor.execute(step, ctx, defaults)
            else:
                raise ScenarioExecutionError(f"Unknown step type: {type(step)}")
    
    
    def _node_id_to_service(self, node_id: int) -> str:
        """Map numeric node_id to docker-compose service name."""
        svc = self._lookup_compose_node_id_reverse(node_id)
        if svc:
            return svc
        logger.debug("node_id_to_service_fallback", node_id=node_id, base_path=str(self.base_path))
        return f"node{node_id}"

    def _lookup_compose_node_id_reverse(self, node_id: int):
        """Reverse lookup: numeric NODE_ID → service name from compose file."""
        try:
            import yaml
            compose_file = self.base_path / "docker-compose.generated.yml"
            if not compose_file.exists():
                logger.warning("compose_not_found_reverse", path=str(compose_file))
                return None
            with open(compose_file) as f:
                data = yaml.safe_load(f)
            for name, svc in (data or {}).get("services", {}).items():
                env = svc.get("environment", {})
                if isinstance(env, dict) and str(env.get("NODE_ID")) == str(node_id):
                    return name
        except Exception as e:
            logger.warning("compose_reverse_lookup_failed", node_id=node_id, error=str(e))
        return None

    def _create_exec_cli_for_waiter(self):
        """Create synchronous exec_cli function for waiters with retry support."""
        # Waiters expect sync function, but we have async _run_cli_command
        # Use a closure that captures self and runs async command synchronously
        def exec_cli_sync(node_id: int, command: str, check_output: bool = True) -> tuple:
            """
            Synchronous wrapper that runs async CLI command with automatic retry.
            
            Retries on CLI initialization failures (e.g., "Can't find state of my node").
            """
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop.is_running():
                # If loop is running, we need to use a different approach
                # Create a new task and wait for it
                import concurrent.futures
                svc = self._node_id_to_service(node_id)
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._run_cli_command(
                            command, svc, 30,
                            retry_on_init_failure=True
                        )
                    )
                    result = future.result(timeout=40)
            else:
                svc = self._node_id_to_service(node_id)
                result = loop.run_until_complete(
                    self._run_cli_command(
                        command, svc, 30,
                        retry_on_init_failure=True
                    )
                )
            
            return result.get("returncode", -1), result.get("stdout", ""), result.get("stderr", "")
        
        return exec_cli_sync
    
    def _get_node_config(self, node_id: str):
        """Get NodeConfig for node ID - create minimal object with node_id attribute."""
        # First resolve alias if needed (root-1 -> node1, etc.)
        resolved = self._resolve_node_alias(node_id)
        
        # Extract numeric ID from node string (node1 -> 1, node-1 -> 1)
        if resolved.startswith("node"):
            num_str = resolved[4:]
            if num_str.isdigit():
                node_num = int(num_str)
            else:
                # Try node-N format
                if "-" in num_str:
                    node_num = int(num_str.split("-")[-1])
                else:
                    raise ValueError(f"Cannot parse node_id from: {resolved}")
        # Handle role-based aliases directly (root-1 -> 1, master-1 -> 4, etc.)
        elif node_id.startswith("root-"):
            node_num = int(node_id.split("-")[1])
        elif node_id.startswith("master-"):
            master_idx = int(node_id.split("-")[1])
            node_num = master_idx + 3  # master-1 -> 4, master-2 -> 5, etc.
        else:
            # Custom compose service — look up NODE_ID from generated compose
            nid = self._lookup_compose_node_id(resolved)
            if nid is not None:
                node_num = nid
            else:
                raise ValueError(f"Unknown node_id format: {node_id}")
        
        # Create minimal NodeConfig-like object
        from types import SimpleNamespace
        return SimpleNamespace(node_id=node_num)
    
    
    
    async def _execute_checks(
        self,
        checks: List[CheckSpec],
        ctx: RuntimeContext,
        defaults: Optional[StepDefaults] = None
    ):
        """Execute assertion checks with defaults."""
        for i, check in enumerate(checks, 1):
            logger.info(f"Check {i}/{len(checks)}: {type(check).__name__}")
            
            # Apply defaults universally - check if attribute exists
            if defaults:
                # node
                if defaults.node and hasattr(check, 'node'):
                    if check.node == "node1":  # Default value
                        check.node = defaults.node
                
                # timeout
                if defaults.timeout and hasattr(check, 'timeout'):
                    if check.timeout == 30:  # Default value
                        check.timeout = defaults.timeout
            
            if isinstance(check, CLICheck):
                await self.cli_check_executor.execute(check, ctx, defaults)
            elif isinstance(check, RPCCheck):
                await self.rpc_check_executor.execute(check, ctx)
            elif isinstance(check, PythonCheck):
                await self.python_check_executor.execute(check, ctx)
            elif isinstance(check, BashCheck):
                await self.bash_check_executor.execute(check, ctx)
            else:
                raise ScenarioExecutionError(f"Unknown check type: {type(check)}")
    
    
    async def _run_cli_command(
        self, command: str, node: str, timeout: Optional[int] = 30,
        retry_on_init_failure: bool = False, max_retries: int = 10
    ) -> Dict[str, Any]:
        """
        Run CLI command via docker exec with retry logic for initialization failures.
        
        Args:
            command: CLI command to execute
            node: Target node name
            timeout: Command timeout in seconds
            retry_on_init_failure: Retry if CLI returns "Can't find state" or similar init errors
            max_retries: Maximum number of retry attempts (default: 5)
            
        Returns:
            Dict with stdout, stderr, returncode
        """
        # Set test name for crash artifact collection
        self.container_manager.current_test_name = self.current_scenario_name
        
        # Patterns indicating CLI/node not fully initialized
        init_failure_patterns = [
            "Can't find state of my node",
            "Connection refused",
            "No such file or directory",  # Unix socket not created yet
        ]
        
        retry_count = 0
        retry_delay = 0.5  # Start with 0.5s
        
        while retry_count <= max_retries:
            result = await self.container_manager.exec_cli_command(command, node, timeout)
            
            # Check if it's an initialization failure (regardless of exit_code)
            # Cellframe CLI often returns exit_code=0 even with errors
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            output = stdout + stderr
            
            is_init_failure = any(pattern in output for pattern in init_failure_patterns)
            
            # If not an init failure or not retrying, return immediately
            if not is_init_failure or not retry_on_init_failure:
                return result
            
            # Init failure detected - check if we can retry
            if retry_count >= max_retries:
                # Exhausted retries - return error
                return result
            
            # Retry with exponential backoff
            retry_count += 1
            logger.info("cli_init_retry",
                       node=node,
                       command=command[:50],
                       attempt=retry_count,
                       max_retries=max_retries,
                       delay=retry_delay,
                       error=output[:100])
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 5.0)  # Cap at 5s
        
        # Should never reach here, but return last result as fallback
        return result
    
    async def _call_rpc(
        self, method: str, params: List[Any], node: str, timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """Call JSON-RPC method via HTTP."""
        import httpx
        
        # Assuming RPC endpoint is at http://node:8545
        url = f"http://{node}:8545"
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            return response.json()
    
    def _check_expectation(
        self, result: Dict[str, Any], expect: str, contains: Optional[str]
    ) -> bool:
        """Check if result matches expectation."""
        import json
        import yaml
        
        # Cellframe CLI always returns exit code 0, but puts errors in output
        # Output can be JSON or YAML format
        has_error = False
        stdout = result["stdout"].strip()
        
        if stdout:
            # Try to parse as YAML first (Cellframe CLI default format)
            try:
                yaml_response = yaml.safe_load(stdout)
                
                if self.debug:
                    self._log_to_file(f"[DEBUG] YAML parsed: type={type(yaml_response)}, value={yaml_response}")
                
                if isinstance(yaml_response, dict):
                    # Check for 'errors' key
                    if "errors" in yaml_response:
                        errors = yaml_response["errors"]
                        if self.debug:
                            self._log_to_file(f"[DEBUG] Found 'errors' in YAML: type={type(errors)}, value={errors}")
                        
                        # Cellframe CLI uses 'errors' field even for success!
                        # Check if errors dict has 'code' field - code: 0 means success
                        if isinstance(errors, dict):
                            error_code = errors.get('code')
                            if error_code is not None and error_code != 0:
                                has_error = True
                                if self.debug:
                                    self._log_to_file(f"[DEBUG] Detected error: code={error_code} (non-zero)")
                            elif error_code == 0:
                                if self.debug:
                                    self._log_to_file(f"[DEBUG] Success: code=0 in errors dict")
                            elif errors:
                                # No 'code' field but errors dict is not empty
                                has_error = True
                                if self.debug:
                                    self._log_to_file("[DEBUG] Detected error: errors dict without code field")
                        elif isinstance(errors, list) and len(errors) > 0:
                            has_error = True
                            if self.debug:
                                self._log_to_file("[DEBUG] Detected error: errors is non-empty list")
            except (yaml.YAMLError, ValueError, AttributeError) as e:
                # Try JSON format
                try:
                    json_response = json.loads(stdout)
                    
                    if isinstance(json_response, dict):
                        # Check for 'errors' key (can be dict or list)
                        if "errors" in json_response:
                            errors = json_response["errors"]
                            
                            # Check if errors dict has 'code' field - code: 0 means success
                            if isinstance(errors, dict):
                                error_code = errors.get('code')
                                if error_code is not None and error_code != 0:
                                    has_error = True
                                elif error_code == 0:
                                    # Success - code: 0
                                    pass
                                elif errors:
                                    # No 'code' field but errors dict is not empty
                                    has_error = True
                            elif isinstance(errors, list) and len(errors) > 0:
                                has_error = True
                except (json.JSONDecodeError, ValueError):
                    # Not JSON or YAML - check for text error patterns
                    error_patterns = ["error:", "Error:", "ERROR:", "failed", "Failed"]
                    if any(pattern in stdout for pattern in error_patterns):
                        has_error = True
        
        # Check expectation
        if expect == "success":
            # Success means: returncode 0 AND no errors
            if result["returncode"] != 0:
                return False
            if has_error:
                return False
        elif expect == "error":
            # Error means: returncode != 0 OR has errors
            if result["returncode"] == 0 and not has_error:
                return False
        
        # Check contains if specified
        if contains:
            if contains not in stdout:
                return False
        
        return True
