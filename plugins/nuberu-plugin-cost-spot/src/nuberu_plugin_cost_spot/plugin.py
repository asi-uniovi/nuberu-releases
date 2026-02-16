from dataclasses import dataclass
import logging
from typing import Callable

import asimpy
import pluggy

from nuberu.interfaces.protocols import CostModelProtocol
from nuberu.components.vm import VM
from nuberu.core.events import EventBus, EventTopic
from nuberu.plugins import PluginBase

hookimpl = pluggy.HookimplMarker("nuberu")


@dataclass(frozen=True)
class VMTracking:
    start_time: float
    instance_price: float


class SpotCostModel:
    """
    SpotCostModel tracks the accumulated cost of VM usage during the simulation.

    It subscribes to VM_STARTED and VM_STOPPED events to calculate the usage
    duration of each VM and accumulate the cost based on the hourly price
    defined by its InstanceClass.
    """

    env: asimpy.Environment
    event_bus: EventBus
    vm_tracking: dict[str, VMTracking]
    total_cost: float
    _event_queue: asimpy.Store
    logger: logging.Logger

    def __init__(
        self,
        env: asimpy.Environment,
        event_bus: EventBus,
        logger: logging.Logger | None = None,
    ):
        self.env: asimpy.Environment = env
        self.event_bus: EventBus = event_bus
        self.vm_tracking: dict[str, VMTracking] = {}
        self.total_cost: float = 0.0
        self.logger = logger or logging.getLogger(__name__)

        self._event_queue: asimpy.Store = asimpy.Store(env)

        self.event_bus.subscribe(EventTopic.VM_STARTED, self._event_queue)
        self.event_bus.subscribe(EventTopic.VM_STOPPED, self._event_queue)
        self.event_bus.subscribe(EventTopic.SIMULATION_FINISHED, self._event_queue)

    async def _listener(self) -> None:
        while True:
            event = await self._event_queue.get()
            if event.topic == EventTopic.VM_STARTED:
                self._handle_vm_started(event.payload)
            elif event.topic == EventTopic.VM_STOPPED:
                self._handle_vm_stopped(event.payload)
            elif event.topic == EventTopic.SIMULATION_FINISHED:
                self._handle_simulation_finished()

    def _handle_vm_started(self, payload: dict) -> None:
        vm: VM = payload["vm"]
        self.logger.debug(f"Received: VM {vm.vm_id} started")
        self.vm_tracking[vm.vm_id] = VMTracking(
            start_time=self.env.now,
            instance_price=vm.instance_class.price,
        )

    def _handle_vm_stopped(self, payload: dict) -> None:
        vm: VM = payload["vm"]
        self.logger.debug(f"Received: VM {vm.vm_id} stopped")
        tracking = self.vm_tracking.pop(vm.vm_id, None)
        if not tracking:
            self.logger.warning(f"Shutdown without previous record for VM {vm.vm_id}")
            return

        duration = self.env.now - tracking.start_time
        price_per_hour = tracking.instance_price

        # If simulation in seconds and price is $/hora, then:
        cost = (duration / 3600.0) * price_per_hour

        # If instead price is already in $/segundo (or if your simulator measures time in hours),
        # use directly: cost = duration * price
        self.total_cost += cost

    def _handle_simulation_finished(self) -> None:
        """Handle SIMULATION_FINISHED: calculate final cost and publish COST_FINAL."""
        # Calculate any remaining costs and publish the final total
        total = self.get_total_cost()
        self.event_bus.publish(
            topic=EventTopic.COST_FINAL,
            payload={
                "total_cost": total,
                "time": self.env.now,
            },
            origin=self.__class__.__name__,
        )
        self.logger.info(f"Total accumulated cost: {total}")

    def get_total_cost(self) -> float:
        """Calculate and return total cost. Does NOT publish events.

        This method calculates cost for any VMs still being tracked
        (their VM_STOPPED events may not have been processed yet).
        Event publishing is handled by _handle_simulation_finished().
        """
        for vm_id, tracking in list(self.vm_tracking.items()):
            duration = self.env.now - tracking.start_time
            price_per_hour = tracking.instance_price
            cost = (duration / 3600.0) * price_per_hour
            self.total_cost += cost
            self.logger.debug(
                f"Calculated pending cost for VM {vm_id}: "
                f"duration={duration:.1f}s, cost=${cost:.4f}"
            )
        self.vm_tracking.clear()
        return self.total_cost

    def run(self) -> None:
        self.logger.info(f"CostModel process started at {self.env.now}")
        self.env.process(self._listener())


class SpotCostModelPlugin(PluginBase):
    """
    Plugin that implements the get_cost_model_factory hook,
    returning a factory function that creates SpotCostModel instances.
    """

    plugin_name = "cost_spot"

    def __init__(self):
        super().__init__()

    @hookimpl
    def get_cost_model_factory(
        self, config: dict
    ) -> Callable[[asimpy.Environment, EventBus], CostModelProtocol]:
        """Return factory (constructor) for creating SpotCostModel instances."""
        return self._create_cost_model

    def _create_cost_model(
        self, env: asimpy.Environment, event_bus: EventBus
    ) -> CostModelProtocol:
        """Factory method that creates SpotCostModel with plugin's logger."""
        return SpotCostModel(env, event_bus, logger=self.logger)
