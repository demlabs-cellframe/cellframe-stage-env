from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

class ConfigStep(BaseModel):
    """
    Manage node configuration files by regenerating from templates.
    
    Usage:
      # Regenerate base config with seed_mode
      - config: "cellframe-node"
        nodes: [root-1, root-2, root-3]
        set:
          seed_mode: "true"
      
      # Update chain config with genesis hash
      - config: "stagenet/zerochain"
        nodes: [root-1]
        set:
          static_genesis_event: "{{token_hash}}"
          is_static_genesis_event: "true"
          
      # Update with string format
      - config: "stagenet/main"
        nodes: [master-1]
        set: "fee_addr={{fee_addr}}, minimum_fee=1.0"
    """
    config: str = Field(..., description="Config name/path (e.g. 'cellframe-node', 'stagenet/zerochain')")
    nodes: Union[str, List[str]] = Field(..., description="Target node(s)")
    set: Union[Dict[str, Any], str] = Field(default_factory=dict, description="Variables to inject (Dict or 'k=v, k2=v')")
