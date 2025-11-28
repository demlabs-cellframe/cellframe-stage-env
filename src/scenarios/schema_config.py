from typing import List, Optional, Union
from pydantic import BaseModel, Field

class ConfigStep(BaseModel):
    """
    Manage node configuration files.
    
    Actions:
    - disable_seed_mode: Disable seed mode and regenerate configs
    - enable_seed_mode: Enable seed mode
    - set_genesis: Set static_genesis_event/block hash
    - set_fee_addr: Set fee address in main.cfg
    - update: Update specific key in config file
    """
    config: str = Field(..., description="Action: 'disable_seed_mode', 'enable_seed_mode', 'set_genesis', 'set_fee_addr', 'update'")
    nodes: Union[str, List[str]] = Field(..., description="Target node(s)")
    
    # Parameters for set_genesis
    chain: Optional[str] = Field(None, description="Chain name (e.g. 'zerochain', 'main')")
    hash: Optional[str] = Field(None, description="Genesis hash value")
    
    # Parameters for set_fee_addr / update
    value: Optional[str] = Field(None, description="Value to set")
    
    # Parameters for update
    file: Optional[str] = Field(None, description="Config file name (e.g. 'main.cfg')")
    section: Optional[str] = Field(None, description="Config section (e.g. '[esbocs]')")
    key: Optional[str] = Field(None, description="Config key")
    
    # Optional parameters for disable_seed_mode (override auto-detection)
    zerochain_genesis_hash: Optional[str] = Field(None, description="Zerochain genesis hash (override)")
    main_genesis_hash: Optional[str] = Field(None, description="Mainchain genesis hash (override)")
    fee_addr: Optional[str] = Field(None, description="Fee address (override)")
