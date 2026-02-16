from __future__ import annotations

import random
from typing import Callable, TYPE_CHECKING

import asimpy
import pluggy

from nuberu.plugins import PluginBase
from nuberu.core.events import EventTopic

if TYPE_CHECKING:
    from nuberu.channels import Channel
    from nuberu.components.container import Container
    from nuberu.components.registry import Registry
    from nuberu.core.events import EventBus
    from nuberu.workload.request import Request

hookimpl = pluggy.HookimplMarker("nuberu")


class LoadBalancerWeighted:
    """
    LoadBalancer distributes incoming requests to the appropriate containers
    based on the specified load balancing policy.

    Args:
        env (asimpy.Environment): SimPy environment for simulation.
        registry (Registry): Registry to get containers for apps.
        event_bus (EventBus): Event bus for communication between components.
        request_channel (Channel): Channel to receive incoming requests.
    """

    env: asimpy.Environment
    registry: Registry
    event_bus: EventBus
    request_channel: Channel
    current_index: int

    def __init__(
        self,
        env: asimpy.Environment,
        registry: Registry,
        event_bus: EventBus,
        request_channel: Channel,
    ) -> None:
        self.env = env
        self.registry = registry  # Registry to get containers for apps
        self.event_bus = event_bus
        self.request_channel = request_channel  # Channel to receive requests

    def select_container(self, request: Request) -> Container | None:
        """
        Select a container based on the current load balancing policy.

        Args:
            request (Request): The incoming request to be assigned

        Returns:
            Container | None: The selected container or None if no containers are available or if the app is not found.
        """
        if request.app is None:
            return None

        valid_containers = self.registry.get_containers(request.app.name)

        if not valid_containers:
            return None

        return self._weighted_selection(containers=valid_containers)

    def _weighted_selection(self, containers: list[Container]) -> Container | None:
        """
        Select a container using a weighted random selection algorithm based on container RPS (requests per second).

        Args:
            containers (list[Container]): List of available containers.

        Returns:
            Container | None: The selected container or None if total RPS is zero.
        """
        # 1) For each container, extract its RPS as a float
        perfs = []
        for c in containers:
            rps = c.rps
            perfs.append(rps)

        total_rps = sum(perfs)
        if total_rps > 0.0:
            # 2) Build a list of normalized weights
            weights = [p / total_rps for p in perfs]
            # 3) Randomly choose a container, with probability = weight_i
            #    random.choices returns a list, take [0]
            chosen = random.choices(containers, weights=weights, k=1)[0]
            return chosen
        return None

    async def run(self) -> None:
        """
        Continuously receive requests and assign them to containers based on the load balancing policy.
        """
        while True:
            # Receive incoming requests
            request: Request = await self.request_channel.receive()
            self.logger.info(f"Received request {request.id} for app {request.app}")

            container = self.select_container(request)
            if container is None:
                if request.set_request_rejected():
                    self.event_bus.publish(
                        topic=EventTopic.REQUEST_REJECTED,
                        payload={
                            "request_id": request.id,
                            "app_id": request.app.name if request.app else "unknown",
                            "reason": "no container available",
                            "time": self.env.now,
                            "timeline": [ts.to_dict() for ts in request.timeline],
                        },
                        origin="LoadBalancer",
                    )
                    self.logger.warning(
                        f"No container available for request {request.id}! Request dropped."
                    )
                continue

            assert container is not None  # For mypy
            assert request.app is not None  # Also for mypy

            await container.handle_incoming_request(request)


class LoadBalancerWeightedPlugin(PluginBase):
    """
    Plugin that implements the get_load_balancer_factory hook,
    returning a factory function that creates LoadBalancerWeighted instances.
    """

    plugin_name = "weighted_load_balancer"

    def __init__(self):
        super().__init__()

    @hookimpl
    def get_load_balancer_factory(self, config: dict) -> Callable:
        """Return factory for creating LoadBalancerWeighted instances."""
        return self._create_weighted_load_balancer

    def _create_weighted_load_balancer(
        self,
        env: asimpy.Environment,
        registry: Registry,
        event_bus: EventBus,
        request_channel: Channel,
    ) -> LoadBalancerWeighted:
        """Factory method for creating LoadBalancerWeighted instances."""
        return LoadBalancerWeighted(
            env, registry, event_bus, request_channel, logger=self.logger
        )
