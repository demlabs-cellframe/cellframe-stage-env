"""
Utility functions for snapshot system.
"""

import hashlib
import json
import subprocess
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def calculate_topology_hash(topology_config: Dict[str, Any]) -> str:
    """
    Calculate SHA256 hash of topology configuration.
    
    Includes: node_count, roles, consensus, chain configs
    Excludes: timestamps, runtime IPs/ports, temporary settings
    
    Args:
        topology_config: Topology configuration dictionary
        
    Returns:
        SHA256 hash as hex string
    """
    # Extract only stable topology properties
    stable_config = {
        'node_count': topology_config.get('node_count'),
        'nodes': [
            {
                'role': node.get('role'),
                'consensus': node.get('consensus'),
            }
            for node in topology_config.get('nodes', [])
        ],
        'network_type': topology_config.get('network_type'),
        'chain_type': topology_config.get('chain_type'),
    }
    
    # Normalize to JSON string and calculate hash
    normalized = json.dumps(stable_config, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def calculate_file_checksum(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.
    
    Args:
        file_path: Path to file
        
    Returns:
        SHA256 checksum as hex string
    """
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def run_command(cmd: list, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
    """
    Run shell command with logging.
    
    Args:
        cmd: Command and arguments as list
        check: Raise exception on non-zero exit
        capture_output: Capture stdout/stderr
        
    Returns:
        CompletedProcess instance
    """
    logger.debug(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True
        )
        
        if result.stdout:
            logger.debug(f"Command output: {result.stdout}")
        
        return result
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(cmd)}")
        logger.error(f"Exit code: {e.returncode}")
        if e.stdout:
            logger.error(f"Stdout: {e.stdout}")
        if e.stderr:
            logger.error(f"Stderr: {e.stderr}")
        raise


def check_squashfs_tools() -> bool:
    """
    Check if squashfs-tools are available.
    
    Returns:
        True if mksquashfs and unsquashfs are available
    """
    try:
        run_command(['which', 'mksquashfs'], check=True)
        run_command(['which', 'unsquashfs'], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def check_overlayfs_support() -> bool:
    """
    Check if OverlayFS is supported.
    
    Returns:
        True if overlay filesystem is available
    """
    try:
        # Check if overlay module is loaded or available
        result = run_command(['modinfo', 'overlay'], check=False)
        return result.returncode == 0
    except Exception:
        return False


def get_cellframe_version(package_path: Optional[Path] = None) -> str:
    """
    Get cellframe-node version from package or installed system.
    
    Args:
        package_path: Optional path to .deb package
        
    Returns:
        Version string (e.g., "5.4-28")
    """
    if package_path and package_path.exists():
        # Extract version from .deb filename
        # Expected format: cellframe-node_5.4-28_amd64.deb
        name = package_path.stem
        parts = name.split('_')
        if len(parts) >= 2:
            return parts[1]
    
    # Try to get from installed package
    try:
        result = run_command(['dpkg', '-l', 'cellframe-node'], check=False)
        if result.returncode == 0:
            # Parse dpkg output
            for line in result.stdout.split('\n'):
                if 'cellframe-node' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
    except Exception:
        pass
    
    return 'unknown'


def format_size(size_bytes: int) -> str:
    """
    Format size in bytes to human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "60 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def is_snapshot_expired(created_time: str, max_age_days: int = 30) -> bool:
    """
    Check if snapshot is expired based on creation time.
    
    Args:
        created_time: ISO timestamp string
        max_age_days: Maximum age in days (default: 30)
        
    Returns:
        True if snapshot is older than max_age_days
    """
    try:
        created = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
        age = datetime.now(created.tzinfo) - created
        return age > timedelta(days=max_age_days)
    except Exception as e:
        logger.warning(f"Failed to parse timestamp {created_time}: {e}")
        return False


def load_metadata(metadata_path: Path) -> Optional[Dict[str, Any]]:
    """
    Load snapshot metadata from JSON file.
    
    Args:
        metadata_path: Path to .json metadata file
        
    Returns:
        Metadata dictionary or None if file doesn't exist
    """
    if not metadata_path.exists():
        return None
    
    try:
        with open(metadata_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load metadata from {metadata_path}: {e}")
        return None


def save_metadata(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """
    Save snapshot metadata to JSON file.
    
    Args:
        metadata_path: Path to .json metadata file
        metadata: Metadata dictionary
    """
    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.debug(f"Saved metadata to {metadata_path}")
    except Exception as e:
        logger.error(f"Failed to save metadata to {metadata_path}: {e}")
        raise

