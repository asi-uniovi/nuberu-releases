from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

import asimpy
import pluggy

from nuberu.channels import MultiChannelReceiver
from nuberu.core.events import EventTopic, Signal, BlockingFlag

# EOT sentinel replaced by channel.close() - receive returns None when closed
from nuberu.workload.timeline import RequestTimestamp
from nuberu.plugins import PluginBase

if TYPE_CHECKING:
    from nuberu.channels import DuplexChannel
    from nuberu.core.events import EventBus
    from nuberu.workload.request import Request
    from nuberu.components.container import Container
    from nuberu.components.registry import Registry

hookimpl = pluggy.HookimplMarker("nuberu")


class LoadBalancer:
    """
    LoadBalancer distributes incoming requests to the appropriate containers
    based on the specified load balancing policy.

    Args:
        env (asimpy.Environment): SimPy environment for simulation.
        registry (Registry): Registry to get containers for apps.
        event_bus (EventBus): Event bus for communication between components.
        wi_duplex_channel (DuplexChannel): Bidirectional channel with WorkloadInjector.
        policy (str): Load balancing policy to apply (default is "round_robin").
    """

    env: asimpy.Environment
    registry: Registry
    event_bus: EventBus
    wi_duplex_channels: dict[str, DuplexChannel]
    policy: str
    current_index: dict[str, int]

    def __init__(
        self,
        env: asimpy.Environment,
        registry: Registry,
        event_bus: EventBus,
        wi_duplex_channels: dict[str, DuplexChannel],
        policy: str = "round_robin",
        lb_id: str = "lb-1",
        logger: logging.Logger | None = None,
    ) -> None:
        self.env = env
        self.registry = registry  # Registry to get containers for apps
        self.event_bus = event_bus
        self.wi_duplex_channels = (
            wi_duplex_channels  # Per-app bidirectional channels with WorkloadInjector
        )
        self.policy = policy
        self.current_index = {}  # Dictionary to track the current index per app for round-robin
        self.lb_id = lb_id  # LoadBalancer identifier for tracking
        self.logger = logger or logging.getLogger(__name__)

        # Pending requests tracking: container_id -> count of inflight requests
        # Only containers with pending requests will be listened to for responses
        self._pending_requests: dict[str, int] = {}

        # --- Container DuplexChannel Management ---
        # We maintain two dictionaries for efficiency:
        #
        # 1. _available_duplex_channels: ALL containers registered via Registry
        #    - Populated when CONTAINER_READY event is received
        #    - Removed when CONTAINER_REMOVED event is received
        #    - This is the "pool" of containers we COULD route to
        #
        # 2. _active_duplex_channels: SUBSET of available, only those with pending requests
        #    - Added when first request is sent to a container
        #    - Removed when container channel is closed (receive returns None)
        #    - This is the set we ACTIVELY LISTEN to for responses
        #    - Optimization: avoids creating receive events for idle containers
        #
        self._available_duplex_channels: dict[str, DuplexChannel] = {}
        self._active_duplex_channels: dict[str, DuplexChannel] = {}
        self._registry_queue: asimpy.Store = asimpy.Store(env)
        self._end_sim_queue = asimpy.Store(env)

        # Subscribe to Registry events to maintain available response channels
        self.event_bus.subscribe(EventTopic.CONTAINER_READY, self._registry_queue)
        self.event_bus.subscribe(EventTopic.CONTAINER_REMOVED, self._registry_queue)
        self.event_bus.subscribe(EventTopic.END_SIMULATION, self._end_sim_queue)

        # Signal objects
        self._work_signal = Signal(env)  # For new active channels (auto-reset)
        self._end_sim_signal = BlockingFlag(env)  # For end of simulation

        self._registry_listener = self.env.process(self._listen_registry_events())
        self._response_process = self.env.process(self._route_responses())
        self.env.process(self._listen_end_sim())

        # ToDo: Initiate the load balancer process (run()) in other component
        # like the main simulation component (Simulation).
        # env.process(self.run())

    async def _listen_end_sim(self):
        """Captures END_SIMULATION and triggers the local signal"""
        await self._end_sim_queue.get()
        self._end_sim_signal.set()

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

        if self.policy == "round_robin":
            if request.app.name not in self.current_index:
                self.current_index[request.app.name] = 0
            return self._round_robin(
                containers=valid_containers, app_name=request.app.name
            )
        elif self.policy == "least_loaded":
            return self._least_loaded(containers=valid_containers)
        raise ValueError(f"[{self.env.now}] [LB] Unsupported policy: {self.policy}")

    def _round_robin(
        self, containers: list[Container], app_name: str
    ) -> Container | None:
        """
        Select a container using the round-robin policy.

        Returns:
            Container | None: The selected container or None if no containers are available.
        """
        container = containers[self.current_index[app_name] % len(containers)]
        self.current_index[app_name] += 1
        return container

    def _least_loaded(self, containers: list[Container]) -> Container | None:
        """
        Select the container with the least current load.

        Returns:
            Container | None: The container with the least load or None if no containers are available.
        """
        return min(containers, key=lambda c: c.current_load)

    async def run(self) -> None:
        """
        Continuously receive requests and assign them to containers based on the load balancing policy.
        Receives from WorkloadInjector via per-app DuplexChannels (forward direction).

        Uses MultiChannelReceiver to wait for requests from any app's channel.

        Note: This loop terminates when interrupted (asimpy.Interrupt) or when
        the simulation environment stops executing (EmptySchedule).
        """
        receiver = MultiChannelReceiver(self.env, self.wi_duplex_channels, "forward")

        try:
            while not receiver.is_exhausted:
                app_name, message = await receiver.receive_any()

                # Channel closed or all exhausted
                if message is None:
                    if app_name:
                        self.logger.debug(
                            f"LoadBalancer {self.lb_id} WI channel for {app_name} closed"
                        )
                    continue

                request: Request = message

                # Timeline: LoadBalancer receives request from WorkloadInjector
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id=f"LoadBalancer_{self.lb_id}",
                        event="receive_from_wi",
                        source_id="WorkloadInjector",
                    )
                )
                # Timeline: LoadBalancer received request
                request.add_timeline_entry(f"LB_{self.lb_id}_receive", self.env.now)

                self.logger.info(f"Received request {request.id} for app {request.app}")

                container = self.select_container(request)
                if container is None:
                    if request.set_request_rejected(reason="no_container"):
                        self.event_bus.publish(
                            topic=EventTopic.REQUEST_REJECTED,
                            payload={
                                "request_id": request.id,
                                "app_id": request.app.name
                                if request.app
                                else "unknown",
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

                # Track pending request for this container
                container_id = container.container_id

                # Mark request with assigned container for efficient response routing
                request.set_assigned_container(container_id)

                if container_id not in self._pending_requests:
                    self._pending_requests[container_id] = 0
                    # First request to this container - add to active DuplexChannels
                    if container_id in self._available_duplex_channels:
                        self._active_duplex_channels[container_id] = (
                            self._available_duplex_channels[container_id]
                        )
                        self.logger.debug(
                            f"LoadBalancer {self.lb_id} started listening to container {container_id} (first pending request)"
                        )
                        self._work_signal.set()  # Signal for the _route_responses() loop

                self._pending_requests[container_id] += 1

                # Send request to container via DuplexChannel (forward direction)
                if container.lb_duplex_channel:
                    # Timeline: LoadBalancer sends request to Container
                    request.add_timeline_entry(
                        f"LB_{self.lb_id}_send_to_{container_id}", self.env.now
                    )

                    await container.lb_duplex_channel.send_forward(request)
                    self.logger.debug(
                        f"LoadBalancer sent request {request.id} to container {container_id} via DuplexChannel"
                    )
                else:
                    self.logger.error(
                        f"Container {container_id} has no lb_duplex_channel configured, dropping request {request.id}"
                    )

            self.logger.debug(f"LoadBalancer {self.lb_id} run() all channels closed")
        except asimpy.Interrupt:
            self.logger.info(f"LoadBalancer {self.lb_id} run() interrupted")
            return

    async def _listen_registry_events(self) -> None:
        """
        Listen to Registry events (CONTAINER_READY, CONTAINER_REMOVED) and maintain
        the _container_response_channels dictionary in sync.

        This ensures we always have an up-to-date set of response channels without
        polling or reconstructing the list on every iteration.
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
                        f"LoadBalancer {self.lb_id} registered available DuplexChannel for container {container.container_id}"
                    )

                    # FIX: If we already have pending requests for this container (race condition where
                    # run() selected the container before we processed this event), we must start
                    # listening immediately.
                    if self._pending_requests.get(container.container_id, 0) > 0:
                        if container.container_id not in self._active_duplex_channels:
                            self._active_duplex_channels[container.container_id] = (
                                container.lb_duplex_channel
                            )
                            self.logger.debug(
                                f"LoadBalancer {self.lb_id} started listening to container {container.container_id} (late bind - pending requests > 0)"
                            )
                            self._work_signal.set()  # Signal for the _route_responses() loop
                else:
                    self.logger.warning(
                        f"Container {container.container_id} is READY but has no lb_duplex_channel configured"
                    )

            elif event.topic == EventTopic.CONTAINER_REMOVED:
                # Remove container from available channels and drain any pending responses
                if container.container_id in self._available_duplex_channels:
                    del self._available_duplex_channels[container.container_id]
                    self.logger.debug(
                        f"LoadBalancer {self.lb_id} removed available DuplexChannel for container {container.container_id}"
                    )

                if container.container_id in self._active_duplex_channels:
                    del self._active_duplex_channels[container.container_id]

                if container.container_id in self._pending_requests:
                    # After draining, any remaining "pending" count represents requests
                    # that were never processed by the container (truly lost)
                    remaining = self._pending_requests[container.container_id]
                    if remaining > 0:
                        self.logger.warning(
                            f"Container {container.container_id} removed with {remaining} truly orphaned request(s)"
                        )
                    del self._pending_requests[container.container_id]

    async def _route_responses(self) -> None:
        """
        Continuously receive responses from Containers and route them back to WorkloadInjector.

        This method implements the backward flow of the bidirectional request-response
        pattern. It ONLY listens to containers that have pending requests, making it
        highly efficient:

        Efficiency benefits:
        - Only creates receive() operations for containers with inflight requests
        - Automatically stops listening when all requests from a container are completed
        - No wasted resources on idle containers

        Tracking mechanism:
        - _pending_requests: counter of inflight requests per container
        - _active_duplex_channels: channels we're actively listening to
        - When channel closes, remove from active channels

        Crash handling:
        - If container crashes with pending requests, _listen_registry_events() removes it
        - Orphaned requests are detected by pending counter mismatch
        """
        # Create receiver referencing the dynamic _active_duplex_channels dict
        # As run() adds/removes channels, the receiver sees changes automatically
        receiver = MultiChannelReceiver(
            self.env, self._active_duplex_channels, "backward"
        )

        try:
            while True:
                # Check if exhausted before receiving
                if receiver.is_exhausted:
                    if self._end_sim_signal.is_set:
                        self.logger.debug(
                            f"LoadBalancer {self.lb_id} _route_responses exiting (simulation ended & no active channels)"
                        )
                        return

                    # Wait for EITHER new work OR end of simulation
                    # We pass the underlying SimPy events to AnyOf
                    events = [self._work_signal.event, self._end_sim_signal.event]
                    await asimpy.AnyOf(self.env, events)

                    # Just recreate the work signal if it was triggered.
                    self._work_signal.reset()

                    continue

                container_id, message = await receiver.receive_any()

                # Channel closed
                if message is None:
                    if container_id:
                        self.logger.debug(
                            f"LoadBalancer {self.lb_id} channel closed by container {container_id}"
                        )
                        # Clean up pending requests tracking
                        if container_id in self._pending_requests:
                            del self._pending_requests[container_id]
                        # Remove from active channels (receiver handles its internal state)
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
                        component_id=f"LoadBalancer_{self.lb_id}",
                        event="receive_from_container",
                        source_id=req_container_id,
                    )
                )

                self.logger.debug(
                    f"LoadBalancer {self.lb_id} received response for request {request.id}, routing back to WorkloadInjector"
                )

                # Timeline: LoadBalancer sends response back to WorkloadInjector
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id=f"LoadBalancer_{self.lb_id}",
                        event="send_to_wi",
                        target_id="WorkloadInjector",
                    )
                )

                # Route response back to WorkloadInjector via app-specific channel (backward)
                app_name = request.app.name if request.app else None
                if app_name and app_name in self.wi_duplex_channels:
                    await self.wi_duplex_channels[app_name].send_backward(request)
                else:
                    self.logger.error(
                        f"Cannot route response for {request.id}: unknown app {app_name}"
                    )
        except Exception as e:
            self.logger.exception(f"LoadBalancer._route_responses CRASHED: {e}")
            raise


class LoadBalancerPlugin(PluginBase):
    """
    Plugin that implements the get_load_balancer_factory hook,
    returning a factory function that creates LoadBalancer instances.
    """

    plugin_name = "load_balancer"

    def __init__(self):
        super().__init__()

    @hookimpl
    def get_load_balancer_factory(self, config: dict) -> Callable:
        """Return factory for creating LoadBalancer instances."""
        return self._create_load_balancer_factory(config)

    def _create_load_balancer_factory(self, config: dict) -> Callable:
        """Create a factory that passes the plugin's logger to LoadBalancer."""
        policy = config.get("policy", "round_robin")
        lb_id = config.get("lb_id", "lb-1")

        def factory(
            env: asimpy.Environment,
            registry: Registry,
            event_bus: EventBus,
            wi_duplex_channels: dict[str, DuplexChannel],
        ) -> LoadBalancer:
            return LoadBalancer(
                env=env,
                registry=registry,
                event_bus=event_bus,
                wi_duplex_channels=wi_duplex_channels,
                policy=policy,
                lb_id=lb_id,
                logger=self.logger,
            )

        return factory
