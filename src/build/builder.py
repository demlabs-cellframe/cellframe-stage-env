"""
Build manager for cellframe node artifacts.

Handles:
- Building cellframe-node
- Building certificates
- Managing build cache
- Artifact verification
- Node source management (URL, repository, local)
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import hashlib
import shutil
import os

from pydantic import BaseModel

from src.utils.logger import get_logger
from src.utils.cli import run_command, print_info, print_success, print_error
from src.config.manager import get_config_loader
from src.utils.i18n import _

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
    
    def __init__(self, base_path: Path, node_source_config: Optional[Dict[str, Any]] = None):
        """
        Initialize build manager.
        
        Args:
            base_path: Base path to stage-env directory
            node_source_config: Node source configuration from stage-env.cfg
        """
        self.base_path = base_path
        paths_config = get_config_loader().get_paths_config()
        self.project_root = (base_path / paths_config.get('project_root', '../..')).resolve()
        self.build_dir = self.project_root / "build"
        self.cache_dir = base_path / "cache" / "build"
        self.node_source_config = node_source_config or {}
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("build_manager_initialized",
                   project_root=str(self.project_root),
                   node_source_type=self.node_source_config.get("type", "url"))
    
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
        
        print_info(_("Building cellframe-node ({} mode)").format(build_type))
        
        try:
            # Clean if requested
            if clean and self.build_dir.exists():
                logger.info("cleaning_build_dir")
                print_info(_("Cleaning build directory..."))
                import shutil
                shutil.rmtree(self.build_dir)
            
            # Create build directory
            self.build_dir.mkdir(parents=True, exist_ok=True)
            
            # Configure with CMake
            cmake_build_type = "Debug" if build_type == "debug" else "Release"
            
            print_info(_("Configuring with CMake..."))
            run_command(
                ["cmake", 
                 f"-DCMAKE_BUILD_TYPE={cmake_build_type}",
                 ".."],
                cwd=self.build_dir,
            )
            
            # Build
            jobs = parallel if parallel > 0 else self._get_cpu_count()
            
            print_info(_("Building with {} parallel jobs...").format(jobs))
            run_command(
                ["cmake", "--build", ".", "--", f"-j{jobs}"],
                cwd=self.build_dir,
            )
            
            # Find artifacts
            artifacts = self._find_artifacts()
            
            duration = time.time() - start_time
            
            print_success(_("Build completed in {}s").format(f"{duration:.1f}"))
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
            
            print_error(_("Build failed: {}").format(e))
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
            print_info(_("Removing build directory..."))
            shutil.rmtree(self.build_dir)
        
        if self.cache_dir.exists():
            print_info(_("Removing build cache..."))
            shutil.rmtree(self.cache_dir)
        
        print_success(_("Build artifacts cleaned"))
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
    
    def get_node_package(self) -> Optional[Path]:
        """
        Get cellframe-node package based on node_source configuration.
        
        Returns:
            Path to .deb package or None if failed
        """
        source_type = self.node_source_config.get("type", "url")
        
        logger.info("getting_node_package", source_type=source_type)
        print_info(_("Getting cellframe-node package (source: {})").format(source_type))
        
        try:
            if source_type == "url":
                return self._get_package_from_url()
            elif source_type == "repository":
                return self._get_package_from_repository()
            elif source_type == "local":
                return self._get_package_from_local()
            else:
                print_error(_("Unknown node_source type: {}").format(source_type))
                logger.error("unknown_source_type", type=source_type)
                return None
        except Exception as e:
            print_error(_("Failed to get node package: {}").format(e))
            logger.error("get_node_package_failed", error=str(e))
            return None
    
    def _get_package_from_url(self) -> Optional[Path]:
        """
        Download cellframe-node package from URL.
        
        Returns:
            Path to downloaded .deb package
        """
        url = self.node_source_config.get("url")
        if not url:
            print_error(_("No URL specified in node_source config"))
            return None
        
        print_info(_("Downloading from: {}").format(url))
        logger.info("downloading_from_url", url=url)
        
        # Download to cache
        package_name = "cellframe-node-latest.deb"
        package_path = self.cache_dir / package_name
        
        try:
            run_command(["wget", "-O", str(package_path), url])
            print_success(_("Downloaded: {}").format(package_name))
            return package_path
        except Exception as e:
            print_error(_("Download failed: {}").format(e))
            return None
    
    def _get_package_from_repository(self) -> Optional[Path]:
        """
        Clone repository, build, and create .deb package.
        
        Returns:
            Path to built .deb package
        """
        repo_url = self.node_source_config.get("repository_url")
        branch = self.node_source_config.get("repository_branch", "master")
        build_type = self.node_source_config.get("build_type", "debug")
        
        if not repo_url:
            print_error(_("No repository_url specified in node_source config"))
            return None
        
        print_info(_("Cloning repository: {} (branch: {})").format(repo_url, branch))
        logger.info("cloning_repository", url=repo_url, branch=branch)
        
        # Clone directory
        clone_dir = self.cache_dir / "cellframe-node-repo"
        
        # Remove if exists
        if clone_dir.exists():
            print_info(_("Removing existing clone..."))
            shutil.rmtree(clone_dir)
        
        try:
            # Clone
            run_command(["git", "clone", "--depth", "1", "-b", branch, repo_url, str(clone_dir)])
            
            # Build
            build_dir = clone_dir / "build"
            build_dir.mkdir(exist_ok=True)
            
            cmake_build_type = "Debug" if build_type == "debug" else "Release"
            
            print_info(_("Configuring with CMake..."))
            run_command(
                ["cmake", f"-DCMAKE_BUILD_TYPE={cmake_build_type}", ".."],
                cwd=build_dir
            )
            
            jobs = self._get_cpu_count()
            print_info(_("Building with {} parallel jobs...").format(jobs))
            run_command(["cmake", "--build", ".", "--", f"-j{jobs}"], cwd=build_dir)
            
            # Package
            print_info(_("Creating .deb package..."))
            run_command(["cpack", "-G", "DEB"], cwd=build_dir)
            
            # Find .deb package
            deb_files = list(build_dir.glob("*.deb"))
            if not deb_files:
                print_error(_("No .deb package found after build"))
                return None
            
            package_path = deb_files[0]
            
            # Copy to cache root for easier access
            cached_package = self.cache_dir / package_path.name
            shutil.copy2(package_path, cached_package)
            
            print_success(_("Package created: {}").format(cached_package.name))
            return cached_package
            
        except Exception as e:
            print_error(_("Repository build failed: {}").format(e))
            logger.error("repository_build_failed", error=str(e))
            return None
    
    def _get_package_from_local(self) -> Optional[Path]:
        """
        Get cellframe-node package from local file.
        
        Returns:
            Path to local .deb package
        """
        local_path = self.node_source_config.get("local_path")
        if not local_path:
            # Try to auto-detect if we're in cellframe-node repository
            if self._is_cellframe_node_repo():
                print_info(_("No local_path specified, but detected cellframe-node repository"))
                print_info(_("Attempting to build package automatically..."))
                return self._build_and_get_local_package()
            else:
                print_error(_("No local_path specified in node_source config"))
                return None
        
        # Resolve path (can be relative to stage-env dir or absolute)
        package_path = Path(local_path)
        if not package_path.is_absolute():
            package_path = self.base_path / local_path
        
        package_path = package_path.resolve()
        
        # If package doesn't exist and we're in cellframe-node repo, try to build it
        if not package_path.exists():
            if self._is_cellframe_node_repo() and self.build_dir in package_path.parents:
                print_info(_("Package not found at {}").format(package_path))
                print_info(_("Detected cellframe-node repository - building package..."))
                built_package = self._build_and_get_local_package()
                if built_package:
                    # Update local_path to point to built package
                    logger.info("auto_built_package", 
                              requested=str(package_path),
                              built=str(built_package))
                    return built_package
            else:
                print_error(_("Local package not found: {}").format(package_path))
                logger.error("local_package_not_found", path=str(package_path))
                return None
        
        if not package_path.suffix == ".deb":
            print_error(_("Local file is not a .deb package: {}").format(package_path))
            return None
        
        print_success(_("Using local package: {}").format(package_path.name))
        logger.info("using_local_package", path=str(package_path))
        
        return package_path
    
    def _is_cellframe_node_repo(self) -> bool:
        """Check if we're running in cellframe-node repository."""
        cmake_file = self.project_root / "CMakeLists.txt"
        if not cmake_file.exists():
            return False
        
        try:
            with open(cmake_file, 'r') as f:
                content = f.read()
                return "cellframe-node" in content
        except Exception:
            return False
    
    def _build_and_get_local_package(self) -> Optional[Path]:
        """
        Build cellframe-node package from source and return path to .deb file.
        
        Returns:
            Path to built .deb package or None if build failed
        """
        if not self._is_cellframe_node_repo():
            print_error(_("Not in cellframe-node repository - cannot build package"))
            return None
        
        # Check if package already exists
        existing_packages = list(self.build_dir.glob("cellframe-node*.deb"))
        if existing_packages:
            package_path = existing_packages[0]
            print_info(_("Using existing package: {}").format(package_path.name))
            logger.info("using_existing_built_package", path=str(package_path))
            return package_path
        
        # Build package
        print_info(_("Building cellframe-node package..."))
        logger.info("auto_building_package", build_dir=str(self.build_dir))
        
        try:
            build_result = self.build(build_type="debug", clean=False, parallel=0)
            if not build_result.success:
                print_error(_("Package build failed"))
                return None
            
            # Package with cpack
            print_info(_("Creating .deb package..."))
            run_command(["cpack", "-G", "DEB"], cwd=self.build_dir)
            
            # Find the built package
            deb_files = list(self.build_dir.glob("cellframe-node*.deb"))
            if not deb_files:
                print_error(_("No .deb package found after build"))
                logger.error("no_package_after_build", build_dir=str(self.build_dir))
                return None
            
            package_path = deb_files[0]
            print_success(_("Package built: {}").format(package_path.name))
            logger.info("package_built_successfully", path=str(package_path))
            
            return package_path
            
        except Exception as e:
            print_error(_("Failed to build package: {}").format(e))
            logger.error("package_build_failed", error=str(e))
            return None

