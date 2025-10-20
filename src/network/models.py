"""
Data models for network management.

Defines common models used across network management modules.
"""

from pydantic import BaseModel


class NodeConfig(BaseModel):
    """Configuration for a single node."""
    
    node_id: int
    role: str  # root, master, full, validator
    node_type: str  # for grouping
    rpc_port: int
    p2p_port: int
    cf_port: int
    http_port: int
    ip_address: str

