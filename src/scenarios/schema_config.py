from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

class ConfigStep(BaseModel):
    """
    Manage node configuration files by regenerating from templates.
    
    Usage:
      # Regenerate base config (template auto-resolved in stage-env)
      - config: "cellframe-node"
        nodes: [root-1, root-2, root-3]
        set:
          seed_mode: "true"
      
      # cfg.d INI snippet (no template, direct INI write)
      - config: "cellframe-node.cfg.d/plugins.cfg"
        nodes: [node-9, node-10]
        set:
          plugins.enabled: "true"
          
      # Absolute path with external J2 template
      - config: "/var/lib/plugins/myplugin/myplugin.cfg"
        template: "{{project_root}}/tests/e2e/common/templates/myplugin/myplugin.cfg.j2"
        nodes: [node-9, node-10, node-11]
        set:
          key1: "blablabla"
          key2: "false"
          
      # Deploy rendered config directly into running container
      - config: "/opt/cellframe-node/var/lib/plugins/srv-vpn/srv-vpn.cfg"
        template: "srv-vpn.cfg.j2"
        deploy: container
        nodes: [vpn-server-1, vpn-server-2]
        set:
          enabled: "true"
          net: "{{network_name}}"
    """
    config: str = Field(..., description="Config path — relative name or absolute path with {{node_id}} placeholder")
    nodes: Union[str, List[str]] = Field(..., description="Target node(s)")
    set: Union[Dict[str, Any], str] = Field(default_factory=dict, description="Variables to inject (Dict or 'k=v, k2=v')")
    template: Optional[str] = Field(None, description="Path to J2 template (absolute or relative to project root)")
    deploy: Optional[str] = Field(None, description="Deploy mode: 'container' to write directly into running Docker container")
