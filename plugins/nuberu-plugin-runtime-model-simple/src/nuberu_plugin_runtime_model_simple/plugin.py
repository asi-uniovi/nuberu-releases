from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

import asimpy
import pluggy

from nuberu.channels import DuplexChannel
from nuberu.core.events import EventBus, EventTopic
from nuberu.core.states import ContainerState
from nuberu.workload.timeline import RequestTimestamp
from nuberu.plugins import PluginBase


if TYPE_CHECKING:
    from nuberu.components.container import Container
    from nuberu.workload.request import Request

hookimpl = pluggy.HookimplMarker("nuberu")

logger = logging.getLogger("nuberu.plugins.runtime_model_simple")


class RuntimeModelSimple:
    """
    Default RuntimeModelSimple used if no plugin is provided.

    Assumes that each container has a maximum requests-per-second (RPS) capacity
    defined in `performance` attribute. The container accepts requests as long as
    its current load is below that threshold.
    """

    def __init__(
        self,
        env: asimpy.Environment,
        container: Container,
        performance: float,
        event_bus: EventBus,
        duplex_channel: DuplexChannel,
        idle_sink: asimpy.Store | None = None,
        progress_sink: asimpy.Store | None = None,
        queue_size: int = 1,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initializes the RuntimeModelSimple with a container and performance data.

        Args:
            env (asimpy.Environment): The simulation environment.
            container (Container): The container to be monitored.
            performance (float): Requests per second that the container can handle.
            event_bus (EventBus): Event bus for handling events.
            duplex_channel (DuplexChannel): Bidirectional channel for request/response communication.
            idle_sink (asimpy.Store, optional): Store to signal when the container is idle.
            progress_sink (asimpy.Store, optional): Store to signal progress during draining.
            queue_size (int): Size of the processing queue for the container (default is 1).
            logger (logging.Logger, optional): Logger instance to use. If None, uses module logger.
        """
        self.env: asimpy.Environment = env
        self.container: Container = container
        self.event_bus: EventBus = event_bus
        self.performance: float = performance
        self.duplex_channel: DuplexChannel = duplex_channel
        self._idle_sink: asimpy.Store | None = idle_sink
        self._progress_sink: asimpy.Store | None = progress_sink
        # Expose p95-like estimate so Containers can derive drain watchdogs
        # self.service_p95: float | None = 1.0 / performance if performance > 0 else None
        self.logger = logger or logging.getLogger(__name__)

        self._accepted: int = 0
        self._rejected: int = 0
        self.max_queue_size: int = queue_size
        self._current_request: Request | None = None

    def can_enqueue(self, request: Request) -> bool:
        """
        Determines whether a new request can be enqueued based on the current queue size.

        This method checks the ACTUAL queue size from the channel plus any request being processed. This provides a single source of truth and eliminates synchronization bugs.

        Args:
            request (Request): The request to be enqueued.
        Returns:
            bool: True if the request can be enqueued, False otherwise.
        """
        # Get actual queue size from channel (single source of truth)
        actual_queue_size = self.duplex_channel.get_forward_queue_size()

        # Count request being processed (if any)
        processing_count = 1 if self._current_request is not None else 0

        # Total pending work = queue + processing
        current_total_load = actual_queue_size + processing_count

        # Special mode: queue_size == 0 simulates a system with no queueing.
        # Requests are accepted only if the container is idle at arrival.
        if self.max_queue_size == 0:
            if processing_count == 0:
                self._accepted += 1
                return True
            else:
                self._rejected += 1
                self.logger.warning(
                    f"Container {self.container.container_id} rejected request {request.id} "
                    f"due to being busy (q=0 mode)."
                )
                return False

        # Normal mode: predict future load AFTER adding this request
        # Container calls can_enqueue() BEFORE adding to queue, so we need to predict the state after the request is enqueued
        future_total_load = current_total_load + 1  # +1 for the request being checked

        # Accept if future load won't exceed the limit
        # This matches original semantics: _pending was incremented in can_enqueue()
        # before the request was actually sent to the queue
        if future_total_load <= self.max_queue_size:
            self._accepted += 1
            return True
        else:
            self._rejected += 1
            self.logger.warning(
                f"Container {self.container.container_id} rejected request {request.id} "
                f"due to capacity limit. Queue: {actual_queue_size}, Processing: {processing_count}, "
                f"Current: {current_total_load}, Future: {future_total_load}, Limit: {self.max_queue_size}"
            )
            return False

    def compute_response_time(self, request: Request) -> float:
        """
        Compute a simple response time estimation (inverse of max RPS).

        Args:
            request (Request): The request being served.

        Returns:
            float: Estimated response time in seconds.
        """
        # In a simple model, we assume the response time is the inverse of the performance (RPS)
        if self.performance > 0.0:
            return 1.0 / self.performance
        else:
            return float("inf")

    def metrics_summary(self) -> dict[str, int]:
        """
        Returns a summary of accepted and rejected requests (optional).

        Returns:
            dict[str, int]: Metrics dictionary.
        """
        return {
            "accepted": self._accepted,
            "rejected": self._rejected,
        }

    def get_debug_state(self) -> dict:
        """
        Returns detailed state for debugging drain mode issues.

        All values come from real state (no redundant counters), providing
        accurate and trustworthy debugging information.

        Returns:
            dict: Debug state with actual queue sizes and processing state
        """
        queue_size = self.duplex_channel.get_forward_queue_size()
        processing = 1 if self._current_request is not None else 0
        total_work = queue_size + processing

        return {
            # Real state (single source of truth)
            "requests_in_queue": queue_size,
            "requests_processing": processing,
            "total_pending_work": total_work,
            # Additional useful info
            "current_request_id": (
                self._current_request.id if self._current_request else None
            ),
            "queue_limit": self.max_queue_size,
            "utilization": (
                total_work / self.max_queue_size if self.max_queue_size > 0 else 0.0
            ),
            # Historical counters
            "accepted_total": self._accepted,
            "rejected_total": self._rejected,
            "container_state": self.container.state.value,
        }

    async def run(self) -> None:
        try:
            while self.container.state != ContainerState.STOPPED:
                # If draining and no work left, signal idle and exit gracefully
                if (
                    self.container.state == ContainerState.DRAINING
                    and self.duplex_channel.get_forward_queue_size() == 0
                    and self._current_request is None
                ):
                    if self._idle_sink is not None:
                        await self._idle_sink.put(True)
                    break

                # Capture queue length BEFORE dequeue (includes current request)
                queue_length_before_dequeue = (
                    self.duplex_channel.get_forward_queue_size()
                )

                # Process requests - receive from forward channel
                self._current_request = await self.duplex_channel.receive_forward()

                # Handle channel closure (Container closed forward channel during drain)
                if self._current_request is None:
                    self.logger.debug(
                        f"[RuntimeModel {self.container.container_id}] forward channel closed, signaling idle"
                    )
                    if self._idle_sink is not None:
                        await self._idle_sink.put(True)
                    break

                service_time: float = self.compute_response_time(self._current_request)

                # Add timeline entry: RuntimeModel receives request from Container with queue metadata
                self._current_request.timeline.append(
                    RequestTimestamp(
                        time=self.env.now,
                        component_id=f"RuntimeModel_{self.container.container_id}",
                        event="receive_from_container",
                        source_id=f"Container_{self.container.container_id}",
                        metadata={
                            "queue_length": queue_length_before_dequeue,
                            "vm_id": self.container.vm.vm_id,
                            "duration": round(service_time, 4),
                        },
                    )
                )

                # Note: No need to decrement counter - we use actual queue size

                # Update request duration based on performance data of this container
                # This is a simple model, so we assume the performance is constant
                # and the request duration is equal to the inverse of the performance (RPS)
                self._current_request.set_duration(service_time)  # service_time (1/rps)

                # Asserts for mypy
                assert self._current_request.app is not None
                assert self._current_request.arrival_time is not None
                assert self._current_request.duration is not None
                assert self._current_request.cpu is not None
                assert self._current_request.memory is not None

                # Timeline: Start processing (queue exit, service start)
                self._current_request.add_timeline_entry(
                    f"Runtime_{self.container.container_id}_start_service", self.env.now
                )

                # Set start_time for response time calculations
                self._current_request.start_time = self.env.now

                # Do not override drain state
                if self.container.state not in (
                    ContainerState.DRAINING,
                    ContainerState.STOPPING,
                ):
                    self.container.state = ContainerState.RUNNING

                # Process the request
                self.logger.info(
                    f"Container {self.container.container_id} processing request {self._current_request.id}",
                )
                self.logger.debug(
                    "Duration: "
                    f"{self._current_request.duration:.4f} seconds, Expected end of request: {self.env.now + self._current_request.duration:.4f} seconds"
                )
                await self.env.timeout(self._current_request.duration)

                # Release resources
                self.logger.info(
                    f"[Container {self.container.container_id}] released: {self._current_request.cpu} CPU and {self._current_request.memory} memory. Available: {self.container.available_cpu}",
                )

                # Mark request as completed
                if self._current_request.set_request_completed(
                    finish_time=self.env.now
                ):
                    # Add timeline entry: processing completed
                    self._current_request.timeline.append(
                        RequestTimestamp(
                            time=self.env.now,
                            component_id=f"RuntimeModel_{self.container.container_id}",
                            event="processing_completed",
                            metadata={
                                "service_time": self._current_request.duration,
                                "container_state": self.container.state.name,
                            },
                        )
                    )

                    # Timeline: Service completed
                    self._current_request.add_timeline_entry(
                        f"Runtime_{self.container.container_id}_end_service",
                        self.env.now,
                    )

                    # Add timeline entry: sending response back to Container
                    self._current_request.timeline.append(
                        RequestTimestamp(
                            time=self.env.now,
                            component_id=f"RuntimeModel_{self.container.container_id}",
                            event="send_to_container",
                            target_id=f"Container_{self.container.container_id}",
                        )
                    )

                # Send response back through backward channel
                await self.duplex_channel.send_backward(self._current_request)
                self.logger.debug(
                    f"RuntimeModel sent response for request {self._current_request.id} back to container {self.container.container_id} via backward channel"
                )

                if (
                    self.container.state == ContainerState.DRAINING
                    and self._progress_sink is not None
                ):
                    await self._progress_sink.put(True)

                self.logger.debug(
                    f"Container {self.container.container_id} finished processing request {self._current_request.id}"
                )
                if self.container.state not in (
                    ContainerState.DRAINING,
                    ContainerState.STOPPING,
                ):
                    self.container.state = ContainerState.IDLE
                self._current_request = None  # Clear the current request
        except asimpy.Interrupt as interrupt:
            # Check if the interrupt happened during receive_forward and captured a value.
            # In SimPy, if an interrupt occurs after get() removed an item from store but before the process received it, the value may be in
            #  interrupt.cause or the process may have been about to receive it
            interrupted_request = None

            # If we were in the middle of receiving (line 165), the request might be in the interrupt's cause if SimPy captured it
            if hasattr(interrupt, "cause") and interrupt.cause is not None:
                # The cause might be the request that was being received
                from ..workload.request import Request

                if isinstance(interrupt.cause, Request):
                    interrupted_request = interrupt.cause

            # Mark current request as LOST (if we had one in processing)
            if self._current_request is not None:
                # Only mark as LOST if not already in a terminal state
                if self._current_request.set_request_lost():
                    self.event_bus.publish(
                        topic=EventTopic.REQUEST_LOST,
                        payload={
                            "request_id": self._current_request.id,
                            "app_id": (
                                self._current_request.app.name
                                if self._current_request.app
                                else "unknown"
                            ),
                            "container_id": self.container.container_id,
                            "vm_id": self.container.vm.vm_id,
                            "time": self.env.now,
                            "reason": "container_interrupted",
                            "timeline": [
                                ts.to_dict() for ts in self._current_request.timeline
                            ],
                        },
                        origin=self.container.container_id,
                        correlation_id=self._current_request.id,
                    )
                    self.logger.info(
                        f"RuntimeModel of container {self.container.container_id} interrupted at {self.env.now}, current request marked as LOST"
                    )
                else:
                    self.logger.debug(
                        f"RuntimeModel of container {self.container.container_id} interrupted at {self.env.now}, but current request already in terminal state {self._current_request.state}"
                    )
                self._current_request = None

            # Handle interrupted request (if there was one being received)
            if interrupted_request is not None:
                if interrupted_request.set_request_lost():
                    self.event_bus.publish(
                        topic=EventTopic.REQUEST_LOST,
                        payload={
                            "request_id": interrupted_request.id,
                            "app_id": (
                                interrupted_request.app.name
                                if interrupted_request.app
                                else "unknown"
                            ),
                            "container_id": self.container.container_id,
                            "vm_id": self.container.vm.vm_id,
                            "time": self.env.now,
                            "reason": "interrupted_during_receive",
                            "timeline": [
                                ts.to_dict() for ts in interrupted_request.timeline
                            ],
                        },
                        origin=self.container.container_id,
                        correlation_id=interrupted_request.id,
                    )
                    self.logger.info(
                        f"RuntimeModel of container {self.container.container_id} marked in-flight request as LOST"
                    )

            # Note: Queue draining is now handled by Container.stop()
            # The Container is the owner of the channels and responsible for
            # cleaning up any orphaned requests during hardstop.
            return


class RuntimeModelPlugin(PluginBase):
    """
    Plugin wrapper that implements the get_runtime_model_factory hook.
    Returns a factory function that creates RuntimeModelSimple instances.
    """

    plugin_name = "runtime_model_simple"

    def __init__(self):
        super().__init__()

    @hookimpl
    def get_runtime_model_factory(self, config: dict) -> Callable:
        """
        Return a factory function that creates RuntimeModelSimple instances.

        The factory captures the queue_size from config and returns a function
        that accepts runtime dependencies and creates a RuntimeModelSimple instance.

        Args:
            config: Configuration dict containing queue_size

        Returns:
            A factory function that creates RuntimeModelSimple instances
        """
        return self._create_runtime_model_factory(config)

    def _create_runtime_model_factory(self, config: dict) -> Callable:
        """Create a factory that passes the plugin's logger to RuntimeModelSimple."""
        queue_size = config.get("queue_size", 1)

        def factory(
            env: asimpy.Environment,
            container: Container,
            performance: float,
            event_bus: EventBus,
            duplex_channel: DuplexChannel,
            idle_sink: asimpy.Store | None = None,
            progress_sink: asimpy.Store | None = None,
        ) -> RuntimeModelSimple:
            return RuntimeModelSimple(
                env=env,
                container=container,
                performance=performance,
                event_bus=event_bus,
                duplex_channel=duplex_channel,
                idle_sink=idle_sink,
                progress_sink=progress_sink,
                queue_size=queue_size,
                logger=self.logger,
            )

        return factory
