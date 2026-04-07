from typing import List, Optional, Union
from pydantic import BaseModel, Field


class DpkgStep(BaseModel):
    """
    Install or remove a .deb package inside Docker containers.

    Handles docker cp + dpkg -i automatically. The package path is resolved
    on the host (supports symlinks), copied into the container, installed,
    and the temporary file is cleaned up.

    Usage:
      # Install a single package into several containers
      - dpkg: install
        package: "{{project_root}}/build/cellframe-node-cdb.deb"
        services: ["node-9", "node-10", "node-11"]

      # Remove a package by name
      - dpkg: remove
        package: cellframe-node-cdb
        services: ["node-9"]
    """
    dpkg: str = Field(..., description="Operation: 'install' or 'remove'")
    package: str = Field(..., description="Host path to .deb (install) or package name (remove)")
    services: Union[str, List[str]] = Field(..., description="Docker services to operate on")
    fix_deps: bool = Field(False, description="Run apt-get install -f after dpkg -i to resolve dependencies")
    description: Optional[str] = Field(None, description="Step description for logs")
