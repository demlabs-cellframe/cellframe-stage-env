"""
Certificate generator for test network.

Python wrapper around C certificate generator utility running in Docker.
Handles generation of:
- Node certificates
- Validator certificates  
- CA certificates

Uses cf-cert-generator utility in Docker container for cross-platform compatibility.
This utility generates proper binary DAP certificates using DAP SDK crypto.
"""

from pathlib import Path
from typing import List, Optional
import json
import re
import subprocess
import shutil
import os

from pydantic import BaseModel

from src.utils.logger import get_logger
from src.utils.cli import run_command, print_info, print_success, print_error
from src.utils.i18n import _

logger = get_logger(__name__)

CERT_BUILDER_IMAGE = "cf-tools:latest"


class CertConfig(BaseModel):
    """Certificate configuration."""
    
    name: str
    type: str  # node, validator, ca
    output_dir: Path


class CertGenerator:
    """Generate certificates for test network."""
    
    def __init__(self, base_path: Path, certs_dir: Optional[Path] = None,
                 dap_sdk_branch: Optional[str] = None):
        """
        Initialize certificate generator.
        
        Args:
            base_path: Base path to stage-env directory
            certs_dir: Optional path to certificates directory (defaults to base_path/cache/certs)
            dap_sdk_branch: Git branch of dap-sdk to build tools against
                           (e.g. "release-5.8", "release-6.0").
                           Defaults to "release-6.0".
        """
        self.base_path = base_path
        self.certs_dir = certs_dir if certs_dir is not None else (base_path / "cache" / "certs")
        self.dockerfile = base_path / "Dockerfile.tools"
        self.project_root = base_path.parent.parent
        self.dap_sdk_branch = dap_sdk_branch or "release-6.0"
        
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("cert_generator_initialized",
                   certs_dir=str(self.certs_dir),
                   dap_sdk_branch=self.dap_sdk_branch,
                   docker_mode=True)
    
    def _image_needs_rebuild(self) -> bool:
        """Check if the Docker image is older than local source files or SDK branch changed."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.Created}}||{{index .Config.Labels \"dap.sdk.branch\"}}",
                 CERT_BUILDER_IMAGE],
                capture_output=True, text=True, check=True,
            )
            parts = result.stdout.strip().split("||", 1)
            created_raw = parts[0]
            image_branch = parts[1] if len(parts) > 1 else ""

            if image_branch != self.dap_sdk_branch:
                logger.info("cert_builder_sdk_branch_changed",
                            image_branch=image_branch,
                            desired_branch=self.dap_sdk_branch)
                return True

            from datetime import datetime, timezone
            created_str = created_raw.split(".")[0]
            image_ts = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc
            )

            mtimes: list[float] = []
            for subdir in ("src/certs", "src/gdb"):
                src_dir = self.base_path / subdir
                if src_dir.exists():
                    mtimes.extend(
                        f.stat().st_mtime for f in src_dir.iterdir() if f.is_file()
                    )
            if self.dockerfile.exists():
                mtimes.append(self.dockerfile.stat().st_mtime)
            if not mtimes:
                return False
            max_mtime = max(mtimes)
            src_ts = datetime.fromtimestamp(max_mtime, tz=timezone.utc)

            if src_ts > image_ts:
                logger.info("cert_builder_image_stale",
                            image_created=image_ts.isoformat(),
                            source_modified=src_ts.isoformat())
                return True
            return False
        except Exception:
            return False

    def build_docker_image(self) -> bool:
        """
        Build the cf-tools Docker image if needed.

        The image clones dap-sdk from remote (branch = ``self.dap_sdk_branch``)
        and builds cf-cert-generator + dap-gdb-tool.  Tool sources are COPY'd
        from the project tree; the SDK is NOT copied — it's always cloned fresh.

        Automatically rebuilds when local source files in ``src/certs/`` or
        ``src/gdb/`` are newer than the existing Docker image.

        Returns:
            True if image is ready
        """
        try:
            result = subprocess.run(
                ["docker", "images", "-q", CERT_BUILDER_IMAGE],
                capture_output=True, text=True, check=True,
            )
            if result.stdout.strip() and not self._image_needs_rebuild():
                logger.debug("cert_builder_image_exists")
                return True
            if result.stdout.strip():
                print_info(_("Certificate builder sources changed, rebuilding image..."))
        except subprocess.CalledProcessError:
            pass

        logger.info("building_cert_builder_image",
                    dap_sdk_branch=self.dap_sdk_branch)
        print_info(_("Building cf-tools image (SDK branch: {})...").format(
            self.dap_sdk_branch))

        try:
            result = subprocess.run(
                [
                    "docker", "build",
                    "-f", str(self.dockerfile),
                    "--build-arg", f"DAP_SDK_BRANCH={self.dap_sdk_branch}",
                    "-t", CERT_BUILDER_IMAGE,
                    str(self.project_root),
                ],
                capture_output=True, text=True,
            )

            if result.returncode != 0:
                logger.error("builder_image_build_failed",
                             stderr=result.stderr, stdout=result.stdout)
                print_error(_("Failed to build builder image: {}").format(result.stderr))
                return False

            print_success(_("cf-tools image built (SDK: {})").format(
                self.dap_sdk_branch))
            logger.info("cert_builder_image_built",
                        dap_sdk_branch=self.dap_sdk_branch)
            return True

        except Exception as e:
            logger.error("builder_image_build_exception", error=str(e))
            print_error(_("Exception building builder image: {}").format(e))
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
        root_count: int = 2,
        network_id: str = "0x0000000000001234",
    ) -> dict:
        """
        Generate all certificates for network using Docker-based cf-cert-generator.
        
        Args:
            network_name: Network name (e.g., "stagenet")
            node_count: Total number of nodes
            root_count: Number of ROOT nodes (rest will be MASTER)
            network_id: Network ID hex string
            
        Returns:
            Dict with generated certificate paths
        """
        logger.info("generating_all_certificates",
                   network=network_name,
                   nodes=node_count,
                   root_count=root_count,
                   method="docker_self_contained")

        print_info(_("Generating {} node certificates (self-contained Docker)...").format(node_count))

        if not self.build_docker_image():
            raise RuntimeError("Failed to build certificate builder Docker image")
        self.certs_dir.mkdir(parents=True, exist_ok=True)

        uid, gid = os.getuid(), os.getgid()

        docker_cmd = [
            "docker", "run", "--rm",
            "--entrypoint", "sh",
            "-v", f"{self.certs_dir.absolute()}:/output",
            CERT_BUILDER_IMAGE,
            "-c",
            f"/usr/local/bin/cf-cert-generator /output {node_count} {network_name} {network_id} {root_count} && "
            f"chown -R {uid}:{gid} /output",
        ]

        try:
            logger.info("calling_docker_cert_generator",
                       image=CERT_BUILDER_IMAGE,
                       output_dir=str(self.certs_dir),
                       node_count=node_count,
                       network_name=network_name,
                       network_id=network_id)

            result_proc = subprocess.run(
                docker_cmd,
                capture_output=True, text=True, check=True,
            )

            logger.info("cert_generator_docker_output", stdout=result_proc.stdout)
            if result_proc.stderr:
                logger.warning("cert_generator_docker_stderr", stderr=result_proc.stderr)

        except subprocess.CalledProcessError as e:
            print_error(_("Certificate generation failed: {}").format(e))
            logger.error("cert_generation_docker_failed",
                        returncode=e.returncode,
                        stdout=e.stdout,
                        stderr=e.stderr)
            raise RuntimeError(f"Certificate generation failed: {e.stderr}")
        
        result = {
            "nodes": [],
            "validators": [],
        }
        
        # Collect generated certificates from node1/, node2/, etc.
        for i in range(1, node_count + 1):
            node_dir = self.certs_dir / f"node{i}"
            
            node_cert = node_dir / "node-addr.dcert"
            if node_cert.exists():
                result["nodes"].append(str(node_cert))
            
            for cert_file in node_dir.glob("*.pvt.*.dcert"):
                result["validators"].append(str(cert_file))
        
        # Save PKI config
        pki_config = {
            "network": network_name,
            "network_id": network_id,
            "node_count": node_count,
            "root_count": root_count,
            "generated_at": self._get_timestamp(),
            "crypto": "Dilithium (post-quantum)",
        }
        
        pki_config_file = self.certs_dir / "pki-config.json"
        with open(pki_config_file, "w") as f:
            json.dump(pki_config, f, indent=2)
        
        print_success(_("Generated {} node + {} validator certificates").format(len(result['nodes']), len(result['validators'])))
        logger.info("all_certificates_generated",
                   nodes=len(result["nodes"]),
                   validators=len(result["validators"]))
        
        return result
    
    def _normalize_cert_name(self, cert_name: str) -> str:
        """
        Normalize certificate name to standard format.
        
        Converts old format (pvt.{network}.{type}.{idx}.dcert) to
        new format ({network}.{type}.pvt.{idx}.dcert).
        
        Args:
            cert_name: Original certificate filename
            
        Returns:
            Normalized certificate filename
        """
        old_pvt_pattern = re.compile(r'^pvt\.(\w+)\.(\w+)\.(\d+)\.dcert$')
        match = old_pvt_pattern.match(cert_name)
        
        if match:
            network, cert_type, idx = match.groups()
            new_name = f"{network}.{cert_type}.pvt.{idx}.dcert"
            logger.debug("normalized_cert_name", old=cert_name, new=new_name)
            return new_name
        
        return cert_name
    
    def _is_private_cert(self, cert_name: str) -> bool:
        """
        Check if certificate is private (contains private key).
        
        Handles both old (pvt.{network}...) and new ({network}.{type}.pvt.{idx}) formats.
        """
        return ".pvt." in cert_name or cert_name.startswith("pvt.")
    
    def copy_certs_to_shared_ca(self, shared_ca_dir: Path, network_name: str = "stagenet") -> None:
        """
        Copy public certificates to shared CA directory for container mounting.
        
        This copies PUBLIC certificates (no private keys) to shared/ca directory
        which is mounted to /opt/cellframe-node/share/ca in containers.
        
        Args:
            shared_ca_dir: Path to shared CA directory (cache/configs/shared/ca)
            network_name: Network name for certificate naming
        """
        shared_ca_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("copying_certs_to_shared_ca",
                   source=str(self.certs_dir),
                   dest=str(shared_ca_dir))
        
        copied_count = 0
        
        for node_dir in self.certs_dir.iterdir():
            if not node_dir.is_dir() or not node_dir.name.startswith("node"):
                continue
            
            for cert_file in node_dir.glob("*.dcert"):
                cert_name = cert_file.name
                
                if self._is_private_cert(cert_name):
                    continue

                if cert_name.startswith("node-addr"):
                    continue
                
                normalized_name = self._normalize_cert_name(cert_name)
                dest_file = shared_ca_dir / normalized_name
                shutil.copy2(cert_file, dest_file)
                copied_count += 1
                logger.debug("copied_cert_to_shared_ca",
                           cert=cert_name,
                           dest=str(dest_file))
        
        for stale in shared_ca_dir.glob("node-addr*"):
            stale.unlink(missing_ok=True)
            logger.debug("removed_stale_node_addr_from_shared_ca", file=stale.name)

        print_success(_("Copied {} public certificates to shared CA").format(copied_count))
        logger.info("certs_copied_to_shared_ca", count=copied_count)
    
    def copy_private_certs_to_node_data(
        self,
        data_dir: Path,
        node_count: int,
        network_name: str = "stagenet"
    ) -> None:
        """
        Copy private certificates to node data directories.
        
        Private certificates are copied to each node's var/lib/ca directory
        for signing operations. Supports both old (pvt.{network}...) and
        new ({network}.{type}.pvt.{idx}) naming formats.
        
        Args:
            data_dir: Base data directory (cache/data)
            node_count: Number of nodes
            network_name: Network name
        """
        logger.info("copying_private_certs_to_node_data",
                   data_dir=str(data_dir),
                   node_count=node_count)
        
        for node_id in range(1, node_count + 1):
            node_cert_dir = self.certs_dir / f"node{node_id}"
            if not node_cert_dir.exists():
                logger.warning("node_cert_dir_not_found", node_id=node_id)
                continue
            
            node_ca_dir = data_dir / f"node{node_id}" / "lib" / "ca"
            node_ca_dir.mkdir(parents=True, exist_ok=True)
            
            for cert_file in node_cert_dir.glob("*.dcert"):
                normalized_name = self._normalize_cert_name(cert_file.name)
                dest_file = node_ca_dir / normalized_name
                shutil.copy2(cert_file, dest_file)
                logger.debug("copied_cert_to_node_data",
                           node_id=node_id,
                           cert=cert_file.name,
                           dest_name=normalized_name)
        
        print_success(_("Copied private certificates to {} node data directories").format(node_count))
        logger.info("private_certs_copied_to_nodes", count=node_count)
    
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
    
    def certs_exist(self, node_count: int = 0, root_count: int = 0, network_name: str = "stagenet") -> bool:
        """
        Check if all required certificates exist.
        
        Args:
            node_count: Expected number of nodes (0 = basic check only)
            root_count: Expected number of ROOT nodes (0 = basic check only)
            network_name: Network name for certificate naming
            
        Returns:
            True if all required certificates exist
        """
        if not self.certs_dir.exists():
            return False
        
        # Check for PKI config
        pki_config = self.certs_dir / "pki-config.json"
        if not pki_config.exists():
            return False
        
        # Basic check: at least one cert
        certs = list(self.certs_dir.rglob("*.dcert"))
        if len(certs) == 0:
            return False
        
        # If node_count specified, validate all required certs exist
        if node_count > 0:
            missing_certs = self._get_missing_certs(node_count, root_count, network_name)
            if missing_certs:
                logger.warning("incomplete_certificates_detected",
                             missing=missing_certs[:5],  # Log first 5
                             total_missing=len(missing_certs))
                return False
        
        return True
    
    def _get_missing_certs(
        self, 
        node_count: int, 
        root_count: int, 
        network_name: str
    ) -> list:
        """
        Get list of missing required certificates.
        
        Args:
            node_count: Total number of nodes
            root_count: Number of ROOT nodes
            network_name: Network name
            
        Returns:
            List of missing certificate paths
        """
        missing = []
        
        for node_id in range(1, node_count + 1):
            node_dir = self.certs_dir / f"node{node_id}"
            
            # Check node-addr.dcert
            if not (node_dir / "node-addr.dcert").exists():
                missing.append(f"node{node_id}/node-addr.dcert")
            
            # Check validator cert based on role
            if node_id <= root_count:
                # ROOT node
                cert_idx = node_id - 1
                cert_name = f"{network_name}.root.pvt.{cert_idx}.dcert"
            else:
                # MASTER node
                cert_idx = node_id - root_count - 1
                cert_name = f"{network_name}.master.pvt.{cert_idx}.dcert"
            
            if not (node_dir / cert_name).exists():
                missing.append(f"node{node_id}/{cert_name}")
        
        return missing
    
    def generate_single_node_cert(self, output_dir: Path, cert_name: str = "node-addr") -> Optional[str]:
        """Generate a single node-addr certificate and return the node address.

        Uses ``cf-cert-generator --single`` which prints ``ADDR:<hex>`` to stdout.

        Returns:
            Node address string (e.g. "A1B2::C3D4::E5F6::7890") or None on failure.
        """
        if not self.build_docker_image():
            logger.error("cert_builder_image_not_available")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        uid, gid = os.getuid(), os.getgid()

        docker_cmd = [
            "docker", "run", "--rm",
            "--entrypoint", "sh",
            "-v", f"{output_dir.absolute()}:/output",
            CERT_BUILDER_IMAGE,
            "-c",
            f"/usr/local/bin/cf-cert-generator --single /output {cert_name}"
            f" && chown -R {uid}:{gid} /output",
        ]

        try:
            result = subprocess.run(docker_cmd, capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith("ADDR:"):
                    addr = line[5:].strip()
                    logger.info("single_cert_generated", cert_name=cert_name, addr=addr,
                                output_dir=str(output_dir))
                    return addr
            logger.warning("single_cert_no_addr_in_output", stdout=result.stdout[:300])
            return None
        except subprocess.CalledProcessError as e:
            logger.error("single_cert_generation_failed", rc=e.returncode,
                         stderr=e.stderr[:300])
            return None

    def clean(self) -> None:
        """Remove all generated certificates.

        Certificates may have been created inside Docker (owned by root),
        so ``shutil.rmtree`` can fail with PermissionError.  Fall back to
        ``docker run … rm -rf`` which runs as root inside the container.
        """
        logger.info("cleaning_certificates")

        if self.certs_dir.exists():
            print_info(_("Removing certificates..."))
            try:
                shutil.rmtree(self.certs_dir)
            except PermissionError:
                logger.warning("rmtree_permission_denied_fallback_docker",
                               path=str(self.certs_dir))
                subprocess.run(
                    ["docker", "run", "--rm",
                     "-v", f"{self.certs_dir.absolute()}:/certs",
                     "alpine:latest", "rm", "-rf", "/certs/."],
                    check=False,
                )
                shutil.rmtree(self.certs_dir, ignore_errors=True)
            self.certs_dir.mkdir(parents=True, exist_ok=True)

        print_success(_("Certificates cleaned"))
        logger.info("certificates_cleaned")

