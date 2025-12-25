from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    # Forward reference for type checking
    from .schema import TestStep

class SetStep(BaseModel):
    """
    Set variable value.
    
    Usage:
      - set: var_name
        value: 123
      
      - set: var_name = 123  # Compact syntax
    """
    set: str = Field(..., description="Variable name (or expression 'var = val')")
    value: Optional[Any] = Field(None, description="Value to set (string, number, or expression)")
    eval: bool = Field(False, description="Evaluate value as Python expression")

    @model_validator(mode='after')
    def parse_set_expression(self) -> 'SetStep':
        """Parse 'var = val' syntax in 'set' field.
        
        Type inference:
          - "text" or 'text' → string
          - 123 or 45.67 → number
          - true/false → boolean
          - null → None
          - unquoted text → string (fallback)
        """
        if '=' in self.set and self.value is None:
            # Split by first '=' only
            parts = self.set.split('=', 1)
            self.set = parts[0].strip()
            val_str = parts[1].strip()
            
            # Parse value with type inference
            self.value = self._parse_value(val_str)
            
        if not self.set:
            raise ValueError("Variable name cannot be empty")
            
        if self.value is None and not isinstance(self.value, type(None)):
            raise ValueError("Value must be provided either in 'value' field or in 'set' expression 'var = val'")
             
        return self
    
    @staticmethod
    def _parse_value(val_str: str) -> Any:
        """Parse value string with type inference.
        
        - Quoted strings ("text" or 'text') → str
        - Numbers (123, 45.67, -5, 1e10) → int/float
        - Booleans (true, false, True, False) → bool
        - Null (null, None) → None
        - Unquoted text → str (fallback)
        """
        # Check for quoted strings first
        if (val_str.startswith('"') and val_str.endswith('"')) or \
           (val_str.startswith("'") and val_str.endswith("'")):
            return val_str[1:-1]  # Return string without quotes
        
        # Try boolean
        if val_str.lower() == 'true':
            return True
        if val_str.lower() == 'false':
            return False
        
        # Try null/None
        if val_str.lower() in ('null', 'none'):
            return None
        
        # Try integer
        try:
            return int(val_str)
        except ValueError:
            pass
        
        # Try float (including scientific notation)
        try:
            return float(val_str)
        except ValueError:
            pass
        
        # Fallback to string
        return val_str


class IfStep(BaseModel):
    """Conditional execution."""
    condition: str = Field(..., alias="if", description="Python expression condition")
    then_steps: List["TestStep"] = Field(..., alias="then", description="Steps to execute if condition is true")
    else_steps: Optional[List["TestStep"]] = Field(None, alias="else", description="Steps to execute if condition is false")


class WhileStep(BaseModel):
    """While loop execution."""
    condition: str = Field(..., alias="while", description="Python expression condition")
    steps: List["TestStep"] = Field(..., description="Steps to execute")
    max_loops: int = Field(100, description="Maximum iterations (safety limit)")


class ForStep(BaseModel):
    """For loop execution."""
    item_var: str = Field(..., alias="for", description="Variable name for item")
    in_items: Union[List[Any], str] = Field(..., alias="in", description="List of items or expression evaluating to list")
    steps: List["TestStep"] = Field(..., description="Steps to execute")


class SwitchStep(BaseModel):
    """Switch/Case execution."""
    switch: str = Field(..., description="Variable or expression to switch on")
    cases: Dict[str, List["TestStep"]] = Field(..., description="Map of cases (value -> steps)")
    default: Optional[List["TestStep"]] = Field(None, description="Default steps if no case matches")


class AssertStep(BaseModel):
    """
    Assert condition.
    
    Usage:
      - assert: key_count == 3
        message: "Expected 3 validators"
      
      - assert: "'pkey_hash' in _keys_output"
    """
    condition: str = Field(..., alias="assert", description="Python expression that must be true")
    message: Optional[str] = Field(None, description="Custom error message if assertion fails")


class LogStep(BaseModel):
    """
    Log a message.
    
    Usage:
      - log: "✓ Validators: {{key_count}}"
      
      - log: "Processing node {{node_name}}"
        level: debug
    """
    message: str = Field(..., alias="log", description="Message to log (supports variable substitution)")
    level: str = Field("info", description="Log level: debug, info, warning, error")


class ExtractStep(BaseModel):
    """
    Extract value from string using regex.
    
    Usage:
      - extract: pkey_hash
        from: "{{_keys_output}}"
        pattern: "pkey_hash:\\s*(0x[A-Fa-f0-9]{64})"
        group: 1
      
      - extract: node_addr
        from: "{{_node_info}}"
        pattern: "current_addr:\\s*([A-F0-9:]+)"
    """
    var_name: str = Field(..., alias="extract", description="Variable name to store extracted value")
    source: str = Field(..., alias="from", description="Source string (supports variable substitution)")
    pattern: str = Field(..., description="Regex pattern with capture groups")
    group: int = Field(1, description="Capture group number (default: 1)")
    default: Optional[str] = Field(None, description="Default value if no match")


class CountStep(BaseModel):
    """
    Count occurrences of substring in string.
    
    Usage:
      - count: key_count
        in: "{{_keys_output}}"
        pattern: "pkey_hash:"
    """
    var_name: str = Field(..., alias="count", description="Variable name to store count")
    source: str = Field(..., alias="in", description="Source string to search in")
    pattern: str = Field(..., description="Substring or pattern to count")


class NodeListStep(BaseModel):
    """
    Generate list of node names.
    
    Usage:
      - node_list: root_nodes
        prefix: "node-"
        start: 1
        count: "{{root_count}}"
      
      - node_list: master_nodes
        prefix: "node-"
        start: "{{root_count + 1}}"
        count: "{{master_count}}"
    """
    var_name: str = Field(..., alias="node_list", description="Variable name for the list")
    prefix: str = Field("node-", description="Node name prefix")
    start: Union[int, str] = Field(1, description="Starting index (number or expression)")
    count: Union[int, str] = Field(..., description="Number of nodes (number or expression)")


class JoinStep(BaseModel):
    """
    Join list elements into string.
    
    Usage:
      - join: cert_list
        items: ["stagenet.root.pvt.0", "stagenet.root.pvt.1"]
        separator: ","
      
      - join: cert_list
        template: "stagenet.root.pvt.{i}"
        range: "{{root_count}}"
        separator: ","
    """
    var_name: str = Field(..., alias="join", description="Variable name for result string")
    items: Optional[List[str]] = Field(None, description="List of items to join")
    template: Optional[str] = Field(None, description="Template with {i} placeholder for range generation")
    range_count: Optional[Union[int, str]] = Field(None, alias="range", description="Generate items using template for range(n)")
    separator: str = Field(",", description="Separator between items")


class ComputeStep(BaseModel):
    """
    Compute expression and save result.
    
    Usage:
      - compute: node_num
        expr: "root_count + val_idx + 1"
      
      - compute: cert_name
        expr: "'stagenet.master.pvt.' + str(val_idx)"
    """
    var_name: str = Field(..., alias="compute", description="Variable name for result")
    expr: str = Field(..., description="Python expression to evaluate")


class FormatStep(BaseModel):
    """
    Format string with variable substitution.
    
    Usage:
      - format: node_name
        template: "node-{num}"
        num: "{{node_num}}"
      
      - format: wallet_name  
        template: "stagenet_master_{idx}"
        idx: "{{val_idx}}"
    """
    var_name: str = Field(..., alias="format", description="Variable name for result")
    template: str = Field(..., description="Template string with {var} placeholders")
    
    class Config:
        extra = "allow"  # Allow extra fields for template vars

