import inspect
from typing import Generator
from unittest.mock import MagicMock

import asimpy
import pytest

from nuberu import (
    VM,
    ContainerClass,
    ContainerState,
    EventBus,
)
from nuberu.components.container import Container


@pytest.fixture
def mock_env() -> Generator[asimpy.Environment, None, None]:
    """Mock SimPy environment."""

    class AwaitableMock(MagicMock):
        def __await__(self):
            yield
            return self.return_value

    env = MagicMock(spec=asimpy.Environment)
    env.now = 10

    def mock_process(coro):
        if inspect.iscoroutine(coro):
            coro.close()
        return MagicMock()

    env.process.side_effect = mock_process
    env.timeout.side_effect = lambda delay: AwaitableMock()
    return env


@pytest.fixture
def mock_vm() -> Generator[VM, None, None]:
    """Mock VM."""
    vm = MagicMock(spec=VM)
    vm.vm_id = "VM1"
    vm.cpu = 8.0
    vm.memory = 16.0
    vm.available_cpu = 8.0
    vm.available_memory = 16.0
    vm.has_image = MagicMock(return_value=False)
    vm.add_image = MagicMock()
    vm.containers = MagicMock()
    return vm


@pytest.fixture
def mock_container_class() -> Generator[ContainerClass, None, None]:
    """Mock ContainerClass."""
    container_class = MagicMock(spec=ContainerClass)
    container_class.cores = 2.0
    container_class.mem = 4.0
    container_class.app = MagicMock()
    container_class.app.name = "test-app"
    return container_class


@pytest.fixture
def mock_runtime_model_factory():
    """Mock runtime model factory that returns a mock runtime model."""

    def factory(
        env,
        container,
        performance,
        event_bus,
        duplex_channel,
        idle_sink,
        progress_sink,
    ):
        runtime_model = MagicMock()
        runtime_model.run = MagicMock(return_value=iter([]))  # Empty generator
        runtime_model.duplex_channel = duplex_channel  # Store the duplex channel
        runtime_model.can_enqueue = MagicMock(
            return_value=True
        )  # Allow request enqueueing
        runtime_model.service_p95 = (
            None  # Avoid MagicMock comparison issues in container.stop()
        )
        return runtime_model

    return factory


@pytest.fixture
def mock_event_bus() -> Generator[EventBus, None, None]:
    return MagicMock(spec=EventBus)


@pytest.fixture
def container(
    mock_env: asimpy.Environment,
    mock_vm: VM,
    mock_container_class: ContainerClass,
    mock_runtime_model_factory,
    mock_event_bus: EventBus,
) -> Generator[Container, None, None]:
    """Create a Container instance for testing."""
    return Container(
        env=mock_env,
        container_id="C1",
        container_class=mock_container_class,
        vm=mock_vm,
        image_name="ubuntu",
        runtime_model_factory=mock_runtime_model_factory,
        event_bus=mock_event_bus,
        rps=100.0,
        drain_pending_requests=False,  # Use hardstop for unit tests with mocks
    )


def test_container_initialization(
    container: Container, mock_container_class: ContainerClass, mock_vm: VM
) -> None:
    """Test that the Container is initialized correctly."""
    assert container.container_id == "C1"
    assert container.image_name == "ubuntu"
    assert container.container_class == mock_container_class
    assert container.vm == mock_vm
    assert container.state == ContainerState.CREATED
    # Container now uses DuplexChannel for RuntimeModel communication
    from nuberu.channels import DuplexChannel

    assert isinstance(container.runtime_duplex_channel, DuplexChannel)


def test_container_properties(container: Container) -> None:
    """Test container resource properties."""
    assert container.cpu == 2.0
    assert container.memory == 4.0
    assert container.available_cpu == 2.0
    assert container.available_memory == 4.0


def test_container_start_without_image(container: Container, mock_vm: VM) -> None:
    """Test starting a container that needs to download an image."""
    container.start()
    assert container.state == ContainerState.RUNNING
    mock_vm.add_image.assert_called_once_with("ubuntu")


def test_container_start_with_image(container: Container, mock_vm: VM) -> None:
    """Test starting a container when the image is already present."""
    mock_vm.has_image.return_value = True
    container.start()
    assert container.state == ContainerState.RUNNING
    mock_vm.add_image.assert_not_called()


@pytest.mark.asyncio
async def test_container_stop(container: Container, mock_vm: VM) -> None:
    """Test stopping a container and releasing resources.

    Note: Container no longer calls vm.containers.pop() directly.
    Instead, it publishes CONTAINER_STOPPED event and the VM handles
    the deregistration via its _container_lifecycle_listener.
    """
    await container.stop()
    assert container.state == ContainerState.STOPPED
    # VM now manages its own container list via event listener,
    # so we just verify the container reached STOPPED state


def test_container_release_resources(container: Container, mock_vm: VM) -> None:
    """Test that the container releases resources correctly."""
    container.release_resources_in_vm(1.0, 2.0)

    mock_vm.available_cpu += 1.0
    mock_vm.available_memory += 2.0


def test_container_assign_vm(container: Container, mock_vm: VM) -> None:
    """Test assigning a VM to the container."""
    new_vm = MagicMock(spec=VM)
    new_vm.vm_id = "VM2"

    container.assign_vm(new_vm)
    assert container.vm == new_vm
