"""Mirror speed tester for Debian and Docker registries.

Tests multiple mirrors and selects the fastest one for Docker builds.
All mirrors are tested in parallel for maximum speed.
"""

import time
import subprocess
import shutil
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

from .logger import get_logger

logger = get_logger(__name__)


def _check_dependencies() -> bool:
    """Check if required tools (curl) are available."""
    return shutil.which("curl") is not None


# Debian Trixie mirrors (testing)
DEBIAN_MIRRORS = [
    # Official Debian CDN (fastest globally, uses geo-routing)
    "http://deb.debian.org/debian",
    
    # Russian mirrors
    "http://mirror.yandex.ru/debian",  # Yandex (Moscow, good CDN)
    "http://ftp.ru.debian.org/debian",  # Official Russian mirror (Moscow)
    "http://mirror.truenetwork.ru/debian",  # TrueNetwork (Moscow)
    "http://mirror.1h.ru/debian",  # 1H.ru mirror (Moscow)
    "http://mirror.timeweb.ru/debian",  # Timeweb (Moscow)
    # "http://mirror.beget.ru/debian",  # Beget (Moscow) - disabled: doesn't have Trixie
    "http://debian.volia.net/debian",  # Volia (Ukraine, but good connectivity to Russia)
    
    # CIS mirrors (good connectivity from Siberia)
    "http://ftp.by.debian.org/debian",  # Belarus (Minsk)
    "http://mirror.datacenter.by/debian",  # Belarus datacenter
    
    # European mirrors (backup options)
    "http://mirror.telepoint.bg/debian",  # Bulgaria
    "http://ftp.de.debian.org/debian",  # Germany (fast European mirror)
    "http://mirror.nl.leaseweb.net/debian",  # Netherlands (Leaseweb, good speed)
    
    # South American mirrors 
    "http://mirror.sitsa.com.ar/debian",  # SiTSA (Villa María, Córdoba, Argentina)
    "http://debian.unnoba.edu.ar/debian",  # UNNOBA University (Argentina)
    "http://ftp.unlp.edu.ar/debian",  # UNLP University (La Plata, Argentina, near Buenos Aires)
    "http://mirror.fcaglp.unlp.edu.ar/debian",  # FCAGLP UNLP (La Plata, Argentina)
    "http://ftp.br.debian.org/debian",  # Official Brazilian mirror (São Paulo, Brazil)
    "http://debian.c3sl.ufpr.br/debian",  # UFPR (Curitiba, Brazil)
    "http://mirror.ufscar.br/debian",  # UFSCar (São Carlos, Brazil)
]

# Docker registry mirrors (for pulling base images)
# Note: Docker registry mirrors require daemon.json configuration
# These are tested for availability, but actual mirror setup is done via daemon.json
DOCKER_REGISTRIES = [
    "docker.io",  # Official Docker Hub
    # Russian mirrors
    "dh-mirror.gitverse.ru",  # GitVerse/Sber mirror (Russia)
    "dockerhub.timeweb.cloud",  # Timeweb mirror (Russia)
    "dockerhub1.beget.com",  # Beget mirror (Russia)
    # International alternatives
    "mirror.gcr.io",  # Google Container Registry mirror
    "ghcr.io",  # GitHub Container Registry
    "quay.io",  # Red Hat Quay
    "public.ecr.aws",  # Amazon ECR Public
    # South American options (AWS/GCP have South American regions)
    # Note: AWS ECR and GCR use geo-routing, so they should route to nearest region
    # For Argentina/Buenos Aires, AWS has sa-east-1 (São Paulo) which is closest
]


class MirrorTester:
    """Test mirror speeds and select the fastest one."""
    
    def __init__(self, timeout: int = 5):
        """
        Initialize mirror tester.
        
        Args:
            timeout: Timeout in seconds for each test
        """
        self.timeout = timeout
    
    async def test_debian_mirror(self, mirror_url: str) -> Tuple[str, Optional[float]]:
        """
        Test Debian mirror speed by downloading a small file (async).
        
        Args:
            mirror_url: Mirror URL (e.g., http://deb.debian.org/debian)
            
        Returns:
            Tuple of (mirror_url, download_time_in_seconds) or (mirror_url, None) if failed
        """
        if not _check_dependencies():
            logger.warning("curl_not_available", using_default=mirror_url)
            return (mirror_url, None)
        
        try:
            # Test with a small file from the mirror
            # Use Release file which is small and always available
            test_url = f"{mirror_url}/dists/trixie/Release"
            
            start_time = time.time()
            process = await asyncio.create_subprocess_exec(
                "curl", "-s", "-o", "/dev/null", "-w", "%{time_total}",
                "--max-time", str(self.timeout), test_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout + 1
                )
                elapsed = time.time() - start_time
                
                if process.returncode == 0:
                    try:
                        # Try to parse curl output
                        curl_time = float(stdout.decode().strip())
                        return (mirror_url, min(curl_time, elapsed))
                    except ValueError:
                        return (mirror_url, elapsed)
                else:
                    return (mirror_url, None)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return (mirror_url, None)
        except Exception as e:
            logger.debug("mirror_test_failed", mirror=mirror_url, error=str(e))
            return (mirror_url, None)
    
    async def test_docker_registry(self, registry: str) -> Tuple[str, Optional[float]]:
        """
        Test Docker registry speed by checking API availability (async).
        
        Note: Docker registry mirrors require daemon.json configuration.
        This method tests HTTP API availability, not actual image pull.
        
        Args:
            registry: Registry name (e.g., docker.io, dh-mirror.gitverse.ru)
            
        Returns:
            Tuple of (registry_name, response_time_in_seconds) or (registry_name, None) if failed
        """
        if not _check_dependencies():
            logger.warning("curl_not_available", registry=registry)
            return (registry, None)
        
        try:
            # Test registry v2 API availability
            # For Docker Hub mirrors, test the v2 API endpoint
            if registry == "docker.io":
                test_url = "https://registry-1.docker.io/v2/"
            elif registry.startswith("dh-mirror") or registry.startswith("dockerhub"):
                # Docker Hub mirrors use https://
                test_url = f"https://{registry}/v2/"
            elif registry in ["ghcr.io", "quay.io", "public.ecr.aws"]:
                # These are alternative registries, not mirrors
                test_url = f"https://{registry}/v2/"
            else:
                test_url = f"https://{registry}/v2/"
            
            start_time = time.time()
            process = await asyncio.create_subprocess_exec(
                "curl", "-s", "-o", "/dev/null", "-w", "%{time_total}",
                "--max-time", str(self.timeout),
                "-H", "Accept: application/vnd.docker.distribution.manifest.v2+json",
                test_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout + 1
                )
                elapsed = time.time() - start_time
                
                if process.returncode == 0:
                    try:
                        curl_time = float(stdout.decode().strip())
                        return (registry, min(curl_time, elapsed))
                    except ValueError:
                        return (registry, elapsed)
                else:
                    return (registry, None)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return (registry, None)
        except Exception as e:
            logger.debug("docker_registry_test_failed", registry=registry, error=str(e))
            return (registry, None)
    
    async def find_fastest_debian_mirror(self) -> Tuple[str, float]:
        """
        Test all Debian mirrors in parallel and return the fastest one.
        
        Returns:
            Tuple of (mirror_url, time_in_seconds)
        """
        logger.info("testing_debian_mirrors_parallel", count=len(DEBIAN_MIRRORS))
        
        # Test all mirrors in parallel
        tasks = [self.test_debian_mirror(mirror) for mirror in DEBIAN_MIRRORS]
        test_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        results: List[Tuple[str, float]] = []
        
        for result in test_results:
            if isinstance(result, Exception):
                logger.debug("mirror_test_exception", error=str(result))
                continue
            
            mirror_url, time_taken = result
            if time_taken is not None:
                results.append((mirror_url, time_taken))
                logger.info("mirror_test_result", mirror=mirror_url, time=f"{time_taken:.2f}s")
            else:
                logger.warning("mirror_test_failed", mirror=mirror_url)
        
        if not results:
            logger.warning("no_working_mirrors_found", using_default=DEBIAN_MIRRORS[0])
            return DEBIAN_MIRRORS[0], float('inf')
        
        # Sort by time (fastest first)
        results.sort(key=lambda x: x[1])
        fastest = results[0]
        
        logger.info("fastest_debian_mirror", 
                   mirror=fastest[0], 
                   time=f"{fastest[1]:.2f}s")
        
        return fastest
    
    async def find_fastest_docker_registry(self) -> Tuple[str, float]:
        """
        Test all Docker registries in parallel and return the fastest one.
        
        Note: Docker registry mirrors require daemon.json configuration.
        This tests API availability, not actual image pull performance.
        
        Returns:
            Tuple of (registry_name, time_in_seconds)
        """
        logger.info("testing_docker_registries_parallel", count=len(DOCKER_REGISTRIES))
        
        # Test all registries in parallel
        tasks = [self.test_docker_registry(registry) for registry in DOCKER_REGISTRIES]
        test_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        results: List[Tuple[str, float]] = []
        
        for result in test_results:
            if isinstance(result, Exception):
                logger.debug("registry_test_exception", error=str(result))
                continue
            
            registry, time_taken = result
            if time_taken is not None:
                results.append((registry, time_taken))
                logger.info("registry_test_result", registry=registry, time=f"{time_taken:.2f}s")
            else:
                logger.warning("registry_test_failed", registry=registry)
        
        if not results:
            logger.warning("no_working_registries_found", using_default=DOCKER_REGISTRIES[0])
            return DOCKER_REGISTRIES[0], float('inf')
        
        # Sort by time (fastest first)
        results.sort(key=lambda x: x[1])
        fastest = results[0]
        
        logger.info("fastest_docker_registry", 
                   registry=fastest[0], 
                   time=f"{fastest[1]:.2f}s")
        
        return fastest
    
    def get_debian_mirror_for_dockerfile(self, mirror_url: str) -> str:
        """
        Convert mirror URL to Dockerfile format.
        
        Args:
            mirror_url: Full mirror URL
            
        Returns:
            Mirror URL in format suitable for Dockerfile
        """
        # Remove trailing slash
        mirror_url = mirror_url.rstrip('/')
        
        # For Debian, we need to set it in sources.list
        # Return the base URL
        return mirror_url


async def _select_fastest_mirrors_async(timeout: int = 5, test_docker: bool = True) -> Dict[str, Any]:
    """
    Select fastest mirrors for Debian and Docker in parallel (async).
    
    Args:
        timeout: Timeout in seconds for each test
        test_docker: Whether to test Docker registries (default: True)
        
    Returns:
        Dict with 'debian_mirror', 'debian_time', and optionally 'docker_registry', 'docker_time'
    """
    tester = MirrorTester(timeout=timeout)
    
    # Test both Debian mirrors and Docker registries in parallel
    tasks = [tester.find_fastest_debian_mirror()]
    if test_docker:
        tasks.append(tester.find_fastest_docker_registry())
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process Debian mirror result
    debian_result = results[0]
    if isinstance(debian_result, Exception):
        logger.error("debian_mirror_test_failed", error=str(debian_result))
        debian_mirror, debian_time = DEBIAN_MIRRORS[0], float('inf')
    else:
        debian_mirror, debian_time = debian_result
    
    result = {
        'debian_mirror': debian_mirror,
        'debian_time': debian_time,
    }
    
    # Process Docker registry result if requested
    if test_docker and len(results) > 1:
        docker_result = results[1]
        if isinstance(docker_result, Exception):
            logger.error("docker_registry_test_failed", error=str(docker_result))
            docker_registry, docker_time = DOCKER_REGISTRIES[0], float('inf')
        else:
            docker_registry, docker_time = docker_result
        
        result['docker_registry'] = docker_registry
        result['docker_time'] = docker_time
        result['docker_mirror_url'] = f"https://{docker_registry}" if not docker_registry.startswith("http") else docker_registry
    
    return result


def select_fastest_mirrors(timeout: int = 5, test_docker: bool = True) -> Dict[str, Any]:
    """
    Select fastest mirrors for Debian and Docker in parallel.
    
    This is a synchronous wrapper around the async implementation.
    All mirrors (both Debian and Docker) are tested simultaneously for maximum speed.
    
    Args:
        timeout: Timeout in seconds for each test
        test_docker: Whether to test Docker registries (default: True)
        
    Returns:
        Dict with 'debian_mirror', 'debian_time', and optionally 'docker_registry', 'docker_time'
    """
    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a new one in a thread
            import concurrent.futures
            def run_async():
                return asyncio.run(_select_fastest_mirrors_async(timeout, test_docker))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async)
                return future.result()
        else:
            return loop.run_until_complete(_select_fastest_mirrors_async(timeout, test_docker))
    except RuntimeError:
        # No event loop, create a new one
        return asyncio.run(_select_fastest_mirrors_async(timeout, test_docker))

