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
    node_port: int = 8079  # Standard Cellframe node port for P2P/HTTP communications
    ip_address: str
    is_seed_node: bool = False  # Whether this node acts as a seed node
    balancer_enabled: bool = False  # Whether HTTP balancer is enabled
    consensus_participation: bool = False  # Whether participates in consensus

