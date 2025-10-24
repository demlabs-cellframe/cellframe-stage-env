"""
YAML scenario schema definitions using Pydantic.

Provides type-safe models for test scenario definitions,
ensuring validation and user-friendly error messages.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class NodeRole(str, Enum):
    """Node role in network topology."""
    ROOT = "root"
    MASTER = "master"
    FULL = "full"
    LIGHT = "light"
    ARCHIVE = "archive"


class ExpectResult(str, Enum):
    """Expected command result."""
    SUCCESS = "success"
    ERROR = "error"
    ANY = "any"


# ============================================================================
# Network Configuration Models
# ============================================================================

class NodeConfig(BaseModel):
    """Single node configuration."""
    name: str = Field(..., description="Unique node identifier")
    role: NodeRole = Field(NodeRole.FULL, description="Node role in network")
    ip: Optional[str] = Field(None, description="Optional static IP")
    port: Optional[int] = Field(None, ge=1024, le=65535, description="Optional custom node port (default: 8079)")
    validator: bool = Field(False, description="Is validator node")
    
    class Config:
        use_enum_values = True


class NetworkConfig(BaseModel):
    """Network topology configuration."""
    topology: str = Field("default", description="Topology template name")
    nodes: List[NodeConfig] = Field(default_factory=list, description="Node configurations")
    
    @field_validator("topology")
    @classmethod
    def validate_topology(cls, v: str) -> str:
        """Ensure topology is specified."""
        if not v or not v.strip():
            raise ValueError("Network topology must be specified")
        return v.strip()


# ============================================================================
# Package Installation Models
# ============================================================================

class AptPackage(BaseModel):
    """APT package installation."""
    node: Union[str, List[str]] = Field(..., description="Node(s) to install on")
    apt: List[str] = Field(..., description="Package names to install")


class LocalPackage(BaseModel):
    """Local DEB package installation."""
    node: Union[str, List[str]] = Field(..., description="Node(s) to install on")
    local: str = Field(..., description="Local path to .deb file (supports glob)")


class URLPackage(BaseModel):
    """Remote package installation."""
    node: Union[str, List[str]] = Field(..., description="Node(s) to install on")
    url: str = Field(..., description="URL to download package from")
    checksum: Optional[str] = Field(None, description="Optional checksum (sha256:...)")


PackageSpec = Union[AptPackage, LocalPackage, URLPackage]


# ============================================================================
# File Placement Models
# ============================================================================

class FileFromSource(BaseModel):
    """Copy file from host to node."""
    node: Union[str, List[str]] = Field(..., description="Target node(s)")
    src: str = Field(..., description="Source file path on host")
    dst: str = Field(..., description="Destination path in node")
    mode: Optional[str] = Field(None, description="File permissions (e.g., '0755')")


class FileFromContent(BaseModel):
    """Create file from inline content."""
    node: Union[str, List[str]] = Field(..., description="Target node(s)")
    content: str = Field(..., description="File content (supports variables)")
    dst: str = Field(..., description="Destination path in node")
    mode: Optional[str] = Field(None, description="File permissions (e.g., '0755')")


FileSpec = Union[FileFromSource, FileFromContent]


# ============================================================================
# Test Step Models
# ============================================================================

class CLIStep(BaseModel):
    """Execute CLI command."""
    cli: str = Field(..., description="CLI command to execute")
    node: str = Field("node1", description="Node to execute on")
    description: Optional[str] = Field(None, description="Step description")
    save: Optional[str] = Field(None, description="Variable name to save result to")
    wait: Optional[str] = Field(None, description="Wait duration after command (e.g., '5s')")
    expect: ExpectResult = Field(ExpectResult.SUCCESS, description="Expected result")
    contains: Optional[str] = Field(None, description="Expected substring in output")
    timeout: Optional[int] = Field(30, description="Command timeout in seconds")
    
    class Config:
        use_enum_values = True


class RPCStep(BaseModel):
    """Execute JSON-RPC call."""
    rpc: str = Field(..., description="JSON-RPC method name")
    params: List[Any] = Field(default_factory=list, description="RPC parameters")
    node: str = Field("node1", description="Node to call RPC on")
    description: Optional[str] = Field(None, description="Step description")
    save: Optional[str] = Field(None, description="Variable name to save result to")
    wait: Optional[str] = Field(None, description="Wait duration after call")
    expect: ExpectResult = Field(ExpectResult.SUCCESS, description="Expected result")
    timeout: Optional[int] = Field(30, description="RPC call timeout")
    
    class Config:
        use_enum_values = True


class WaitStep(BaseModel):
    """Wait for duration or condition."""
    wait: str = Field(..., description="Duration (e.g., '5s') or condition")
    description: Optional[str] = Field(None, description="Step description")


class PythonStep(BaseModel):
    """Execute Python code with access to context."""
    python: str = Field(..., description="Python code to execute")
    description: Optional[str] = Field(None, description="Step description")
    save: Optional[str] = Field(None, description="Variable name to save result to")


class BashStep(BaseModel):
    """Execute Bash script."""
    bash: str = Field(..., description="Bash script to execute")
    node: str = Field("node1", description="Node to execute on")
    description: Optional[str] = Field(None, description="Step description")
    save: Optional[str] = Field(None, description="Variable name to save result to")
    expect: ExpectResult = Field(ExpectResult.SUCCESS, description="Expected result")
    timeout: Optional[int] = Field(30, description="Script timeout in seconds")
    
    class Config:
        use_enum_values = True


class LoopStep(BaseModel):
    """Loop over steps multiple times."""
    loop: int = Field(..., gt=0, description="Number of iterations")
    steps: List["TestStep"] = Field(..., description="Steps to repeat")


TestStep = Union[CLIStep, RPCStep, WaitStep, PythonStep, BashStep, LoopStep]


# ============================================================================
# Check/Assertion Models
# ============================================================================

class CLICheck(BaseModel):
    """Verify CLI command output."""
    cli: str = Field(..., description="CLI command to execute")
    node: str = Field("node1", description="Node to execute on")
    description: Optional[str] = Field(None, description="Check description")
    contains: Optional[str] = Field(None, description="Expected substring")
    not_contains: Optional[str] = Field(None, description="Substring that should not be present")
    equals: Optional[str] = Field(None, description="Exact expected output")
    timeout: Optional[int] = Field(30, description="Command timeout")


class RPCCheck(BaseModel):
    """Verify JSON-RPC call result."""
    rpc: str = Field(..., description="JSON-RPC method")
    params: List[Any] = Field(default_factory=list, description="RPC parameters")
    node: str = Field("node1", description="Node to call on")
    description: Optional[str] = Field(None, description="Check description")
    result_contains: Optional[Any] = Field(None, description="Expected value in result")
    result_equals: Optional[Any] = Field(None, description="Exact expected result")
    timeout: Optional[int] = Field(30, description="RPC timeout")


class PythonCheck(BaseModel):
    """Verify condition using Python code."""
    python: str = Field(..., description="Python code that should not raise AssertionError")
    description: Optional[str] = Field(None, description="Check description")


class BashCheck(BaseModel):
    """Verify condition using Bash script."""
    bash: str = Field(..., description="Bash script (exit 0 = success)")
    node: str = Field("node1", description="Node to execute on")
    description: Optional[str] = Field(None, description="Check description")
    timeout: Optional[int] = Field(30, description="Script timeout")


CheckSpec = Union[CLICheck, RPCCheck, PythonCheck, BashCheck]


# ============================================================================
# Main Scenario Model
# ============================================================================

class ScenarioMetadata(BaseModel):
    """Scenario metadata and description."""
    name: str = Field(..., description="Scenario display name")
    description: str = Field(..., description="What this scenario tests")
    author: Optional[str] = Field(None, description="Scenario author")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    version: str = Field("1.0", description="Scenario version")


class TestScenario(BaseModel):
    """Complete test scenario definition."""
    
    # Metadata
    name: str = Field(..., description="Scenario name")
    description: str = Field(..., description="Scenario description")
    author: Optional[str] = Field(None, description="Author name")
    tags: List[str] = Field(default_factory=list, description="Tags")
    version: str = Field("1.0", description="Version")
    
    # Includes for reusable configs
    includes: List[str] = Field(default_factory=list, description="Paths to included YAML files")
    
    # Network configuration
    network: NetworkConfig = Field(..., description="Network topology")
    
    # Package installation
    packages: List[PackageSpec] = Field(default_factory=list, description="Packages to install")
    
    # File placement
    files: List[FileSpec] = Field(default_factory=list, description="Files to place in nodes")
    
    # Setup phase
    setup: List[TestStep] = Field(default_factory=list, description="Setup steps")
    
    # Test phase
    test: List[TestStep] = Field(..., description="Test steps")
    
    # Check phase
    check: List[CheckSpec] = Field(default_factory=list, description="Assertions")
    
    # Variables (runtime context)
    variables: Dict[str, Any] = Field(default_factory=dict, description="Predefined variables")
    
    @model_validator(mode='after')
    def validate_scenario(self) -> 'TestScenario':
        """Validate scenario structure."""
        if not self.test:
            raise ValueError("Test scenario must have at least one test step")
        return self


# Allow forward references for recursive models
LoopStep.model_rebuild()

