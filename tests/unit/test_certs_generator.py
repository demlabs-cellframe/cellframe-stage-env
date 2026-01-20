"""Unit tests for src/certs/generator.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.certs.generator import CertGenerator, CertConfig

class TestCertConfig:
    def test_cert_config_creation(self, tmp_path):
        config = CertConfig(name="node1", type="node", output_dir=tmp_path)
        assert config.name == "node1"

class TestCertGeneratorInit:
    def test_init_creates_certs_dir(self, tmp_path):
        generator = CertGenerator(tmp_path / "stage-env")
        assert generator.certs_dir.exists()

class TestBuildDockerImage:
    @patch('subprocess.run')
    def test_build_docker_image_exists(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="abc\n", stderr="")
        generator = CertGenerator(tmp_path / "stage-env")
        assert generator.build_docker_image() is True

@patch('subprocess.run')
class TestGenerateNodeCert:
    @patch.object(CertGenerator, 'build_docker_image', return_value=True)
    def test_generate_node_cert(self, mock_build, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        generator = CertGenerator(tmp_path / "stage-env")
        cert_path = generator.generate_node_cert(1, "node1")
        assert "node1" in str(cert_path)

class TestClean:
    def test_clean_removes_certificates(self, tmp_path):
        generator = CertGenerator(tmp_path / "stage-env")
        cert_file = generator.certs_dir / "node1" / "cert.dcert"
        cert_file.parent.mkdir(parents=True)
        cert_file.touch()
        generator.clean()
        assert not cert_file.exists()
