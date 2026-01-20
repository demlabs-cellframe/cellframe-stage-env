"""Mock fixtures and utilities for testing stage-env components."""

from unittest.mock import MagicMock, AsyncMock
from typing import Dict, List, Any

__all__ = [
    "MockDockerClient",
    "MockDockerContainer",
    "MockDockerNetwork",
    "create_mock_docker_client",
    "create_mock_container",
]


class MockDockerContainer:
    """Mock Docker container for testing."""
    
    def __init__(
        self,
        container_id: str = "mock_container_123",
        name: str = "node1",
        status: str = "running",
        image: str = "cellframe-node:latest",
    ):
        self.id = container_id
        self.name = name
        self.status = status
        self.image = MagicMock()
        self.image.tags = [image]
        self.attrs = {
            "Id": container_id,
            "Name": name,
            "State": {"Status": status},
            "Config": {"Image": image},
        }
        self.exec_run_responses = []
        self.call_count = 0
    
    def start(self) -> None:
        """Mock start method."""
        self.status = "running"
        self.attrs["State"]["Status"] = "running"
    
    def stop(self, timeout: int = 10) -> None:
        """Mock stop method."""
        self.status = "exited"
        self.attrs["State"]["Status"] = "exited"
    
    def remove(self, force: bool = False, v: bool = False) -> None:
        """Mock remove method."""
        self.status = "removed"
    
    def exec_run(
        self,
        cmd,
        stdout: bool = True,
        stderr: bool = True,
        **kwargs
    ):
        """Mock exec_run method."""
        self.call_count += 1
        
        # Return pre-configured response if available
        if self.exec_run_responses:
            response = self.exec_run_responses.pop(0)
            if isinstance(response, tuple):
                return response
            if isinstance(response, Exception):
                raise response
        
        # Default response
        return (0, b"Mock response")
    
    def add_exec_response(self, returncode: int, output):
        """Add a response for exec_run."""
        if isinstance(output, str):
            output = output.encode()
        self.exec_run_responses.append((returncode, output))
    
    def add_exec_exception(self, exception: Exception):
        """Add an exception to raise on exec_run."""
        self.exec_run_responses.append(exception)
    
    def reload(self):
        """Mock reload method."""
        pass
    
    def logs(self, **kwargs):
        """Mock logs method."""
        return b"Mock logs"


class MockDockerNetwork:
    """Mock Docker network for testing."""
    
    def __init__(
        self,
        network_id: str = "mock_network_123",
        name: str = "stagenet",
    ):
        self.id = network_id
        self.name = name
        self.attrs = {
            "Id": network_id,
            "Name": name,
        }
    
    def connect(self, container, **kwargs):
        """Mock connect method."""
        pass
    
    def disconnect(self, container, **kwargs):
        """Mock disconnect method."""
        pass
    
    def remove(self):
        """Mock remove method."""
        pass


class MockDockerClient:
    """Mock Docker client for testing."""
    
    def __init__(self):
        self.containers = MockContainersAPI()
        self.networks = MockNetworksAPI()
        self.images = MockImagesAPI()
        self.volumes = MockVolumesAPI()
        self.api = MagicMock()
    
    def close(self):
        """Mock close method."""
        pass
    
    def ping(self):
        """Mock ping method."""
        return True


class MockContainersAPI:
    """Mock containers API."""
    
    def __init__(self):
        self._containers = {}
        self.run_calls = []
    
    def run(
        self,
        image: str,
        command=None,
        **kwargs
    ):
        """Mock run method."""
        container_name = kwargs.get("name", f"container_{len(self._containers) + 1}")
        container = MockDockerContainer(
            container_id=f"mock_{container_name}",
            name=container_name,
            image=image,
            status="running",
        )
        self._containers[container_name] = container
        self.run_calls.append({"image": image, "command": command, **kwargs})
        return container
    
    def get(self, container_id: str):
        """Mock get method."""
        if container_id in self._containers:
            return self._containers[container_id]
        for container in self._containers.values():
            if container.id == container_id:
                return container
        raise Exception(f"Container not found: {container_id}")
    
    def list(self, **kwargs):
        """Mock list method."""
        return list(self._containers.values())


class MockNetworksAPI:
    """Mock networks API."""
    
    def __init__(self):
        self._networks = {}
    
    def create(self, name: str, **kwargs):
        """Mock create method."""
        network = MockDockerNetwork(
            network_id=f"mock_net_{name}",
            name=name,
        )
        self._networks[name] = network
        return network
    
    def get(self, network_id: str):
        """Mock get method."""
        if network_id in self._networks:
            return self._networks[network_id]
        for network in self._networks.values():
            if network.id == network_id:
                return network
        raise Exception(f"Network not found: {network_id}")
    
    def list(self, **kwargs):
        """Mock list method."""
        return list(self._networks.values())


class MockImagesAPI:
    """Mock images API."""
    
    def __init__(self):
        self.pull_calls = []
    
    def pull(self, repository: str, tag: str = "latest", **kwargs):
        """Mock pull method."""
        self.pull_calls.append({"repository": repository, "tag": tag})
        return MagicMock()
    
    def build(self, **kwargs):
        """Mock build method."""
        return (MagicMock(), [])


class MockVolumesAPI:
    """Mock volumes API."""
    
    def __init__(self):
        self._volumes = {}
    
    def create(self, name: str, **kwargs):
        """Mock create method."""
        volume = MagicMock()
        volume.name = name
        self._volumes[name] = volume
        return volume


def create_mock_docker_client():
    """Create a mock Docker client for testing."""
    return MockDockerClient()


def create_mock_container(
    name: str = "node1",
    status: str = "running",
    image: str = "cellframe-node:latest",
):
    """Create a mock Docker container for testing."""
    return MockDockerContainer(
        container_id=f"mock_{name}",
        name=name,
        status=status,
        image=image,
    )
