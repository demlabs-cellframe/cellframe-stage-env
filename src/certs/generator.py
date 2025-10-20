"""
Certificate generator for test network.

Python wrapper around C certificate generator utility.
Handles generation of:
- Node certificates
- Validator certificates  
- CA certificates
"""

from pathlib import Path
from typing import List, Optional
import json

from pydantic import BaseModel

from ..utils.logger import get_logger
from ..utils.cli import run_command, print_info, print_success

logger = get_logger(__name__)


class CertConfig(BaseModel):
    """Certificate configuration."""
    
    name: str
    type: str  # node, validator, ca
    output_dir: Path


class CertGenerator:
    """Generate certificates for test network."""
    
    def __init__(self, base_path: Path):
        """
        Initialize certificate generator.
        
        Args:
            base_path: Base path to stage-env directory
        """
        self.base_path = base_path
        self.certs_dir = base_path / "cache" / "certs"
        self.cert_tool = base_path / "src" / "certs" / "cert-generator"
        
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("cert_generator_initialized",
                   certs_dir=str(self.certs_dir))
    
    def build_cert_tool(self) -> bool:
        """
        Build certificate generator C utility if needed.
        
        Returns:
            True if tool is ready
        """
        if self.cert_tool.exists():
            logger.debug("cert_tool_exists")
            return True
        
        logger.info("building_cert_tool")
        print_info("Building certificate generator...")
        
        try:
            # Build with CMake
            build_dir = self.base_path / "src" / "certs" / "build"
            build_dir.mkdir(parents=True, exist_ok=True)
            
            run_command(
                ["cmake", ".."],
                cwd=build_dir,
            )
            
            run_command(
                ["cmake", "--build", "."],
                cwd=build_dir,
            )
            
            # Copy to src/certs/
            import shutil
            cert_gen = build_dir / "cert-generator"
            if cert_gen.exists():
                shutil.copy(cert_gen, self.cert_tool)
                self.cert_tool.chmod(0o755)
            
            print_success("Certificate tool built")
            logger.info("cert_tool_built")
            return True
            
        except Exception as e:
            logger.error("cert_tool_build_failed", error=str(e))
            return False
    
    def generate_node_cert(
        self,
        node_id: int,
        node_name: str,
        output_dir: Optional[Path] = None,
    ) -> Path:
        """
        Generate certificate for a node.
        
        Args:
            node_id: Node ID
            node_name: Node name
            output_dir: Output directory (default: cache/certs/nodeN)
            
        Returns:
            Path to generated certificate
        """
        if output_dir is None:
            output_dir = self.certs_dir / f"node{node_id}"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cert_file = output_dir / "node-addr.dcert"
        
        logger.info("generating_node_cert",
                   node_id=node_id,
                   node_name=node_name)
        
        # Use cert tool to generate
        # For now, use Python fallback for simple cert generation
        self._generate_simple_cert(
            name=node_name,
            cert_type="node",
            output_file=cert_file,
        )
        
        logger.info("node_cert_generated",
                   node_id=node_id,
                   path=str(cert_file))
        
        return cert_file
    
    def generate_validator_certs(
        self,
        prefix: str,
        count: int,
        output_dir: Optional[Path] = None,
    ) -> List[Path]:
        """
        Generate validator certificates.
        
        Args:
            prefix: Certificate prefix (e.g., "stagenet.master")
            count: Number of certificates to generate
            output_dir: Output directory
            
        Returns:
            List of paths to generated certificates
        """
        if output_dir is None:
            output_dir = self.certs_dir
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("generating_validator_certs",
                   prefix=prefix,
                   count=count)
        
        certs = []
        
        for i in range(count):
            cert_name = f"{prefix}.{i}"
            cert_file = output_dir / f"{cert_name}.dcert"
            
            self._generate_simple_cert(
                name=cert_name,
                cert_type="validator",
                output_file=cert_file,
            )
            
            certs.append(cert_file)
        
        logger.info("validator_certs_generated", count=len(certs))
        
        return certs
    
    def generate_all(
        self,
        network_name: str,
        node_count: int,
        validator_count: int = 3,
    ) -> dict:
        """
        Generate all certificates for network.
        
        Args:
            network_name: Network name (e.g., "stagenet")
            node_count: Number of nodes
            validator_count: Number of validators
            
        Returns:
            Dict with generated certificate paths
        """
        logger.info("generating_all_certificates",
                   network=network_name,
                   nodes=node_count,
                   validators=validator_count)
        
        print_info(f"Generating certificates for {node_count} nodes...")
        
        result = {
            "nodes": [],
            "validators": [],
        }
        
        # Generate node certificates
        for i in range(1, node_count + 1):
            cert = self.generate_node_cert(
                node_id=i,
                node_name=f"{network_name}-node{i}",
            )
            result["nodes"].append(str(cert))
        
        # Generate validator certificates
        validator_prefix = f"{network_name}.master"
        certs = self.generate_validator_certs(
            prefix=validator_prefix,
            count=validator_count,
        )
        result["validators"] = [str(c) for c in certs]
        
        # Save PKI config
        pki_config = {
            "network": network_name,
            "node_count": node_count,
            "validator_count": validator_count,
            "generated_at": self._get_timestamp(),
        }
        
        pki_config_file = self.certs_dir / "pki-config.json"
        with open(pki_config_file, "w") as f:
            json.dump(pki_config, f, indent=2)
        
        print_success(f"Generated {node_count} node + {validator_count} validator certificates")
        logger.info("all_certificates_generated",
                   total=node_count + validator_count)
        
        return result
    
    def _generate_simple_cert(
        self,
        name: str,
        cert_type: str,
        output_file: Path,
    ) -> None:
        """
        Generate simple certificate (fallback method).
        
        Args:
            name: Certificate name
            cert_type: Certificate type
            output_file: Output file path
        """
        # Simple placeholder implementation
        # In production, this would call the C utility or use proper crypto
        
        cert_data = {
            "name": name,
            "type": cert_type,
            "version": "1.0",
            "created": self._get_timestamp(),
        }
        
        with open(output_file, "w") as f:
            json.dump(cert_data, f, indent=2)
        
        logger.debug("simple_cert_generated",
                    name=name,
                    type=cert_type,
                    file=str(output_file))
    
    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"
    
    def certs_exist(self) -> bool:
        """
        Check if certificates exist.
        
        Returns:
            True if certificate directory has content
        """
        if not self.certs_dir.exists():
            return False
        
        # Check for PKI config
        pki_config = self.certs_dir / "pki-config.json"
        if not pki_config.exists():
            return False
        
        # Check for at least one cert
        certs = list(self.certs_dir.rglob("*.dcert"))
        
        return len(certs) > 0
    
    def clean(self) -> None:
        """Remove all generated certificates."""
        logger.info("cleaning_certificates")
        
        import shutil
        
        if self.certs_dir.exists():
            print_info("Removing certificates...")
            shutil.rmtree(self.certs_dir)
            self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        print_success("Certificates cleaned")
        logger.info("certificates_cleaned")

