"""
YAML scenario parser with include support and variable substitution.

Provides loading, validation, and preprocessing of test scenarios
with user-friendly error messages.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import yaml
from pydantic import ValidationError, BaseModel

from src.utils.logger import get_logger
from .schema import TestScenario, SuiteSetupScenario

logger = get_logger(__name__)

T = TypeVar('T', bound=BaseModel)


class ScenarioParseError(Exception):
    """Error parsing scenario file."""
    
    def __init__(self, message: str, file_path: Optional[Path] = None, line: Optional[int] = None):
        self.file_path = file_path
        self.line = line
        super().__init__(self._format_message(message))
    
    def _format_message(self, message: str) -> str:
        """Format error message with context."""
        parts = []
        if self.file_path:
            parts.append(f"File: {self.file_path}")
        if self.line:
            parts.append(f"Line: {self.line}")
        parts.append(message)
        return "\n".join(parts)


class BaseScenarioParser:
    """
    Base parser with common YAML loading and include processing logic.
    
    Provides reusable functionality for both suite and scenario parsing.
    """
    
    def __init__(self, scenarios_root: Path, common_root: Optional[Path] = None):
        """
        Initialize base parser.
        
        Args:
            scenarios_root: Root directory for scenario/suite files
            common_root: Optional root directory for common includes
        """
        self.scenarios_root = Path(scenarios_root)
        self.common_root = Path(common_root) if common_root else self.scenarios_root
        self._loaded_files: Dict[Path, Dict[str, Any]] = {}
        # Pattern to match {{anything}} including complex expressions like {{map['key']}} or {{array[0]}}
        self._variable_pattern = re.compile(r'\{\{([^}]+)\}\}')

        from .operand_registry import OperandRegistry
        self._operand_registry = OperandRegistry()
        for candidate in [
            self.common_root / "operands",
            self.common_root / "common" / "operands",
        ]:
            if candidate.is_dir():
                self._operand_registry.load_directory(candidate)

    @property
    def operand_registry(self):
        return self._operand_registry
    
    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Load YAML file and return parsed data.
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            Parsed YAML data as dictionary
            
        Raises:
            ScenarioParseError: If file cannot be loaded or parsed
        """
        # Check cache first
        if file_path in self._loaded_files:
            return self._loaded_files[file_path].copy()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            self._loaded_files[file_path] = data
            return data.copy()
            
        except FileNotFoundError:
            raise ScenarioParseError(
                f"File not found: {file_path}",
                file_path=file_path
            )
        except yaml.YAMLError as e:
            raise ScenarioParseError(
                f"YAML parse error: {str(e)}",
                file_path=file_path
            ) from e
    
    def _process_includes(self, data: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
        """
        Process include directives in scenario/suite data.
        
        Args:
            data: Scenario/suite data with includes
            base_dir: Base directory for resolving relative paths
            
        Returns:
            Merged data with all includes processed
        """
        includes = data.pop("includes", [])
        
        if not includes:
            return data
        
        # Load all included files
        included_data: List[Dict[str, Any]] = []
        for include_path in includes:
            # Try multiple search paths:
            # 1. Relative to current file directory
            # 2. Relative to scenarios_root
            # 3. Relative to common_root (for common includes)
            # 4. Integration scenarios common directory (standard location)
            search_paths = [
                (base_dir / include_path).resolve(),
                (self.scenarios_root / include_path).resolve(),
                (self.common_root / include_path).resolve(),
                (self.common_root / "integration" / "scenarios" / include_path).resolve(),
            ]
            
            include_full = None
            for path in search_paths:
                if path.exists():
                    include_full = path
                    break
            
            if include_full is None:
                raise ScenarioParseError(
                    f"Included file not found: {include_path}\nSearched in:\n" +
                    "\n".join(f"  - {p}" for p in search_paths),
                    file_path=search_paths[0]
                )
            
            included = self._load_yaml_file(include_full)
            included_data.append(included)
        
        # Merge: includes first, then main data (main overrides)
        result = {}
        for included in included_data:
            result = self._deep_merge(result, included)
        result = self._deep_merge(result, data)
        
        return result
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries.
        
        Args:
            base: Base dictionary
            override: Dictionary with values to override base
            
        Returns:
            Merged dictionary
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dicts
                result[key] = self._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                # Concatenate lists
                result[key] = result[key] + value
            else:
                # Override value
                result[key] = value
        
        return result
    
    # ------------------------------------------------------------------
    # Custom operand step transformation
    # ------------------------------------------------------------------
    _KNOWN_STEP_KEYS = frozenset({
        "cli", "rpc", "wait", "wait_for_datum", "wait_network", "python",
        "print", "bash", "tool", "loop", "docker_op", "snapshot", "dpkg",
        "config", "set", "if", "while", "for", "switch", "name",
        "operand_name",
    })

    def _transform_operand_steps(self, data: Any) -> Any:
        """Recursively rewrite custom-operand dicts into ``CustomOperandStep`` format."""
        if isinstance(data, dict):
            # Is this dict a step invocation for a registered operand?
            operand_key = self._detect_operand_key(data)
            if operand_key is not None:
                action_value = str(data[operand_key])
                params = {k: v for k, v in data.items() if k not in (operand_key, "description")}
                defn = self._operand_registry.get(operand_key)

                # If the value is not a known action name and a default_action is declared,
                # treat the value as the 'args' parameter and use the default action.
                # This enables compact syntax:  - kelvpn_cli: "--authinfo"
                if defn.default_action and action_value not in defn.actions:
                    params["args"] = action_value
                    action = defn.default_action
                else:
                    action = action_value

                return {
                    "operand_name": operand_key,
                    "operand_action": action,
                    "operand_params": params,
                    "description": data.get("description"),
                }
            return {k: self._transform_operand_steps(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._transform_operand_steps(item) for item in data]
        return data

    def _detect_operand_key(self, step_dict: dict) -> Optional[str]:
        """Return the operand name if *step_dict* looks like a custom-operand invocation."""
        names = self._operand_registry.names
        if not names:
            return None
        for key in step_dict:
            if key in names and key not in self._KNOWN_STEP_KEYS:
                return key
        return None

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve relative path to absolute path.
        
        Args:
            path: Relative path string
            
        Returns:
            Absolute Path object
        """
        if Path(path).is_absolute():
            return Path(path)
        return (self.scenarios_root / path).resolve()


class ScenarioParser(BaseScenarioParser):
    """Parse and validate YAML test scenarios."""
    
    def load_scenario(self, scenario_path: str) -> TestScenario:
        """
        Load and parse scenario from YAML file.
        
        Args:
            scenario_path: Relative path to scenario file
            
        Returns:
            Parsed and validated test scenario
            
        Raises:
            ScenarioParseError: If scenario is invalid
        """
        full_path = self._resolve_path(scenario_path)
        
        if not full_path.exists():
            raise ScenarioParseError(
                f"Scenario file not found: {scenario_path}",
                file_path=full_path
            )
        
        try:
            # Load main scenario file
            raw_data = self._load_yaml_file(full_path)
            
            # Check if this is a suite descriptor (has 'suite: "Name"' field)
            if 'suite' in raw_data and isinstance(raw_data['suite'], str):
                from .schema import SuiteDescriptor
                suite = SuiteDescriptor(**raw_data)
                logger.info(f"Loaded suite descriptor: {suite.name} from {scenario_path}")
                # Return suite descriptor as-is (parser will handle differently)
                return suite
            
            # Process includes for regular scenarios
            if "includes" in raw_data:
                raw_data = self._process_includes(raw_data, full_path.parent)
            
            # Transform custom operand steps before Pydantic validation
            if self._operand_registry.names:
                raw_data = self._transform_operand_steps(raw_data)

            # Validate with Pydantic
            scenario = TestScenario(**raw_data)
            
            logger.info(f"Loaded scenario: {scenario.name} from {scenario_path}")
            return scenario
            
        except yaml.YAMLError as e:
            raise ScenarioParseError(
                f"YAML parse error: {str(e)}",
                file_path=full_path
            ) from e
        except ValidationError as e:
            raise ScenarioParseError(
                f"Validation error:\n{self._format_validation_errors(e)}",
                file_path=full_path
            ) from e
        except Exception as e:
            raise ScenarioParseError(
                f"Unexpected error: {str(e)}",
                file_path=full_path
            ) from e
    
    def _format_validation_errors(self, error: ValidationError) -> str:
        """Format Pydantic validation errors for user display."""
        lines = []
        for err in error.errors():
            field = " → ".join(str(x) for x in err["loc"])
            lines.append(f"  {field}: {err['msg']}")
        return "\n".join(lines)
    
    def substitute_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """
        Substitute {{variable}} placeholders in text.
        Supports:
        - Simple variables: {{var_name}}
        - Array indexing: {{array[0]}}, {{array[1]}}
        - Map/Dict string keys: {{map['key']}}, {{map["key"]}}
        - Nested access: {{map.key}} (if key is valid identifier)
        
        Args:
            text: Text with variable placeholders
            variables: Variable name -> value mapping
            
        Returns:
            Text with variables substituted
            
        Raises:
            ScenarioParseError: If undefined variable referenced or invalid index/key
        """
        import re
        
        def replace_var(match):
            full_expr = match.group(1)  # e.g., "array[0]", "map['key']", "map.key", "simple_var"
            
            # Try numeric indexing: var_name[123]
            if '[' in full_expr and full_expr.endswith(']') and not ("'" in full_expr or '"' in full_expr):
                try:
                    bracket_pos = full_expr.index('[')
                    var_name = full_expr[:bracket_pos]
                    index_str = full_expr[bracket_pos+1:-1]
                    
                    if index_str.isdigit():
                        index = int(index_str)
                        
                        if var_name not in variables:
                            raise ScenarioParseError(f"Undefined variable: {var_name}")
                        
                        value = variables[var_name]
                        if not isinstance(value, (list, tuple)):
                            raise ScenarioParseError(f"Variable '{var_name}' is not an array (type: {type(value).__name__})")
                        
                        if index < 0 or index >= len(value):
                            raise ScenarioParseError(f"Array index {index} out of bounds for '{var_name}' (length: {len(value)})")
                        
                        return str(value[index])
                except (ValueError, IndexError):
                    pass
            
            # Try string key indexing: var_name['key'] or var_name["key"]
            if '[' in full_expr and full_expr.endswith(']') and ("'" in full_expr or '"' in full_expr):
                try:
                    bracket_pos = full_expr.index('[')
                    var_name = full_expr[:bracket_pos]
                    key_part = full_expr[bracket_pos+1:-1]  # Get content between [ and ]
                    
                    # Remove quotes from key
                    if (key_part.startswith("'") and key_part.endswith("'")) or \
                       (key_part.startswith('"') and key_part.endswith('"')):
                        key = key_part[1:-1]
                        
                        if var_name not in variables:
                            raise ScenarioParseError(f"Undefined variable: {var_name}")
                        
                        value = variables[var_name]
                        if not isinstance(value, dict):
                            raise ScenarioParseError(f"Variable '{var_name}' is not a map/dict (type: {type(value).__name__})")
                        
                        if key not in value:
                            raise ScenarioParseError(f"Key '{key}' not found in map '{var_name}' (available keys: {list(value.keys())})")
                        
                        return str(value[key])
                except (ValueError, KeyError):
                    pass
            
            # Try dot notation: var_name.key
            if '.' in full_expr and full_expr.count('.') == 1:
                parts = full_expr.split('.')
                if len(parts) == 2:
                    var_name, key = parts
                    
                    if var_name not in variables:
                        raise ScenarioParseError(f"Undefined variable: {var_name}")
                    
                    value = variables[var_name]
                    if isinstance(value, dict):
                        if key not in value:
                            raise ScenarioParseError(f"Key '{key}' not found in map '{var_name}' (available keys: {list(value.keys())})")
                        return str(value[key])
                    elif hasattr(value, key):
                        # Support attribute access for objects
                        return str(getattr(value, key))
                    else:
                        raise ScenarioParseError(f"Variable '{var_name}' (type: {type(value).__name__}) does not support key/attribute '{key}'")
            
            # Simple variable
            if full_expr not in variables:
                raise ScenarioParseError(f"Undefined variable: {full_expr}")
            return str(variables[full_expr])
        
        return self._variable_pattern.sub(replace_var, text)


class SuiteSetupParser(BaseScenarioParser):
    """Parse and validate suite setup scenarios with includes."""
    
    def load_suite_setup(
        self,
        suite_includes: List[str],
        suite_setup: Optional[Dict[str, Any]],
        suite_name: str,
        base_dir: Path
    ) -> SuiteSetupScenario:
        """
        Load and parse suite setup scenario with includes.
        
        Args:
            suite_includes: List of include paths from suite descriptor
            suite_setup: Optional setup section from suite descriptor
            suite_name: Suite name for logging
            base_dir: Base directory for resolving includes
            
        Returns:
            Parsed SuiteSetupScenario with all includes merged
            
        Raises:
            ScenarioParseError: If parsing fails
        """
        try:
            # Build suite setup data
            suite_setup_data = {
                "name": f"{suite_name} - Suite Setup",
                "description": "Suite-level initialization",
                "includes": suite_includes,
                "setup": suite_setup or []
            }
            
            # Process includes to merge setup steps
            merged_data = self._process_includes(suite_setup_data, base_dir)
            
            # Transform custom operand steps before Pydantic validation
            if self._operand_registry.names:
                merged_data = self._transform_operand_steps(merged_data)

            # Create SuiteSetupScenario from merged data
            suite_setup_scenario = SuiteSetupScenario(**merged_data)

            logger.info(f"Loaded suite setup for '{suite_name}' with {len(suite_includes)} includes")
            return suite_setup_scenario
            
        except ValidationError as e:
            raise ScenarioParseError(
                f"Suite setup validation error:\n{self._format_validation_errors(e)}",
                file_path=base_dir
            ) from e
        except Exception as e:
            raise ScenarioParseError(
                f"Suite setup parse error: {str(e)}",
                file_path=base_dir
            ) from e
    
    def _format_validation_errors(self, error: ValidationError) -> str:
        """Format Pydantic validation errors for user display."""
        lines = []
        for err in error.errors():
            field = " → ".join(str(x) for x in err["loc"])
            lines.append(f"  {field}: {err['msg']}")
        return "\n".join(lines)
    
