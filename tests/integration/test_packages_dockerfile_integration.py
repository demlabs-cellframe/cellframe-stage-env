"""Integration tests for Dockerfile generation with additional packages."""

import pytest
from pathlib import Path
from src.packages import PackageSource, AdditionalPackagesConfig
from src.packages.dockerfile import DockerfileBuilder


class TestDockerfileGeneration:
    """Test Dockerfile generation with various package configurations."""
    
    def test_dockerfile_no_packages(self, tmp_path):
        """Test default Dockerfile without additional packages."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig()
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "FROM debian:bullseye" in dockerfile
        assert "cellframe-node.deb" in dockerfile
        assert "apt-get install -y gdb" not in dockerfile
    
    def test_dockerfile_with_apt_packages(self, tmp_path):
        """Test Dockerfile with APT packages."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb", "strace", "valgrind"])
            ]
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "# Install APT packages" in dockerfile
        assert "apt-get install -y gdb strace valgrind" in dockerfile
    
    def test_dockerfile_with_local_package(self, tmp_path):
        """Test Dockerfile with local .deb package."""
        # Create dummy .deb file
        deb_file = tmp_path / "custom.deb"
        deb_file.touch()
        
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="local", path=str(deb_file))
            ]
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "# Install local .deb packages" in dockerfile
        assert "COPY" in dockerfile
        assert "dpkg -i" in dockerfile
    
    def test_dockerfile_with_repository(self, tmp_path):
        """Test Dockerfile with custom repository."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            groups={
                "master": [
                    PackageSource(
                        type="repository",
                        repo_url="https://plugins.cellframe.net/debian",
                        key_url="https://plugins.cellframe.net/key.gpg",
                        packages=["cellframe-plugin-staking"]
                    )
                ]
            }
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="master",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "# Setup custom repositories" in dockerfile
        assert "curl -fsSL https://plugins.cellframe.net/key.gpg" in dockerfile
        assert "gpg --dearmor" in dockerfile
        assert "cellframe-plugin-staking" in dockerfile
    
    def test_dockerfile_with_pre_configure_script(self, tmp_path):
        """Test Dockerfile with pre-configuration script."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(
                    type="script",
                    stage="post_configure",
                    script="echo 'Pre-config setup'"
                )
            ]
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "# Pre-configuration scripts" in dockerfile
        assert "before cellframe-node install" in dockerfile
        # Script should come BEFORE cellframe install
        pre_config_pos = dockerfile.find("Pre-config setup")
        cellframe_pos = dockerfile.find("Install cellframe-node")
        assert pre_config_pos < cellframe_pos
    
    def test_dockerfile_with_post_install_script(self, tmp_path):
        """Test Dockerfile with post-installation script."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            nodes={
                "node-1": [
                    PackageSource(
                        type="script",
                        stage="post_install",
                        script="echo 'node-role = ROOT' >> /opt/cellframe-node/etc/cellframe-node.cfg"
                    )
                ]
            }
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        assert "# Post-installation scripts" in dockerfile
        assert "after cellframe-node install" in dockerfile
        # Script should come AFTER cellframe install
        post_install_pos = dockerfile.find("Post-installation scripts")
        cellframe_pos = dockerfile.find("Install cellframe-node")
        assert post_install_pos > cellframe_pos
    
    def test_dockerfile_all_levels_combined(self, tmp_path):
        """Test Dockerfile with packages from all levels: base + group + node."""
        deb_file = tmp_path / "custom.deb"
        deb_file.touch()
        
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb"])
            ],
            groups={
                "master": [
                    PackageSource(type="apt", packages=["strace"])
                ]
            },
            nodes={
                "node-1": [
                    PackageSource(type="local", path=str(deb_file))
                ]
            }
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="master",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        # Should have packages from all three levels
        assert "gdb" in dockerfile  # base
        assert "strace" in dockerfile  # group
        assert "COPY" in dockerfile  # node-specific local package
    
    def test_dockerfile_correct_order(self, tmp_path):
        """Test that Dockerfile sections are in correct order."""
        deb_file = tmp_path / "custom.deb"
        deb_file.touch()
        
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb"]),
                PackageSource(
                    type="repository",
                    repo_url="https://example.com/repo",
                    key_url="https://example.com/key.gpg",
                    packages=["custom-tool"]
                ),
                PackageSource(type="local", path=str(deb_file)),
                PackageSource(
                    type="script",
                    stage="post_configure",
                    script="echo pre"
                ),
                PackageSource(
                    type="script",
                    stage="post_install",
                    script="echo post"
                )
            ]
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        # Check order: APT → Repos → Local → Pre-scripts → Cellframe → Post-scripts
        apt_pos = dockerfile.find("# Install APT packages")
        repo_pos = dockerfile.find("# Setup custom repositories")
        local_pos = dockerfile.find("# Install local .deb packages")
        pre_pos = dockerfile.find("# Pre-configuration scripts")
        cellframe_pos = dockerfile.find("# Install cellframe-node")
        post_pos = dockerfile.find("# Post-installation scripts")
        
        assert apt_pos < repo_pos < local_pos < pre_pos < cellframe_pos < post_pos
    
    def test_dockerfile_save_to_file(self, tmp_path):
        """Test saving Dockerfile to file."""
        builder = DockerfileBuilder()
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["gdb"])]
        )
        
        dockerfile = builder.generate_dockerfile(
            node_id="node-1",
            node_role="root",
            cellframe_deb_path="/opt/cellframe-node.deb",
            additional_packages=config
        )
        
        output_path = tmp_path / "Dockerfile.node-1"
        builder.save_dockerfile(dockerfile, output_path)
        
        assert output_path.exists()
        content = output_path.read_text()
        assert "gdb" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
