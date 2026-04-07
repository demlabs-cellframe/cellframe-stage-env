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
      connect:
        steps:
          - ...
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..utils.logger import get_logger

logger = get_logger(__name__)


class OperandDefinition:
    """Parsed operand definition."""

    __slots__ = ("name", "description", "actions", "default_action", "source_path")

    def __init__(self, name: str, description: str, actions: Dict[str, Any],
                 source_path: Path, default_action: Optional[str] = None):
        self.name = name
        self.description = description
        self.actions = actions
        self.default_action = default_action
        self.source_path = source_path

    def resolve_action(self, action: str) -> tuple:
        """Resolve *action*, falling back to *default_action* if defined.

        Returns ``(resolved_action, extra_args)`` where *extra_args* is the
        original value to pass as ``args`` when the default action is used,
        or ``None`` when the action matched directly.
        """
        if action in self.actions:
            return action, None
        if self.default_action and self.default_action in self.actions:
            return self.default_action, action
        available = ", ".join(sorted(self.actions))
        raise KeyError(
            f"Operand '{self.name}' has no action '{action}'. "
            f"Available: {available}"
        )

    def get_action_steps(self, action: str) -> List[dict]:
        """Return raw step dicts for *action*."""
        resolved, _ = self.resolve_action(action)
        return list(self.actions[resolved].get("steps", []))


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
        default_action = data.get("default_action")
        defn = OperandDefinition(
            name=name,
            description=data.get("description", ""),
            actions=actions,
            source_path=path,
            default_action=default_action,
        )
        self._operands[name] = defn
        logger.info("operand_registered", name=name, actions=list(actions), path=str(path))

    def is_operand(self, name: str) -> bool:
        return name in self._operands

    def get(self, name: str) -> OperandDefinition:
        return self._operands[name]
