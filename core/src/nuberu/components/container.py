from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import asimpy

from ..channels import ChannelClosedError, DuplexChannel
from ..core.events import EventTopic

# Note: EOT sentinel replaced by channel.close_backward() semantics
from ..core.states import ContainerState
from ..interfaces.protocols import RuntimeModelProtocol
from ..utils.helpers import notify_event
from ..workload.timeline import RequestTimestamp

if TYPE_CHECKING:
    from ..components.vm import VM
    from ..core.events import EventBus
    from ..core.infrastructure import App, ContainerClass
    from ..workload.request import Request

logger = logging.getLogger(__name__)


class Container:
    """
    Container class represents a container that can process requests.
    It is associated with a specific VM and can be in different states (e.g., RUNNING, STOPPED).
    The container can accept requests based on its performance model and current load.

    Attributes:
        env (asimpy.Environment): The simulation environment.
        container_id (str): Unique identifier for the container.
        container_class (ContainerClass): The type of container.
        vm (VM): The VM where the container is hosted. Defaults to None.
        state (ContainerState): Current state of the container.
        runtime_duplex_channel (DuplexChannel): Bidirectional channel for RuntimeModel communication.
        lb_duplex_channel (DuplexChannel): Bidirectional channel for LoadBalancer communication.
        image_name (str): The image that this container will run.
        event_bus (EventBus): Event bus for communication between components.
        rps (float): Requests per second that the container can handle.
        _runtime_model (RuntimeModelProtocol): Instance of the runtime model (created by factory).
    """

    env: asimpy.Environment
    container_id: str
    container_class: ContainerClass
    vm: VM
    state: ContainerState
    image_name: str
    event_bus: EventBus
    rps: float

    # Internal attributes
    _runtime_model: RuntimeModelProtocol  # Created by runtime_model_factory

    def __init__(
        self,
        env: asimpy.Environment,
        container_id: str,
        container_class: ContainerClass,
        vm: VM,
        image_name: str,
        runtime_model_factory: Callable[
            [
                asimpy.Environment,
                "Container",
                float,
                EventBus,
                DuplexChannel,
                asimpy.Store,
                asimpy.Store,
            ],
            RuntimeModelProtocol,
        ],
        event_bus: EventBus,
        rps: float,
        vm_container_overhead: float = 0.0,
        drain_pending_requests: bool = True,
        drain_grace_period: float = 0.5,
    ):
        """
        Initialize a Container object.

        Args:
            env (asimpy.Environment): The simulation environment.
            container_id (str): Unique identifier for the container.
            container_class (ContainerClass): The type of container.
            vm (VM): The VM where the container is hosted. Defaults to None.
            image_name (str): The image that this container will run.
            runtime_model_factory (Callable): Factory function that creates runtime model instances.
            event_bus (EventBus): Event bus for communication between components.
            rps (float): Requests per second that the container can handle.
            vm_container_overhead (float): Container startup overhead in seconds (from network_delays config).
        """
        self.env = env
        self.container_id = container_id
        self.container_class = container_class
        self.vm = vm
        self.image_name = image_name
        self.event_bus = event_bus
        self.rps = rps
        self.drain_pending_requests = (
            drain_pending_requests  # Global simulation setting
        )
        self.drain_grace_period = drain_grace_period
        self.state: ContainerState = ContainerState.CREATED

        # Bidirectional channel for RuntimeModel communication
        # Forward: Container -> RuntimeModel (requests)
        # Backward: RuntimeModel -> Container (responses)
        # Apply vm_container_overhead for forward (startup overhead), backward is instantaneous
        self.runtime_duplex_channel: DuplexChannel = DuplexChannel(
            env=env,
            forward_delay=vm_container_overhead,
            backward_delay=0,  # Instantaneous (same process)
        )

        # Private idle signal for drain completion (point-to-point Container <-> RuntimeModel)
        self._runtime_idle_queue: asimpy.Store = asimpy.Store(env)
        # Private progress signal to detect forward progress during drain
        self._runtime_progress_queue: asimpy.Store = asimpy.Store(env)

        # Bidirectional channel for LoadBalancer communication
        # Forward: LoadBalancer -> Container (requests)
        # Backward: Container -> LoadBalancer (responses)
        # This will be set by InfrastructureManager/Builder during setup
        self.lb_duplex_channel: DuplexChannel | None = None

        # Start request listener process (receives from LoadBalancer)
        self._request_listener_process = self.env.process(self._listen_for_requests())

        # Create runtime model instance using the factory
        self._runtime_model = runtime_model_factory(
            env=self.env,
            container=self,
            performance=self.rps,
            event_bus=self.event_bus,
            duplex_channel=self.runtime_duplex_channel,
            idle_sink=self._runtime_idle_queue,
            progress_sink=self._runtime_progress_queue,
        )

        # Start the runtime model process
        self._runtime_process = self.env.process(self._runtime_model.run())

        # Start response propagation process
        self._response_process = self.env.process(self._propagate_responses())

    @property
    def current_load(self) -> float:
        """
        Calculates the current load of the container based on CPU and memory usage.

        Returns:
            float: A value between 0.0 (no load) and 1.0 (fully loaded).
        """
        cpu_usage: float = (self.cpu - self.available_cpu) / self.cpu
        memory_usage: float = (self.memory - self.available_memory) / self.memory
        return (cpu_usage + memory_usage) / 2

    @property
    def app(self) -> App:
        return self.container_class.app

    @property
    def cpu(self) -> float:
        """Returns the CPU capacity of the container based on its ContainerClass."""
        return self.container_class.cores

    @property
    def memory(self) -> float:
        """Returns the memory capacity of the container based on its ContainerClass."""
        return self.container_class.mem

    @property
    def available_cpu(self) -> float:
        """Returns the available CPU in the container."""
        return self.cpu  # - sum(request.cpu for request in self.processing_queue)

    @property
    def available_memory(self) -> float:
        """Returns the available memory in the container."""
        return self.memory  # - sum(request.memory for request in self.processing_queue)

    def start(self) -> None:
        """
        Start the container if it's not already running.
        Download the image if it's necessary.
        """
        allowed_states = {
            ContainerState.STOPPED,
            ContainerState.CREATED,
        }

        if self.state in allowed_states:
            if self.vm is not None and not self.vm.has_image(self.image_name):
                self.vm.add_image(self.image_name)
                logger.info(
                    f"[Container {self.container_id}] (cc:{self.container_class}) Downloaded Image '{self.image_name}' on VM {self.vm.vm_id}.",
                )

            self.state = ContainerState.RUNNING
            self.event_bus.publish(
                topic=EventTopic.CONTAINER_READY,
                payload={
                    "container": self,
                    "container_id": self.container_id,
                    "vm_id": self.vm.vm_id,
                    "time": self.env.now,
                },
                origin=self.container_id,
            )
            logger.debug(
                f"[Container {self.container_id}] (cc:{self.container_class}) Started on VM {self.vm.vm_id}.",
            )
            # CONTAINER_READY event is triggered in the VM class when the image is downloaded
        else:
            logger.error(
                f"[Container {self.container_id}] (cc:{self.container_class})  Cannot start. Container is already running.",
            )

    async def stop(self) -> None:
        """Stop the container, optionally draining pending requests.

        If drain_pending_requests is True:
        - Sets state to DRAINING
        - Waits for RuntimeModel to signal idle (queue empty)
        - Closes backward channel to signal no more responses to LoadBalancer

        If drain_pending_requests is False (hardstop):
        - Interrupts RuntimeModel immediately
        - Closes backward channel to signal no more responses to LoadBalancer
        """
        if self.state in (ContainerState.STOPPED, ContainerState.STOPPING):
            logger.debug(f"[Container {self.container_id}] already {self.state.value}")
            return

        if self.vm is None:
            logger.warning(f"[Container {self.container_id}] has no VM, cannot stop")
            return

        self.state = ContainerState.STOPPING
        vm_id = self.vm.vm_id

        if self.drain_pending_requests:
            # DRAIN MODE: Wait for RuntimeModel to finish processing all requests
            self.state = ContainerState.DRAINING

            # Log detailed drain state for debugging
            if hasattr(self._runtime_model, "get_debug_state"):
                debug_state = self._runtime_model.get_debug_state()
                logger.debug(
                    f"[Container {self.container_id}] entering DRAINING mode - "
                    f"debug_state={debug_state}"
                )
            else:
                logger.info(f"[Container {self.container_id}] entered DRAINING mode")

            notify_event(
                event_bus=self.event_bus,
                topic=EventTopic.CONTAINER_DRAINING,
                origin=self.container_id,
                obj=self,
                env=self.env,
            )

            # Note: We don't close the LB forward channel here. The Registry already
            # filters draining containers via get_containers(), so the LB won't send
            # new requests. Closing from Container side would be semantically incorrect
            # (a process can't close the "other side" of a socket).

            # Give some time for in-flight requests to arrive from the LB
            # before closing the internal bridge to the RuntimeModel.
            if self.drain_grace_period > 0:
                await self.env.timeout(self.drain_grace_period)

            # Step 1: Close the Container->RuntimeModel channel to unblock RuntimeModel
            # This allows RuntimeModel to detect closure and signal idle after processing
            # any remaining requests in its queue
            self.runtime_duplex_channel.close_forward()
            logger.debug(
                f"[Container {self.container_id}] closed runtime forward channel"
            )

            # Step 2: Yield control to allow other processes (listeners, RuntimeModels) to run
            # This is critical: closing channels puts sentinels in queues, but the processes
            # waiting on those queues need CPU time to receive the sentinels
            await self.env.timeout(0)

            # Step 3: Wait for RuntimeModel to signal idle (queue empty + current request done)
            try:
                await self._runtime_idle_queue.get()
                logger.debug(f"[Container {self.container_id}] drain complete")
            except asimpy.Interrupt:
                logger.debug(f"[Container {self.container_id}] drain interrupted")
        else:
            # HARDSTOP: Interrupt RuntimeModel immediately
            if self._runtime_process.is_alive:
                self._runtime_process.interrupt()
                logger.debug(f"[Container {self.container_id}] runtime interrupted")

            # Close runtime forward channel (LB channel not closed - see drain mode comment)
            self.runtime_duplex_channel.close_forward()

            # Drain orphaned requests from BOTH channels and mark as LOST
            # This ensures no requests are left in limbo in the channel queues
            lost_count = 0
            for channel in [self.lb_duplex_channel, self.runtime_duplex_channel]:
                if channel is None:
                    continue
                while channel.get_forward_queue_size() > 0:
                    req = await channel.receive_forward()
                    if req is None:
                        break
                    if req.set_request_lost():
                        self.event_bus.publish(
                            topic=EventTopic.REQUEST_LOST,
                            payload={
                                "request_id": req.id,
                                "app_id": req.app.name if req.app else "unknown",
                                "container_id": self.container_id,
                                "vm_id": self.vm.vm_id if self.vm else "unknown",
                                "time": self.env.now,
                                "reason": "container_hardstop",
                                "timeline": [ts.to_dict() for ts in req.timeline],
                            },
                            origin=self.container_id,
                            correlation_id=req.id,
                        )
                        lost_count += 1

            if lost_count > 0:
                logger.info(
                    f"[Container {self.container_id}] marked {lost_count} orphaned requests as LOST"
                )

        # Interrupt response process if alive
        if hasattr(self, "_response_process") and self._response_process.is_alive:
            self._response_process.interrupt()

        # Close the backward channel to signal no more responses
        # This replaces the old EOT sentinel pattern with proper channel semantics
        if self.lb_duplex_channel:
            self.lb_duplex_channel.close_backward()
            logger.debug(f"[Container {self.container_id}] closed backward channel")

        # Publish events and update state
        notify_event(
            event_bus=self.event_bus,
            topic=EventTopic.CONTAINER_STOPPED,
            origin=self.container_id,
            obj=self,
            env=self.env,
        )
        notify_event(
            event_bus=self.event_bus,
            topic=EventTopic.CONTAINER_REMOVED,
            origin=self.container_id,
            obj=self,
            env=self.env,
        )
        # Note: VM removes container from its list via _container_lifecycle_listener
        # when it receives CONTAINER_STOPPED event (separation of concerns)
        self.state = ContainerState.STOPPED
        logger.debug(f"[Container {self.container_id}] stopped on VM {vm_id}")

    def __repr__(self) -> str:
        return f"Container(id={self.container_id}, image={self.image_name}, state={self.state.value})"

    def release_resources_in_vm(
        self, cpu_to_free: float, memory_to_free: float
    ) -> None:
        """
        Release resources in the VM.

        Args:
            cpu_to_free (float): CPU units to release.
            memory_to_free (float): Memory units to release.
        """
        try:
            # self.vm.cpu.put(cpu_to_free)
            logger.info(
                f"[Container {self.container_id}] released {cpu_to_free} CPU units. Available: {self.available_cpu}",
            )

            # self.vm.memory.put(memory_to_free)
            logger.info(
                f"[Container {self.container_id}] released {memory_to_free} memory units. Available: {self.available_memory}",
            )

        except ValueError:
            logger.error(
                f"[Container {self.container_id}] try to release more resources than available in vm {self.vm.vm_id}.",
            )

    def assign_vm(self, vm: VM) -> None:
        """
        Assign the container to a VM.

        Args:
            vm (nuberu.VM): The VM to assign the container to.
        """
        self.vm = vm

        logger.info(
            f"[Container {self.container_id}] Assigned to VM {vm.vm_id}",
        )

    async def _listen_for_requests(self) -> None:
        """
        Continuously receive requests from LoadBalancer and forward to RuntimeModel.

        This method implements the forward flow of the bidirectional request-response
        pattern. It receives requests from LoadBalancer via the forward channel of the
        duplex connection and enqueues them to the RuntimeModel.
        """
        try:
            while self.state != ContainerState.STOPPED:
                if not self.lb_duplex_channel:
                    # Wait for channel to be configured
                    await self.env.timeout(0)
                    continue

                # Receive request from LoadBalancer (forward channel)
                request = await self.lb_duplex_channel.receive_forward()

                # Handle channel closure (Container.stop() closed the LB channel during drain)
                if request is None:
                    logger.debug(
                        f"[Container {self.container_id}] LB channel closed, exiting request listener"
                    )
                    return

                # Timeline: Container receives request from LoadBalancer
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id=f"Container_{self.container_id}",
                        event="receive_from_lb",
                        source_id="LoadBalancer",
                        metadata={"vm_id": self.vm.vm_id},
                    )
                )

                assert request.app is not None  # For mypy
                logger.debug(
                    f"Container {self.container_id} received request {request.id} from LoadBalancer"
                )

                rm = self._runtime_model
                if rm.can_enqueue(request):
                    # Capture queue length BEFORE enqueue (actual state before this request)
                    queue_length_before_enqueue = (
                        self.runtime_duplex_channel.get_forward_queue_size()
                    )

                    # Send request to RuntimeModel
                    try:
                        await self.runtime_duplex_channel.send_forward(request)
                    except ChannelClosedError:
                        logger.warning(
                            f"Container {self.container_id} attempted to send request {request.id} to a closed RuntimeModel channel. Marking as LOST."
                        )
                        if request.set_request_lost():
                            self.event_bus.publish(
                                topic=EventTopic.REQUEST_LOST,
                                payload={
                                    "request_id": request.id,
                                    "app_id": request.app.name
                                    if request.app
                                    else "unknown",
                                    "container_id": self.container_id,
                                    "vm_id": self.vm.vm_id if self.vm else "unknown",
                                    "time": self.env.now,
                                    "reason": "runtime_channel_closed",
                                    "timeline": [
                                        ts.to_dict() for ts in request.timeline
                                    ],
                                },
                                origin=self.container_id,
                                correlation_id=request.id,
                            )
                        return

                    # Timeline: Container accepted and sent to RuntimeModel with queue metadata
                    request.timeline.append(
                        RequestTimestamp(
                            time=self.env.now,
                            component_id=f"Container_{self.container_id}",
                            event="accepted_and_sent_to_runtime",
                            target_id=f"RuntimeModel_{self.container_id}",
                            metadata={
                                "queue_length": queue_length_before_enqueue,
                                "vm_id": self.vm.vm_id,
                            },
                        )
                    )

                    logger.info(
                        f"Container {self.container_id} accepted request {request.id}",
                    )
                else:
                    if request.set_request_rejected(reason="runtime_model_rejected"):
                        self.event_bus.publish(
                            topic=EventTopic.REQUEST_REJECTED,
                            payload={
                                "request_id": request.id,
                                "app_id": request.app.name,
                                "container_id": self.container_id,
                                "vm_id": self.vm.vm_id,
                                "arrival_time": request.arrival_time,
                                "reason": "RuntimeModel rejected",
                                "timeline": [ts.to_dict() for ts in request.timeline],
                            },
                            origin=self.container_id,
                            correlation_id=request.id,
                        )
                    logger.warning(
                        f"Container {self.container_id} rejected request {request.id}"
                    )
        except asimpy.Interrupt:
            logger.info(
                f"Container {self.container_id} request listener interrupted at {self.env.now}"
            )
            return

    async def _propagate_responses(self) -> None:
        """
        Continuously receive responses from RuntimeModel and forward them to LoadBalancer.

        This method implements the backward flow of the bidirectional request-response
        pattern. It receives completed requests from the RuntimeModel via the backward
        channel of the duplex connection and propagates them to LoadBalancer via the
        backward channel of the lb_duplex_channel.
        """
        try:
            while self.state != ContainerState.STOPPED:
                # Receive response from RuntimeModel (backward channel)
                request: Request = await self.runtime_duplex_channel.receive_backward()

                # Timeline: Container receives response from RuntimeModel
                request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id=f"Container_{self.container_id}",
                        event="receive_from_runtime",
                        source_id=f"RuntimeModel_{self.container_id}",
                    )
                )

                logger.debug(
                    f"Container {self.container_id} received response for request {request.id}, forwarding to LoadBalancer"
                )

                # Forward response to LoadBalancer via backward channel
                # Note: lb_duplex_channel will be set by InfrastructureManager/Builder
                if self.lb_duplex_channel:
                    # Timeline: Container sends response back to LoadBalancer
                    request.timeline.append(
                        RequestTimestamp(
                            time=self.env.now,
                            component_id=f"Container_{self.container_id}",
                            event="send_to_lb",
                            target_id="LoadBalancer",
                        )
                    )

                    await self.lb_duplex_channel.send_backward(request)
                else:
                    logger.warning(
                        f"Container {self.container_id} has no lb_duplex_channel configured, dropping response for request {request.id}"
                    )
        except asimpy.Interrupt:
            logger.info(
                f"Container {self.container_id} response propagation interrupted at {self.env.now}"
            )
            # If we were holding a request when interrupted (e.g. at a yield point not shown here),
            # it might be lost. But using send_backward_now above minimizes this risk significantly
            # as the send operation becomes atomic (no yields). The only yield is receive_backward.
            return

    def _to_dict(self) -> dict[str, object]:
        """
        Convert the container to a dictionary representation.

        Returns:
            dict[str, object]: Dictionary with container attributes.
        """
        return {
            "container_id": self.container_id,
            "container_class": self.container_class.name,
            "state": self.state.value,
            "vm_id": self.vm.vm_id if self.vm else None,
            "image_name": self.image_name,
            "cpu": self.cpu,
            "memory": self.memory,
            "available_cpu": self.available_cpu,
            "available_memory": self.available_memory,
        }
