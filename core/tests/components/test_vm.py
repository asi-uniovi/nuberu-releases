import inspect
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import asimpy
import pytest

from nuberu import VM, EventBus, InstanceClass, VMState
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
def mock_instance_class() -> Generator[InstanceClass, None, None]:
    """Mock InstanceClass."""
    instance_class = MagicMock(spec=InstanceClass)
    instance_class.cores = 8.0
    instance_class.mem = 16.0
    instance_class.name = "Standard"
    return instance_class


@pytest.fixture
def mock_event_bus() -> EventBus:
    """Mock for EventBus."""
    return MagicMock(spec=EventBus)


@pytest.fixture
def vm(
    mock_env: asimpy.Environment,
    mock_instance_class: InstanceClass,
    mock_event_bus: EventBus,
) -> Generator[VM, None, None]:
    """Create a VM instance for testing."""
    return VM(
        env=mock_env,
        vm_id="VM1",
        instance_class=mock_instance_class,
        event_bus=mock_event_bus,
    )


@pytest.fixture
def mock_container() -> Generator[Container, None, None]:
    """Mock Container."""
    container = MagicMock(spec=Container)
    container.container_id = "C1"
    container.cpu = 2.0
    container.memory = 4.0
    container.assign_vm = MagicMock()
    container.start = MagicMock()
    container.stop = AsyncMock()  # stop() is now async
    yield container


def test_vm_initialization(vm: VM, mock_instance_class: InstanceClass) -> None:
    """Test that the VM is initialized correctly."""
    assert vm.vm_id == "VM1"
    assert vm.state == VMState.PENDING
    assert vm.instance_class == mock_instance_class
    assert vm.cpu == 8.0
    assert vm.memory == 16.0
    assert vm.available_cpu == 8.0
    assert vm.available_memory == 16.0
    assert vm.images == set()
    assert isinstance(vm.containers, dict)


def test_vm_register_container(vm: VM, mock_container: Container) -> None:
    """Test registering a container in the VM."""
    vm.register_container(mock_container)

    assert mock_container.container_id in vm.containers
    mock_container.assign_vm.assert_called_once_with(vm)
    mock_container.start.assert_called_once()


def test_vm_deregister_container(vm: VM, mock_container: Container) -> None:
    """Test deregistering a container from the VM."""
    vm.register_container(mock_container)
    vm.deregister_container(mock_container)

    assert mock_container.container_id not in vm.containers
    mock_container.stop.assert_not_called()  # Stop should not be called


def test_vm_add_image(vm: VM) -> None:
    """Test adding an image to the VM."""
    vm.add_image("ubuntu")

    assert "ubuntu" in vm.images


def test_vm_has_image(vm: VM) -> None:
    """Test checking if the VM has an image."""
    vm.add_image("ubuntu")

    assert vm.has_image("ubuntu") is True
    assert vm.has_image("debian") is False


@pytest.mark.asyncio
async def test_vm_update_usage(vm: VM) -> None:
    """Test updating CPU and memory usage in the VM."""
    result = await vm.update_usage(-2.0, -4.0)

    assert result is True


@pytest.mark.asyncio
async def test_vm_update_usage_exceeding_limits(vm: VM) -> None:
    """Test updating CPU and memory usage when exceeding limits."""
    result = await vm.update_usage(10.0, 20.0)  # Exceeds limits

    assert result is False


@pytest.mark.asyncio
async def test_vm_shutdown(vm: VM, mock_container: Container) -> None:
    """Test shutting down the VM and stopping all containers."""
    vm.register_container(mock_container)
    await vm.shutdown()

    assert vm.state == VMState.STOPPED
    mock_container.stop.assert_called_once()
