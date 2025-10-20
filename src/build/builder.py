"""
Build manager for cellframe node artifacts.

Handles:
- Building cellframe-node
- Building certificates
- Managing build cache
- Artifact verification
"""

from pathlib import Path
from typing import Optional, List
import hashlib

from pydantic import BaseModel

from ..utils.logger import get_logger
from ..utils.cli import run_command, print_info, print_success, print_error

logger = get_logger(__name__)


class BuildResult(BaseModel):
    """Result of build operation."""
    
    success: bool
    build_type: str
    artifacts: List[str]
    duration_s: float
    cache_used: bool = False


class BuildManager:
    """Manage building of cellframe node and tools."""
    
    def __init__(self, base_path: Path):
        """
        Initialize build manager.
        
        Args:
            base_path: Base path to stage-env directory
        """
        self.base_path = base_path
        self.project_root = base_path.parent.parent  # Go up to project root
        self.build_dir = self.project_root / "build"
        self.cache_dir = base_path / "cache" / "build"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("build_manager_initialized",
                   project_root=str(self.project_root))
    
    def build(
        self,
        build_type: str = "debug",
        clean: bool = False,
        parallel: int = 0,
    ) -> BuildResult:
        """
        Build cellframe-node.
        
        Args:
            build_type: 'debug' or 'release'
            clean: Clean build (remove build dir first)
            parallel: Number of parallel jobs (0 = auto)
            
        Returns:
            BuildResult object
        """
        import time
        
        start_time = time.time()
        
        logger.info("starting_build",
                   build_type=build_type,
                   clean=clean,
                   parallel=parallel)
        
        print_info(f"Building cellframe-node ({build_type} mode)")
        
        try:
            # Clean if requested
            if clean and self.build_dir.exists():
                logger.info("cleaning_build_dir")
                print_info("Cleaning build directory...")
                import shutil
                shutil.rmtree(self.build_dir)
            
            # Create build directory
            self.build_dir.mkdir(parents=True, exist_ok=True)
            
            # Configure with CMake
            cmake_build_type = "Debug" if build_type == "debug" else "Release"
            
            print_info("Configuring with CMake...")
            run_command(
                ["cmake", 
                 f"-DCMAKE_BUILD_TYPE={cmake_build_type}",
                 ".."],
                cwd=self.build_dir,
            )
            
            # Build
            jobs = parallel if parallel > 0 else self._get_cpu_count()
            
            print_info(f"Building with {jobs} parallel jobs...")
            run_command(
                ["cmake", "--build", ".", "--", f"-j{jobs}"],
                cwd=self.build_dir,
            )
            
            # Find artifacts
            artifacts = self._find_artifacts()
            
            duration = time.time() - start_time
            
            print_success(f"Build completed in {duration:.1f}s")
            logger.info("build_completed",
                       duration_s=duration,
                       artifacts_count=len(artifacts))
            
            return BuildResult(
                success=True,
                build_type=build_type,
                artifacts=artifacts,
                duration_s=duration,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            
            print_error(f"Build failed: {e}")
            logger.error("build_failed",
                        error=str(e),
                        duration_s=duration)
            
            return BuildResult(
                success=False,
                build_type=build_type,
                artifacts=[],
                duration_s=duration,
            )
    
    def _get_cpu_count(self) -> int:
        """Get number of CPU cores for parallel builds."""
        import os
        return os.cpu_count() or 4
    
    def _find_artifacts(self) -> List[str]:
        """
        Find built artifacts.
        
        Returns:
            List of artifact paths (relative to build dir)
        """
        artifacts = []
        
        # Look for main executable
        cellframe_node = self.build_dir / "cellframe-node"
        if cellframe_node.exists():
            artifacts.append("cellframe-node")
        
        # Look for CLI tool
        cellframe_cli = self.build_dir / "cellframe-node-cli"
        if cellframe_cli.exists():
            artifacts.append("cellframe-node-cli")
        
        # Look for cert generator
        cert_gen = self.build_dir / "dap-sdk" / "crypto" / "tools" / "cert-generator"
        if cert_gen.exists():
            artifacts.append(str(cert_gen.relative_to(self.build_dir)))
        
        logger.debug("artifacts_found", count=len(artifacts), artifacts=artifacts)
        
        return artifacts
    
    def artifacts_exist(self) -> bool:
        """
        Check if build artifacts exist.
        
        Returns:
            True if artifacts are present
        """
        artifacts = self._find_artifacts()
        return len(artifacts) > 0
    
    def get_artifact_hash(self, artifact_path: str) -> str:
        """
        Calculate hash of artifact for cache validation.
        
        Args:
            artifact_path: Path to artifact (relative to build dir)
            
        Returns:
            SHA256 hash hex string
        """
        full_path = self.build_dir / artifact_path
        
        if not full_path.exists():
            return ""
        
        sha256 = hashlib.sha256()
        
        with open(full_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def verify_artifacts(self) -> bool:
        """
        Verify that artifacts are valid executables.
        
        Returns:
            True if all artifacts are valid
        """
        logger.info("verifying_artifacts")
        
        artifacts = self._find_artifacts()
        
        if not artifacts:
            logger.warning("no_artifacts_found")
            return False
        
        for artifact in artifacts:
            full_path = self.build_dir / artifact
            
            if not full_path.exists():
                logger.error("artifact_missing", artifact=artifact)
                return False
            
            # Check if executable
            if not full_path.stat().st_mode & 0o111:
                logger.error("artifact_not_executable", artifact=artifact)
                return False
        
        logger.info("artifacts_verified", count=len(artifacts))
        return True
    
    def clean(self) -> None:
        """Remove build directory and cache."""
        logger.info("cleaning_build")
        
        import shutil
        
        if self.build_dir.exists():
            print_info("Removing build directory...")
            shutil.rmtree(self.build_dir)
        
        if self.cache_dir.exists():
            print_info("Removing build cache...")
            shutil.rmtree(self.cache_dir)
        
        print_success("Build artifacts cleaned")
        logger.info("build_cleaned")
    
    def get_build_info(self) -> dict:
        """
        Get information about current build.
        
        Returns:
            Dict with build information
        """
        artifacts = self._find_artifacts()
        
        return {
            "build_dir": str(self.build_dir),
            "artifacts_exist": len(artifacts) > 0,
            "artifacts": artifacts,
            "build_dir_size_mb": self._get_dir_size(self.build_dir) / (1024 * 1024)
                                 if self.build_dir.exists() else 0,
        }
    
    def _get_dir_size(self, path: Path) -> int:
        """
        Calculate directory size in bytes.
        
        Args:
            path: Directory path
            
        Returns:
            Size in bytes
        """
        total = 0
        
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except PermissionError:
            pass
        
        return total

