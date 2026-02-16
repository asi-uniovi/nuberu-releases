from unittest.mock import AsyncMock, MagicMock

import pytest

from nuberu import Channel
from nuberu.components.allocator import Allocator
from nuberu.core.events import EventBus


@pytest.fixture
def mock_env():
    """Mock for the simulation environment."""
    env = MagicMock()
    env.now = 10
    return env


@pytest.fixture
def mock_request_channel():
    """Mock for the request channel."""
    channel = MagicMock(spec=Channel)
    channel.receive = AsyncMock()  # Simulate async receive
    return channel


@pytest.fixture
def mock_event_bus() -> EventBus:
    """Mock for EventBus."""
    return MagicMock(spec=EventBus)


@pytest.mark.xfail(reason="Broken test inherited from old codebase")
async def test_apply_next_allocation_success(
    mock_env, mock_request_channel, mock_event_bus, capsys
):
    """Test applying an allocation when allocations are available."""
    # Pass a list with one allocation block
    allocations = [["Allocation_1"]]

    allocator = Allocator(mock_env, allocations, mock_request_channel, mock_event_bus)
    await allocator.apply_next_allocation()

    captured = capsys.readouterr()
    print(captured.out)  # For debugging purposes
    assert f"[{mock_env.now}] Applying allocation block" in captured.out


@pytest.mark.xfail(reason="Broken test inherited from old codebase")
async def test_apply_next_allocation_no_more_allocations(
    mock_env, mock_request_channel, mock_event_bus, capsys
):
    """Test applying an allocation when no more allocations are available."""
    # Pass an empty list to simulate no allocations
    allocations: list[list] = []

    allocator = Allocator(mock_env, allocations, mock_request_channel, mock_event_bus)
    await allocator.apply_next_allocation()

    captured = capsys.readouterr()
    assert "No more allocations available." in captured.out


@pytest.mark.xfail(reason="Broken test inherited from old codebase")
async def test_apply_multiple_allocations(
    mock_env, mock_request_channel, mock_event_bus, capsys
):
    """Test multiple consecutive allocations being applied."""
    # Two allocation blocks, then exhaustion
    allocations = [["Allocation_1"], ["Allocation_2"]]

    allocator = Allocator(mock_env, allocations, mock_request_channel, mock_event_bus)

    # First allocation
    await allocator.apply_next_allocation()
    captured = capsys.readouterr()
    assert f"[{mock_env.now}] Applying allocation block" in captured.out

    # Second allocation
    await allocator.apply_next_allocation()
    captured = capsys.readouterr()
    assert f"[{mock_env.now}] Applying allocation block" in captured.out

    # No more allocations
    await allocator.apply_next_allocation()
    captured = capsys.readouterr()
    assert f"[{mock_env.now}] No more allocations available." in captured.out
