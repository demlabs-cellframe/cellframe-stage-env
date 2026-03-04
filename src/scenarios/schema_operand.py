from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CustomOperandStep(BaseModel):
    """
    Invokes an action defined in a custom operand YAML file.

    Custom operands are scenario fragments stored in ``operands/*.yml``.
    Each operand file declares a set of *actions* — named sequences of
    ordinary steps.  At parse time the YAML key that matches a registered
    operand name is rewritten into this model so the executor can look up
    the action's steps and run them.

    YAML (user-facing)::

        - kelvpn: install
          nodes: ["node-7", "node-8"]

    After transformation by the parser the dict becomes::

        operand_name: kelvpn
        operand_action: install
        operand_params:
          nodes: ["node-7", "node-8"]

    The ``node`` field mirrors the convention used by other step types so that
    ``defaults: node:`` set on a StepGroup or section propagates automatically
    into operand_params when the caller did not supply it explicitly.
    """

    operand_name: str = Field(..., description="Registered operand name (e.g. 'kelvpn')")
    operand_action: str = Field(..., description="Action to execute (e.g. 'install')")
    operand_params: Dict[str, Any] = Field(default_factory=dict, description="Parameters forwarded to the action steps")
    description: Optional[str] = Field(None, description="Step description for logs")
    node: Optional[str] = Field(None, description="Node override (propagated from group/section defaults)")
