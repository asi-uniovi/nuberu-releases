from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nuberu.core.events import EventBus, EventTopic

if TYPE_CHECKING:
    from typing import Iterable, Iterator

    import asimpy

    from ..channels import Channel

logger = logging.getLogger(__name__)


class NoMoreAllocations(Exception):
    """Raised when the allocation iterator is exhausted."""

    pass


class Allocator:
    """
    Component responsible for applying the next allocation in the system.

    Attributes:
        allocation_iterator: An instance of AllocationSpecs providing the next allocation.
    """

    def __init__(
        self,
        env: asimpy.Environment,
        allocations: Iterable,
        channel: Channel,
        event_bus: EventBus,
        eager_start: bool = False,
        allocator_interval: float = 250.0,  # Default interval for applying allocations (s)
    ):
        """
        Initializes the Allocator with an AllocationSpecs iterator.

        Args:
            env: The simulation environment.
            allocations: An iterable providing allocation data.
            channel: Communication channel to send instructions to InfrastructureManager.
            event_bus: Event bus for communication between components.
            eager_start: If True, applies the first allocation immediately.
            allocator_interval: Time interval in seconds between allocation attempts.
        """
        self.env = env
        self._allocations: Iterator = iter(allocations)
        self.channel = channel
        self.event_bus = event_bus
        self._eager = eager_start
        self._next_timeout = allocator_interval

    async def run(self) -> None:
        if self._eager:
            # Eager start: Applies the first allocation immediately if eager_start is True.
            try:
                await self.apply_next_allocation()
                logger.info("Initial allocation applied (eager-start).")
            except NoMoreAllocations:
                logger.debug("No initial allocations available.")
        else:
            # Continuously applies allocations until NoMoreAllocations is raised,
            # at which point the loop breaks and the simulation can finish.
            # Every self._next_timeout seconds, it attempts the next allocation.
            while True:
                try:
                    await self.apply_next_allocation()
                except NoMoreAllocations:
                    logger.debug("Allocator exhausted; leaving loop.")
                    break
                await self.env.timeout(self._next_timeout)

    async def apply_next_allocation(self) -> None:
        """
        Applies the next allocation to the system.

        Retrieves the next allocation (a list of instructions) and applies it one by one.
        """
        try:
            allocation_block: list = next(self._allocations)
            self.event_bus.publish(
                topic=EventTopic.ALLOCATION_RECEIVED,
                payload={
                    "number_of_instr": len(allocation_block),
                    "time": self.env.now,
                },
                origin="Allocator",
            )

            logger.info(
                f"Applying allocation block with {len(allocation_block)} instructions",
            )
            # ToDo: Here we would apply the logic to modify the system (start VMs, move containers, etc.)
            # ToDo: Define the communication protocol between Allocator and InfrastructureManager
            await self.channel.send(allocation_block)
            self.event_bus.publish(
                topic=EventTopic.ALLOCATION_APPLIED,
                payload={
                    "number_of_instr": len(allocation_block),
                    "time": self.env.now,
                },
                origin="Allocator",
            )

        except StopIteration:
            logger.error(
                "No more allocations available.",
            )
            raise NoMoreAllocations(
                f"No more allocations available at time {self.env.now}"
            )
