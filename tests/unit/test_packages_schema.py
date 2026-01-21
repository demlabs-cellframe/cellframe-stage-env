"""Unit tests for additional packages schema."""

import pytest
from pathlib import Path
from pydantic import ValidationError
from src.packages import PackageSource, AdditionalPackagesConfig


class TestPackageSource:
    """Tests for PackageSource model."""
    
    def test_local_package_valid(self, tmp_path):
        """Test valid local package."""
        deb_file = tmp_path / "test.deb"
        deb_file.touch()
        
        pkg = PackageSource(
            type="local",
            path=str(deb_file)
        )
        
        assert pkg.type == "local"
        assert pkg.path == str(deb_file)
        assert pkg.validate_source() is None  # No errors
    
    def test_local_package_missing_path(self):
        """Test local package without path."""
        pkg = PackageSource(type="local")
        error = pkg.validate_source()
        assert error is not None
        assert "missing 'path'" in error
    
    def test_local_package_not_found(self):
        """Test local package with non-existent path."""
        pkg = PackageSource(
            type="local",
            path="/nonexistent/package.deb"
        )
        error = pkg.validate_source()
        assert error is not None
        assert "not found" in error
    
    def test_local_package_not_deb(self, tmp_path):
        """Test local package that's not a .deb file."""
        txt_file = tmp_path / "test.txt"
        txt_file.touch()
        
        pkg = PackageSource(
            type="local",
            path=str(txt_file)
        )
        error = pkg.validate_source()
        assert error is not None
        assert ".deb" in error
    
    def test_apt_package_valid(self):
        """Test valid APT package."""
        pkg = PackageSource(
            type="apt",
            packages=["gdb", "strace"]
        )
        
        assert pkg.type == "apt"
        assert pkg.packages == ["gdb", "strace"]
        assert pkg.validate_source() is None
    
    def test_apt_package_missing_packages(self):
        """Test APT package without packages list."""
        pkg = PackageSource(type="apt")
        error = pkg.validate_source()
        assert error is not None
        assert "missing 'packages'" in error
    
    def test_apt_package_empty_list_validation_error(self):
        """Test that empty packages list raises validation error."""
        with pytest.raises(ValidationError, match="packages list cannot be empty"):
            PackageSource(
                type="apt",
                packages=[]
            )
    
    def test_repository_package_valid(self):
        """Test valid repository package with key_url."""
        pkg = PackageSource(
            type="repository",
            repo_url="https://apt.example.com/debian",
            key_url="https://apt.example.com/key.gpg",
            packages=["cellframe-plugin"]
        )
        
        assert pkg.type == "repository"
        assert pkg.validate_source() is None
    
    def test_repository_package_with_key_id(self):
        """Test valid repository package with key_id."""
        pkg = PackageSource(
            type="repository",
            repo_url="https://apt.example.com/debian",
            key_id="ABC123",
            key_server="keyserver.ubuntu.com",
            packages=["cellframe-plugin"]
        )
        
        assert pkg.validate_source() is None
    
    def test_repository_package_missing_repo_url(self):
        """Test repository package without repo_url."""
        pkg = PackageSource(
            type="repository",
            key_url="https://apt.example.com/key.gpg",
            packages=["cellframe-plugin"]
        )
        error = pkg.validate_source()
        assert error is not None
        assert "missing 'repo_url'" in error
    
    def test_repository_package_missing_key(self):
        """Test repository package without key."""
        pkg = PackageSource(
            type="repository",
            repo_url="https://apt.example.com/debian",
            packages=["cellframe-plugin"]
        )
        error = pkg.validate_source()
        assert error is not None
        assert "'key_url' or 'key_id'" in error
    
    def test_script_post_configure_inline(self):
        """Test valid inline post_configure script."""
        pkg = PackageSource(
            type="script",
            stage="post_configure",
            script="echo 'Configuration'"
        )
        
        assert pkg.type == "script"
        assert pkg.stage == "post_configure"
        assert pkg.validate_source() is None
    
    def test_script_post_install_file(self, tmp_path):
        """Test valid post_install script from file."""
        script_file = tmp_path / "setup.sh"
        script_file.write_text("#!/bin/bash\necho 'Setup'")
        
        pkg = PackageSource(
            type="script",
            stage="post_install",
            script_path=str(script_file)
        )
        
        assert pkg.validate_source() is None
    
    def test_script_missing_stage(self):
        """Test script without stage."""
        pkg = PackageSource(
            type="script",
            script="echo 'test'"
        )
        error = pkg.validate_source()
        assert error is not None
        assert "missing 'stage'" in error
    
    def test_script_missing_content(self):
        """Test script without script or script_path."""
        with pytest.raises(ValueError, match="'script' or 'script_path' must be provided"):
            PackageSource(
                type="script",
                stage="post_install"
            )
    
    def test_script_file_not_found(self):
        """Test script with non-existent file."""
        pkg = PackageSource(
            type="script",
            stage="post_install",
            script_path="/nonexistent/script.sh"
        )
        error = pkg.validate_source()
        assert error is not None
        assert "not found" in error
    
    def test_script_validation_error_on_missing_script(self):
        """Test that validation catches missing script."""
        with pytest.raises(ValueError, match="'script' or 'script_path' must be provided"):
            PackageSource(
                type="script",
                stage="post_install"
            )


class TestAdditionalPackagesConfig:
    """Tests for AdditionalPackagesConfig model."""
    
    def test_empty_config(self):
        """Test empty configuration."""
        config = AdditionalPackagesConfig()
        
        assert config.base == []
        assert config.groups == {}
        assert config.nodes == {}
    
    def test_base_packages(self, tmp_path):
        """Test configuration with base packages."""
        deb_file = tmp_path / "test.deb"
        deb_file.touch()
        
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb"]),
                PackageSource(type="local", path=str(deb_file))
            ]
        )
        
        assert len(config.base) == 2
        assert config.base[0].type == "apt"
        assert config.base[1].type == "local"
    
    def test_group_packages(self):
        """Test configuration with group-specific packages."""
        config = AdditionalPackagesConfig(
            groups={
                "root": [PackageSource(type="apt", packages=["tool1"])],
                "master": [PackageSource(type="apt", packages=["tool2"])]
            }
        )
        
        assert len(config.groups) == 2
        assert "root" in config.groups
        assert "master" in config.groups
    
    def test_invalid_group_name(self):
        """Test that invalid group names raise validation error."""
        with pytest.raises(ValidationError, match="Invalid group name"):
            AdditionalPackagesConfig(
                groups={
                    "invalid_role": [PackageSource(type="apt", packages=["tool"])]
                }
            )
    
    def test_node_specific_packages(self):
        """Test configuration with node-specific packages."""
        config = AdditionalPackagesConfig(
            nodes={
                "node-1": [PackageSource(type="apt", packages=["tool1"])],
                "node-2": [PackageSource(type="apt", packages=["tool2"])]
            }
        )
        
        assert len(config.nodes) == 2
        assert "node-1" in config.nodes
        assert "node-2" in config.nodes
    
    def test_get_packages_for_node_base_only(self):
        """Test getting packages when only base packages exist."""
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["base-tool"])]
        )
        
        packages = config.get_packages_for_node("node-1", "root")
        
        assert len(packages) == 1
        assert packages[0].type == "apt"
    
    def test_get_packages_for_node_with_group(self):
        """Test getting packages with base + group."""
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["base"])],
            groups={
                "root": [PackageSource(type="apt", packages=["root-tool"])]
            }
        )
        
        packages = config.get_packages_for_node("node-1", "root")
        
        assert len(packages) == 2
        assert packages[0].packages == ["base"]
        assert packages[1].packages == ["root-tool"]
    
    def test_get_packages_for_node_all_levels(self):
        """Test getting packages from all levels: base + group + node."""
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["base"])],
            groups={
                "master": [PackageSource(type="apt", packages=["master-tool"])]
            },
            nodes={
                "node-1": [PackageSource(type="apt", packages=["node1-tool"])]
            }
        )
        
        packages = config.get_packages_for_node("node-1", "master")
        
        assert len(packages) == 3
        assert packages[0].packages == ["base"]
        assert packages[1].packages == ["master-tool"]
        assert packages[2].packages == ["node1-tool"]
    
    def test_get_packages_for_node_no_match(self):
        """Test getting packages when node has no specific packages."""
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["base"])],
            nodes={
                "node-2": [PackageSource(type="apt", packages=["node2-tool"])]
            }
        )
        
        packages = config.get_packages_for_node("node-1", "full")
        
        # Should only get base packages
        assert len(packages) == 1
        assert packages[0].packages == ["base"]
    
    def test_has_packages_for_node(self):
        """Test checking if node has any packages."""
        config = AdditionalPackagesConfig(
            base=[PackageSource(type="apt", packages=["base"])]
        )
        
        assert config.has_packages_for_node("node-1", "root") is True
    
    def test_has_packages_for_node_empty(self):
        """Test checking if node has packages when config is empty."""
        config = AdditionalPackagesConfig()
        
        assert config.has_packages_for_node("node-1", "root") is False
    
    def test_validate_all_sources_no_errors(self, tmp_path):
        """Test validation with all valid sources."""
        deb_file = tmp_path / "test.deb"
        deb_file.touch()
        
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb"]),
                PackageSource(type="local", path=str(deb_file))
            ]
        )
        
        errors = config.validate_all_sources()
        assert errors == []
    
    def test_validate_all_sources_with_errors(self):
        """Test validation with invalid sources."""
        config = AdditionalPackagesConfig(
            base=[
                PackageSource(type="apt", packages=["gdb"]),  # Valid
                PackageSource(type="local", path="/nonexistent.deb"),  # Invalid
                PackageSource(type="repository", packages=["tool"])  # Missing repo_url
            ]
        )
        
        errors = config.validate_all_sources()
        
        assert len(errors) == 2
        assert "not found" in errors[0]
        assert "repo_url" in errors[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
