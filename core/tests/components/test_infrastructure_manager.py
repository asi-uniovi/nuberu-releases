import asyncio
import inspect
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import asimpy
import pytest

from nuberu import (
    VM,
    Channel,
    EventBus,
    InstanceClass,
    VMState,
)
from nuberu.components.infrastructure_manager import InfrastructureManager


@pytest.fixture
def mock_env() -> Generator[asimpy.Environment, None, None]:
    """Mock SimPy environment."""
    env = MagicMock(spec=asimpy.Environment)
    env.now = 10

    async def fake_timeout(duration):
        return None

    env.timeout = fake_timeout

    def mock_process(coro):
        if inspect.iscoroutine(coro):
            coro.close()
        return MagicMock()

    env.process.side_effect = mock_process
    return env


@pytest.fixture
def mock_allocator_channel() -> Generator[Channel, None, None]:
    """Mock Channel."""
    channel = MagicMock(spec=Channel)
    channel.receive = AsyncMock()
    return channel


@pytest.fixture
def mock_instance_class() -> Generator[InstanceClass, None, None]:
    """Mock InstanceClass."""
    instance_class = MagicMock(spec=InstanceClass)
    instance_class.cores = 8.0
    instance_class.mem = 16.0
    instance_class.limit = 5
    instance_class.name = "Standard"
    return instance_class


@pytest.fixture
def mock_event_bus() -> EventBus:
    """Mock for EventBus."""
    return MagicMock(spec=EventBus)


@pytest.fixture
def mock_runtime_model_factories():
    """Mock runtime model factories dict."""

    def factory(env, container, performance, event_bus):
        runtime_model = MagicMock()
        runtime_model.run = MagicMock(return_value=iter([]))  # Empty generator
        return runtime_model

    return {"test-app": factory}


@pytest.fixture
def mock_vm(
    mock_instance_class: InstanceClass, mock_env: asimpy.Environment
) -> Generator[VM, None, None]:
    """Mock VM."""
    vm = MagicMock(spec=VM)
    vm.env = mock_env
    vm.vm_id = "VM1"
    vm.instance_class = mock_instance_class
    vm.cpu = mock_instance_class.cores
    vm.memory = mock_instance_class.mem
    vm.available_cpu = mock_instance_class.cores
    vm.available_memory = mock_instance_class.mem

    vm.state = VMState.PENDING

    vm.start = lambda: setattr(vm, "state", VMState.RUNNING)
    vm.shutdown = lambda: setattr(vm, "state", VMState.STOPPED)

    vm.containers = {}
    vm.register_container = MagicMock()
    vm.deregister_container = MagicMock()
    return vm


@pytest.fixture
def real_vm(mock_env, mock_instance_class, mock_event_bus) -> VM:
    return VM(
        env=mock_env,
        vm_id="VM1",
        instance_class=mock_instance_class,
        event_bus=mock_event_bus,
    )


@pytest.fixture
def mock_infra_to_lb_channel() -> Channel:
    """Mock for infra_to_lb_channel."""
    return MagicMock(spec=Channel)


@pytest.fixture
def infrastructure_manager(
    mock_env: asimpy.Environment,
    mock_allocator_channel: Channel,
    mock_event_bus: EventBus,
    real_vm: VM,
    mock_runtime_model_factories,
) -> Generator[InfrastructureManager, None, None]:
    """Create an InfrastructureManager instance for testing."""
    manager = InfrastructureManager(
        env=mock_env,
        allocator_channel=mock_allocator_channel,
        event_bus=mock_event_bus,
        runtime_model_factories=mock_runtime_model_factories,
        get_rps_cb=lambda app, cores, ic: 100.0,  # Mock RPS callback
    )
    manager.vms["VM1"] = real_vm
    return manager


def test_infrastructure_manager_initialization(
    infrastructure_manager: InfrastructureManager,
) -> None:
    """Test that InfrastructureManager initializes correctly."""
    assert isinstance(infrastructure_manager.vms, dict)


def test_start_vm(
    infrastructure_manager: InfrastructureManager, mock_instance_class: InstanceClass
) -> None:
    """Test that start_vm creates a new VM correctly."""
    infrastructure_manager.start_vm("VM2", mock_instance_class)

    assert "VM2" in infrastructure_manager.vms
    assert infrastructure_manager.vms["VM2"].state == VMState.RUNNING


def test_start_existing_vm(
    infrastructure_manager: InfrastructureManager, mock_instance_class: InstanceClass
) -> None:
    """Test that starting an existing VM does not create a duplicate."""
    infrastructure_manager.start_vm("VM1", mock_instance_class)
    initial_vm_count = len(infrastructure_manager.vms)

    infrastructure_manager.start_vm("VM1", mock_instance_class)
    final_vm_count = len(infrastructure_manager.vms)

    assert initial_vm_count == final_vm_count
    assert infrastructure_manager.vms["VM1"].state == VMState.RUNNING


def test_start_vm_exceeding_limit(
    infrastructure_manager: InfrastructureManager, mock_instance_class: InstanceClass
) -> None:
    """Test that start_vm does not exceed instance class limit."""
    # Reset the VM count and the VM dictionary for the test
    infrastructure_manager.vm_count_by_ic.clear()
    infrastructure_manager.vms = {}
    mock_instance_class.name = "test_instance_class"
    mock_instance_class.limit = 1  # Only 1 VM allowed

    infrastructure_manager.start_vm("VM1", mock_instance_class)
    infrastructure_manager.start_vm("VM2", mock_instance_class)  # Should not create

    assert "VM2" not in infrastructure_manager.vms  # Second VM should not be created


@pytest.mark.asyncio
async def test_stop_vm(
    infrastructure_manager: InfrastructureManager, mock_instance_class: InstanceClass
) -> None:
    """Test stopping a VM."""
    infrastructure_manager.start_vm("VM1", mock_instance_class)
    await infrastructure_manager.stop_vm("VM1")

    assert infrastructure_manager.vms["VM1"].state == VMState.STOPPED


# @pytest.mark.xfail(reason="Broken test inherited from old codebase")
@pytest.mark.asyncio
async def test_listen_allocator_instructions(
    infrastructure_manager: InfrastructureManager,
    mock_instance_class: InstanceClass,
) -> None:
    """Test handling allocator instructions asynchronously."""
    instructions = [
        [
            {
                "action": "start_vm",
                "data": {"vm_id": "VM3", "instance_class": mock_instance_class},
            }
        ],
        StopAsyncIteration,
    ]

    infrastructure_manager.allocator_channel.receive = AsyncMock(
        side_effect=instructions
    )

    task = asyncio.create_task(infrastructure_manager.listen_allocator_instructions())

    # Allow some time for the task to process the instruction
    await asyncio.sleep(0.1)

    # Ensure task is done before canceling
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # The VM should have been created
    assert "VM3" in infrastructure_manager.vms
