from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING
from fractions import Fraction
import math

import asimpy
import pluggy

from nuberu.channels import MultiChannelReceiver
from nuberu.core.events import EventTopic, Signal, BlockingFlag
from nuberu.workload.timeline import RequestTimestamp
from nuberu.plugins import PluginBase

if TYPE_CHECKING:
    from nuberu.channels import DuplexChannel
    from nuberu.components.container import Container
    from nuberu.components.registry import Registry
    from nuberu.core.events import EventBus
    from nuberu.workload.request import Request

hookimpl = pluggy.HookimplMarker("nuberu")


class LoadBalancerSmoothWRR:
    env: asimpy.Environment
    registry: Registry
    event_bus: EventBus
    wi_duplex_channels: dict[str, DuplexChannel]

    def __init__(
        self,
        env: asimpy.Environment,
        registry: Registry,
        event_bus: EventBus,
        wi_duplex_channels: dict[str, DuplexChannel],
        logger: logging.Logger | None = None,
    ) -> None:
        self.env = env
        self.registry = registry
        self.event_bus = event_bus
        self.wi_duplex_channels = wi_duplex_channels
        self.logger = logger or logging.getLogger(__name__)

        # Per app: containers, weights, current_weights
        self.state: dict[str, dict[str, list]] = {}

        # Tracking pending requests: container_id -> count
        self._pending_requests: dict[str, int] = {}

        # Active duplex channels for containers with pending requests
        self._active_duplex_channels: dict[str, DuplexChannel] = {}

        # All available container duplex channels (from Registry)
        self._available_duplex_channels: dict[str, DuplexChannel] = {}
        self._registry_queue: asimpy.Store = asimpy.Store(env)

        # Subscribe to Registry events to maintain available response channels
        self.event_bus.subscribe(EventTopic.CONTAINER_READY, self._registry_queue)
        self.event_bus.subscribe(EventTopic.CONTAINER_REMOVED, self._registry_queue)

        # Signal objects
        self._work_signal = Signal(env)  # For new active channels (auto-reset)
        self._end_sim_signal = BlockingFlag(env)  # For end of simulation

        self._end_sim_queue = asimpy.Store(env)
        self.event_bus.subscribe(EventTopic.END_SIMULATION, self._end_sim_queue)
        self.env.process(self._listen_end_sim())

        # Start processes
        self._registry_listener = self.env.process(self._listen_registry_events())
        self._response_process = self.env.process(self._route_responses())

    async def _listen_end_sim(self):
        """Captures END_SIMULATION and triggers the local signal"""
        await self._end_sim_queue.get()
        self._end_sim_signal.set()

    def _init_app_state(self, app_name: str, containers: list[Container]) -> None:
        """
        Initialize internal SWRR state for a given app.

        This method is called once per app (or when its container list changes).
        It assigns each container a static weight based on its estimated throughput (RPS),
        initializes current weights to zero, and stores the total sum of weights.

        Args:
            app_name (str): Name of the application.
            containers (list[Container]): List of active containers for the app.
        """
        # Get rps of all containers
        rps_list = [c.rps for c in containers]

        min_rps = min(rps_list)
        if min_rps <= 0:  # Avoid division by zero or negative weights
            min_rps = 1e-6

        ratios = [rps / min_rps for rps in rps_list]

        # Scale ratios to integer weights, with a tolerance of eps
        eps = 0.005

        # Convert ratios to fractions and round them to integers
        fracs = [Fraction(r).limit_denominator(int(1 / eps)) for r in ratios]

        # Find the least common multiple of all denominators to scale them
        # This ensures that weights are integers and maintain the ratio
        K = math.lcm(*(f.denominator for f in fracs))

        weights = [f.numerator * (K // f.denominator) for f in fracs]
        current_weights = [0 for _ in containers]
        self.state[app_name] = {
            "containers": containers,
            "weights": weights,
            "current_weights": current_weights,
            "total_weight": sum(weights),
        }
        # self.logger.debug(
        #     f"Initialized SWRR state for app '{app_name}': "
        #     f"{len(containers)} containers, weights: {weights}, current_weights: {current_weights}, "
        #     f"total_weight: {self.state[app_name]['total_weight']}"
        # )

    def select_container(self, request: Request) -> Container | None:
        """
        Select a container for the incoming request using Smooth Weighted Round Robin.

        Args:
            request (Request): The incoming request to be routed.

        Returns:
            Container | None: The selected container or None if no container is available.
        """
        if request.app is None:
            return None

        app_name = request.app.name
        containers = self.registry.get_containers(app_name)
        if not containers:
            return None

        # ToDo: This way of checking if the list changed is not robust, and I don't like it.
        # For now I'll leave it like this, but it should be improved.
        if app_name not in self.state or len(self.state[app_name]["containers"]) != len(
            containers
        ):
            self._init_app_state(app_name, containers)

        # Retrieve the current state for the app
        s = self.state[app_name]
        weights = s["weights"]  # Static weights based on RPS
        current_weights = s[
            "current_weights"
        ]  # Accumulated "priority" of each container
        total_weight = s["total_weight"]  # Sum of all weights (used as penalty)

        # Update current_weight for each container
        for i in range(len(containers)):
            current_weights[i] += weights[i]
            # This simulates the "accumulated right to be chosen" over time

        # Select the container with the highest accumulated weight
        max_index = current_weights.index(max(current_weights))

        # Penalize the selected container to avoid consecutive selections
        current_weights[max_index] -= total_weight
        # This ensures a fair, smooth distribution over time
        # self.logger.debug(f"State for app '{app_name}': Selected container index: {max_index}")
        return self.state[app_name]["containers"][max_index]

    async def run(self) -> None:
        """
        Continuously receive requests and assign them to containers based on the load balancing policy.
        Receives from WorkloadInjector via per-app DuplexChannels (forward direction).
        Uses AnyOf to wait for requests from any app's channel.
        """
        try:
            pending_events: dict[str, asimpy.Event] = {}
            active_channels = dict(self.wi_duplex_channels)

            while active_channels:
                for app_name, channel in active_channels.items():
                    if app_name not in pending_events:
                        pending_events[app_name] = channel.receive_forward_event()

                if not pending_events:
                    break

                condition = asimpy.AnyOf(self.env, list(pending_events.values()))
                results = await condition

                for winner_event, message in results.items():
                    try:
                        winner_app = next(
                            app
                            for app, evt in pending_events.items()
                            if evt is winner_event
                        )
                    except StopIteration:
                        continue

                    del pending_events[winner_app]

                    if message is None:
                        self.logger.debug(
                            f"LoadBalancer smoothWRR WI channel for {winner_app} closed"
                        )
                        if winner_app in active_channels:
                            del active_channels[winner_app]
                        continue

                    request: Request = message

                    request.timeline.append(
                        RequestTimestamp(
                            time=self.env.now,
                            component_id="LoadBalancer_smoothWRR",
                            event="receive_from_wi",
                            source_id="WorkloadInjector",
                        )
                    )

                    self.logger.info(
                        f"Received request {request.id} for app {request.app}"
                    )

                    container = self.select_container(request)
                    if container is None:
                        if request.set_request_rejected():
                            self.event_bus.publish(
                                topic=EventTopic.REQUEST_REJECTED,
                                payload={
                                    "request_id": request.id,
                                    "app_id": request.app.name
                                    if request.app
                                    else "unknown",
                                    "reason": "no container available",
                                    "time": self.env.now,
                                    "timeline": [
                                        ts.to_dict() for ts in request.timeline
                                    ],
                                },
                                origin="LoadBalancer",
                            )
                            self.logger.warning(
                                f"No container available for request {request.id}! Request dropped."
                            )
                        continue

                    assert container is not None
                    assert request.app is not None

                    container_id = container.container_id
                    request.set_assigned_container(container_id)

                    if container_id not in self._pending_requests:
                        self._pending_requests[container_id] = 0
                        if container_id in self._available_duplex_channels:
                            self._active_duplex_channels[container_id] = (
                                self._available_duplex_channels[container_id]
                            )
                            self.logger.debug(
                                f"LoadBalancer smoothWRR started listening to container {container_id} (first pending request)"
                            )
                            self._work_signal.set()

                    self._pending_requests[container_id] += 1

                    if container.lb_duplex_channel:
                        request.timeline.append(
                            RequestTimestamp(
                                time=self.env.now,
                                component_id="LoadBalancer_smoothWRR",
                                event="send_to_container",
                                target_id=container_id,
                                metadata={"vm_id": container.vm.vm_id},
                            )
                        )

                        await container.lb_duplex_channel.send_forward(request)
                        self.logger.debug(
                            f"LoadBalancer smoothWRR sent request {request.id} to container {container_id} via DuplexChannel"
                        )
                    else:
                        self.logger.error(
                            f"Container {container_id} has no lb_duplex_channel configured, dropping request {request.id}"
                        )

            self.logger.debug("LoadBalancer smoothWRR run() all channels closed")
        except asimpy.Interrupt:
            self.logger.info("LoadBalancer smoothWRR run() interrupted")
            return

    async def _listen_registry_events(self) -> None:
        """
        Listen to Registry events (CONTAINER_READY, CONTAINER_REMOVED) and maintain
        the _available_duplex_channels dictionary in sync.
        """
        while True:
            event = await self._registry_queue.get()
            container_obj = event.payload.get("container")

            if not hasattr(container_obj, "container_id"):
                continue

            container: Container = container_obj

            if event.topic == EventTopic.CONTAINER_READY:
                # Add container's DuplexChannel to available channels
                if container.lb_duplex_channel is not None:
                    self._available_duplex_channels[container.container_id] = (
                        container.lb_duplex_channel
                    )
                    self.logger.debug(
                        f"LoadBalancer smoothWRR registered available DuplexChannel for container {container.container_id}"
                    )

                    # FIX: Late binding check
                    if self._pending_requests.get(container.container_id, 0) > 0:
                        if container.container_id not in self._active_duplex_channels:
                            self._active_duplex_channels[container.container_id] = (
                                container.lb_duplex_channel
                            )
                            self.logger.debug(
                                f"LoadBalancer smoothWRR started listening to container {container.container_id} (late bind - pending requests > 0)"
                            )
                            self._work_signal.set()
                else:
                    self.logger.warning(
                        f"Container {container.container_id} is READY but has no lb_duplex_channel configured"
                    )

            elif event.topic == EventTopic.CONTAINER_REMOVED:
                # Remove container from available channels
                if container.container_id in self._available_duplex_channels:
                    del self._available_duplex_channels[container.container_id]
                    self.logger.debug(
                        f"LoadBalancer smoothWRR removed available DuplexChannel for container {container.container_id}"
                    )

                # If it had pending requests, clean up
                if container.container_id in self._pending_requests:
                    pending_count = self._pending_requests[container.container_id]
                    self.logger.warning(
                        f"Container {container.container_id} removed with {pending_count} pending request(s) - requests will be orphaned"
                    )
                    del self._pending_requests[container.container_id]
                    if container.container_id in self._active_duplex_channels:
                        del self._active_duplex_channels[container.container_id]

    async def _route_responses(self) -> None:
        """
        Continuously receive responses from Containers and route them back to WorkloadInjector.
        Uses MultiChannelReceiver for efficient concurrent waiting.
        """
        try:
            receiver = MultiChannelReceiver(
                self.env, self._active_duplex_channels, "backward"
            )

            while True:
                # If no active channels, wait for work signal or end of sim
                if receiver.is_exhausted:
                    if self._end_sim_signal.is_set:
                        self.logger.debug(
                            "LoadBalancer smoothWRR _route_responses exiting (simulation ended & no active channels)"
                        )
                        return

                    # Wait for EITHER new work OR end of simulation
                    events = [self._work_signal.event, self._end_sim_signal.event]
                    await asimpy.AnyOf(self.env, events)
                    self._work_signal.reset()
                    continue

                container_id, message = await receiver.receive_any()

                if message is None:
                    # null message means channel closed or exhausted
                    if container_id:
                        self.logger.debug(
                            f"LoadBalancer smoothWRR channel closed by container {container_id}"
                        )
                        if container_id in self._pending_requests:
                            del self._pending_requests[container_id]
                        if container_id in self._active_duplex_channels:
                            del self._active_duplex_channels[container_id]
                    continue

                # Regular request processing
                request = message

                # Get container_id directly from the request
                req_container_id = request.get_assigned_container() or container_id

                # Decrement pending request counter
                if req_container_id and req_container_id in self._pending_requests:
                    self._pending_requests[req_container_id] -= 1

                # Timeline: LoadBalancer receives response from Container
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id="LoadBalancer_smoothWRR",
                        event="receive_from_container",
                        source_id=req_container_id,
                    )
                )

                self.logger.debug(
                    f"LoadBalancer smoothWRR received response for request {request.id}, routing back to WorkloadInjector"
                )

                # Timeline: LoadBalancer sends response back to WorkloadInjector
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id="LoadBalancer_smoothWRR",
                        event="send_to_wi",
                        target_id="WorkloadInjector",
                    )
                )

                # Route response back to WorkloadInjector via app-specific channel
                app_name = request.app.name if request.app else None
                if app_name and app_name in self.wi_duplex_channels:
                    await self.wi_duplex_channels[app_name].send_backward(request)
                else:
                    self.logger.error(
                        f"Cannot route response for {request.id}: unknown app {app_name}"
                    )

        except asimpy.Interrupt:
            self.logger.info("LoadBalancer smoothWRR _route_responses() interrupted")
            return


class LoadBalancerSmoothWRRPlugin(PluginBase):
    """
    Plugin that implements the get_load_balancer_factory hook,
    returning a factory function that creates LoadBalancerSmoothWRR instances.
    """

    plugin_name = "smoothwrr_load_balancer"

    def __init__(self):
        super().__init__()

    @hookimpl
    def get_load_balancer_factory(self, config: dict) -> Callable:
        """Return factory for creating LoadBalancerSmoothWRR instances."""
        return self._create_load_balancer

    def _create_load_balancer(
        self,
        env: asimpy.Environment,
        registry: Registry,
        event_bus: EventBus,
        wi_duplex_channels: dict[str, DuplexChannel],
    ) -> LoadBalancerSmoothWRR:
        """Factory method that creates LoadBalancerSmoothWRR with plugin's logger."""
        return LoadBalancerSmoothWRR(
            env=env,
            registry=registry,
            event_bus=event_bus,
            wi_duplex_channels=wi_duplex_channels,
            logger=self.logger,
        )
