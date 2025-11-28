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
        """Parse 'var = val' syntax in 'set' field."""
        if '=' in self.set and self.value is None:
            # Split by first '=' only
            parts = self.set.split('=', 1)
            self.set = parts[0].strip()
            val_str = parts[1].strip()
            
            # Remove surrounding quotes if present (common in 'var = "val"')
            if (val_str.startswith('"') and val_str.endswith('"')) or \
               (val_str.startswith("'") and val_str.endswith("'")):
                val_str = val_str[1:-1]
            
            self.value = val_str
            
        if not self.set:
            raise ValueError("Variable name cannot be empty")
            
        if self.value is None:
             raise ValueError("Value must be provided either in 'value' field or in 'set' expression 'var = val'")
             
        return self


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

