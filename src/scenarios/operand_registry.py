"""
Registry for custom operands defined as YAML scenario fragments.

Operand files live in ``<common_root>/operands/*.yml`` and declare
reusable named actions that expand into sequences of regular steps.

File format::

    operand: kelvpn
    description: "KelVPN client management"
    actions:
      install:
        description: "Install KelVPN client on target nodes"
        steps:
          - bash: |
              echo "installing..."
            node: "{{node}}"

Optional ``default_action`` field: when the YAML value for the operand key is
not a recognised action name, the value is passed as the ``args`` parameter and
the ``default_action`` is used instead.  This enables compact inline syntax::

    operand: kelvpn_cli
    default_action: run
    actions:
      run:
        params:
          timeout: 15
        steps:
          - bash: timeout {{timeout}} /opt/kelvpn/bin/KelVPNCli {{args}} 2>&1 || true
            node: "{{node}}"

Scenario usage::

    - kelvpn_cli: "--authinfo"   # action value ≠ "run" → args="--authinfo", action=run
      node: full-1
      save: result
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..utils.logger import get_logger

logger = get_logger(__name__)


class OperandDefinition:
    """Parsed operand definition."""

    __slots__ = ("name", "description", "actions", "source_path", "default_action")

    def __init__(self, name: str, description: str, actions: Dict[str, Any],
                 source_path: Path, default_action: Optional[str] = None):
        self.name = name
        self.description = description
        self.actions = actions
        self.source_path = source_path
        self.default_action = default_action

    def get_action_steps(self, action: str) -> List[dict]:
        """Return raw step dicts for *action*."""
        if action not in self.actions:
            available = ", ".join(sorted(self.actions))
            raise KeyError(
                f"Operand '{self.name}' has no action '{action}'. "
                f"Available: {available}"
            )
        return list(self.actions[action].get("steps", []))

    def get_action_defaults(self, action: str) -> Dict[str, Any]:
        """Return default parameter values declared under ``params:`` for *action*."""
        if action not in self.actions:
            return {}
        return dict(self.actions[action].get("params", {}))


class OperandRegistry:
    """Loads and provides access to custom operand definitions."""

    def __init__(self) -> None:
        self._operands: Dict[str, OperandDefinition] = {}

    @property
    def names(self) -> Set[str]:
        return set(self._operands)

    def load_directory(self, directory: Path) -> None:
        """Scan *directory* for ``*.yml`` operand definitions."""
        if not directory.is_dir():
            return
        for yml_path in sorted(directory.glob("*.yml")):
            try:
                self._load_file(yml_path)
            except Exception as exc:
                logger.warning("operand_load_failed", path=str(yml_path), error=str(exc))

    def _load_file(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict) or "operand" not in data:
            return
        name = data["operand"]
        actions = data.get("actions", {})
        defn = OperandDefinition(
            name=name,
            description=data.get("description", ""),
            actions=actions,
            source_path=path,
            default_action=data.get("default_action"),
        )
        self._operands[name] = defn
        logger.info("operand_registered", name=name, actions=list(actions), path=str(path))

    def is_operand(self, name: str) -> bool:
        return name in self._operands

    def get(self, name: str) -> OperandDefinition:
        return self._operands[name]
