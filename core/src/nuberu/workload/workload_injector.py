from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Iterable

import asimpy

from ..channels import DuplexChannel
from ..core.events import EventTopic
from ..core.states import RequestState
from ..workload.request import Request

if TYPE_CHECKING:
    from ..core.events import EventBus
    from ..core.infrastructure import Workload

logger = logging.getLogger(__name__)


class WorkloadInjector:
    """
    Component responsible for injecting requests into the system.

    It pulls the next workload from the Workload iterable and generates
    Request objects based on it, which are sent through a DuplexChannel to the LoadBalancer.

    Attributes:
        env (asimpy.Environment): The simulation environment.
        lb_duplex_channels (dict[str, DuplexChannel]): Per-app channels for LoadBalancer communication.
        workloads (Iterable[Workload]): An iterable providing a list of Workload's to inject.
        event_bus (EventBus): Event bus for communication between components.
        stop_time (float): The time at which the injector should stop injecting requests.

    """

    def __init__(
        self,
        env: asimpy.Environment,
        lb_duplex_channels: dict[str, DuplexChannel],
        workloads: Iterable[Workload],
        event_bus: EventBus,
        stop_time: float,
        app_configs: dict[str, dict[str, Any]],
        eager_start: bool = False,
    ) -> None:
        """
        Initializes the WorkloadInjector with the necessary components.

        Args:
            env: The simulation environment.
            lb_duplex_channels: Per-app bidirectional channels for LoadBalancer communication.
            workloads: Iterable providing a list of Workload's to inject.
            event_bus: Event bus for communication between components.
            stop_time: The time at which the injector should stop injecting requests.
            app_configs: Optional dictionary containing application-specific configurations.
            eager_start: If True, starts the injector immediately upon infrastructure initialization.
        """
        self.env = env

        # Per-app bidirectional channels for LoadBalancer communication
        # Each app has its own channel with specific network delay
        # Forward: WI -> LB (requests), Backward: LB -> WI (responses)
        self.lb_duplex_channels = lb_duplex_channels

        self.event_bus = event_bus
        self.stop_time = stop_time
        self.app_configs = app_configs

        # Pending requests dict: Maps request_id -> Request object
        # Changed from set[str] to dict for direct access to Request objects (RFC 004 Step 5)
        self._pending_requests: dict[str, Request] = {}

        # Start response receiver process
        self._response_receiver = env.process(self._receive_responses())

        # Queue for terminal request events (COMPLETED, REJECTED, LOST)
        # CRITICAL: Not all requests go through _receive_responses()!
        # - Requests rejected by LoadBalancer (no container) never get a backward response
        # - Requests lost due to timeouts/errors may not complete the round-trip
        # - We need event subscriptions to track ALL terminal states
        self._req_done_queue = asimpy.Store(env)
        event_bus.subscribe(EventTopic.REQUEST_COMPLETED, self._req_done_queue)
        event_bus.subscribe(EventTopic.REQUEST_REJECTED, self._req_done_queue)
        event_bus.subscribe(EventTopic.REQUEST_LOST, self._req_done_queue)

        # Track which request_ids already produced a terminal event to avoid
        # double-counting when flushing pending requests at shutdown.
        # NOTE: Potential memory issue - this set grows indefinitely and is never cleared.
        # For very long simulations (millions of requests), this could consume significant
        # memory (~30 bytes per request_id string). Consider bounded cache if needed.
        self._terminal_seen: set[str] = set()

        # Launch process to track request completion via events
        env.process(self._track_requests_done())

        # Keep the iterable of workloads; it must be re-iterable (e.g. a list)
        self.workloads = workloads

        # Necessary to stop request injection when DRAIN mode is activated
        self._active_processes: list[asimpy.Process] = []
        self._end_sim_queue: asimpy.Store = asimpy.Store(env)
        self.event_bus.subscribe(EventTopic.END_SIMULATION, self._end_sim_queue)

        if eager_start:
            self._infra_ready_queue: asimpy.Store = asimpy.Store(self.env)
            # Subscribe to the infrastructure ready event
            self.event_bus.subscribe(
                EventTopic.INFRASTRUCTURE_READY, self._infra_ready_queue
            )
            self.env.process(self._wait_for_infrastructure())
            logger.info(
                "Eager start mode enabled. Waiting for infrastructure to be ready before starting workload injection.",
            )
        else:
            # Start immediately
            self.start()
            logger.info(
                "Eager start mode disabled. Workload injection will start as soon as the injector is initialized.",
            )

        self.env.process(self._listen_for_end_simulation())

    async def _track_requests_done(self) -> None:
        """
        Listen for terminal request events (COMPLETED, REJECTED, LOST) and remove from pending.

        This is CRITICAL because not all requests go through _receive_responses():
        - LoadBalancer may reject requests (no containers available) -> publishes REQUEST_REJECTED
        - Containers may reject requests (queue full) -> publishes REQUEST_REJECTED
        - RuntimeModel may lose requests (interrupt) -> publishes REQUEST_LOST

        These events don't trigger backward channel responses, so we need event subscriptions.
        """
        while True:
            event = await self._req_done_queue.get()
            req_id = event.payload.get("request_id", None)
            if req_id and req_id in self._pending_requests:
                self._terminal_seen.add(req_id)
                # Remove from pending tracking
                request_state = self._pending_requests[req_id].state
                self._pending_requests.pop(req_id)
                logger.debug(
                    f"Request {req_id} marked as done (State: {request_state}) via {event.topic.value} event (pending: {len(self._pending_requests)})"
                )
            elif req_id:
                # Even if it's no longer pending, remember we saw a terminal event
                self._terminal_seen.add(req_id)

    async def _wait_for_infrastructure(self) -> None:
        """
        Callback invoked once InfrastructureManager signals it's ready.
        """
        event = await self._infra_ready_queue.get()
        logger.info(
            f"Infrastructure ready ({event.topic.value}) -> starting workload injection.",
        )
        self.start()

    @property
    def in_flight_count(self) -> int:
        """Returns the number of requests currently in flight."""
        return len(self._pending_requests)

    @property
    def has_in_flight_requests(self) -> bool:
        """Returns True if there are requests currently in flight."""
        return bool(self._pending_requests)

    def _publish_terminal_event(
        self,
        request: Request,
        topic: EventTopic,
        **extra: Any,
    ) -> None:
        """
        Helper to publish terminal request events with consistent payload.

        Args:
            request: The request object to publish event for.
            topic: The event topic (REQUEST_COMPLETED, REQUEST_REJECTED, REQUEST_LOST).
            **extra: Additional payload fields to include.
        """
        payload: dict[str, Any] = {
            "request_id": request.id,
            "app_id": request.app.name if request.app else "unknown",
            "arrival_time": request.arrival_time,
            "time": self.env.now,
            "timeline": [ts.to_dict() for ts in request.timeline],
            **extra,
        }
        self.event_bus.publish(
            topic=topic,
            payload=payload,
            origin="WorkloadInjector",
            correlation_id=request.id,
        )

    def flush_lost_requests(self) -> None:
        """
        Publishes all requests that were pending at the end of the simulation as lost.

        Now uses dict-based tracking (RFC 004 Step 5) to access full Request objects,
        enabling complete timeline tracking and rich event payloads.

        Shutdown Sequence Context:
        This method is called during simulation shutdown (step 4 in Simulation.run()),
        AFTER infrastructure shutdown but BEFORE _flush_remaining_events(). At this point:

        1. _receive_responses() may have published REQUEST_COMPLETED/REJECTED events
        2. Those events are queued but not yet processed by _track_requests_done()
        3. Therefore, _pending_requests may contain requests in terminal states
        4. This is EXPECTED, not a bug - we handle it by re-publishing events

        The re-publishing ensures Monitor captures all terminal events, even if
        _track_requests_done() hasn't processed them yet due to shutdown timing.

        Called for side effects only (event publishing). Does not return a value.
        """
        if not self._pending_requests:
            logger.info("No pending requests to flush.")
            return

        total_pending = len(self._pending_requests)
        logger.warning(
            f"Flushing {total_pending} pending requests at simulation end (t={self.env.now})"
        )

        lost_new = 0
        republished_completed = 0
        republished_rejected = 0
        skipped_already_lost = 0
        already_terminal_seen = 0

        # Iterate over Request objects (not just IDs)
        for request in list(self._pending_requests.values()):
            if request.id in self._terminal_seen:
                already_terminal_seen += 1
                self._pending_requests.pop(request.id, None)
                continue

            if request.state == RequestState.COMPLETED:
                republished_completed += 1
                # Add Client_receive_response to timeline if not already present
                # This ensures the timeline is complete for requests processed during shutdown
                if not any(
                    entry.component_id == "Client_receive_response"
                    for entry in request.timeline
                ):
                    request.add_timeline_entry("Client_receive_response", self.env.now)
                self._publish_terminal_event(
                    request,
                    EventTopic.REQUEST_COMPLETED,
                    finish_time=request.finish_time or self.env.now,
                    round_trip_complete=True,
                )
                self._terminal_seen.add(request.id)
                self._pending_requests.pop(request.id, None)
                continue

            if request.state == RequestState.REJECTED:
                republished_rejected += 1
                self._publish_terminal_event(
                    request,
                    EventTopic.REQUEST_REJECTED,
                    reason=request.rejection_reason or "already_rejected",
                )
                self._terminal_seen.add(request.id)
                self._pending_requests.pop(request.id, None)
                continue

            if request.state == RequestState.LOST:
                # Assume a LOST event was already published by runtime/container; avoid duplicates
                skipped_already_lost += 1
                self._terminal_seen.add(request.id)
                self._pending_requests.pop(request.id, None)
                continue

            # Add timeline entry showing request was lost at client side
            request.add_timeline_entry("Client_lost", self.env.now)
            lost_new += 1

            # Mark request state as LOST
            request.set_request_lost()

            self._terminal_seen.add(request.id)

            # Publish REQUEST_LOST event with complete request data including timeline
            self._publish_terminal_event(
                request,
                EventTopic.REQUEST_LOST,
                reason="simulation_end",
            )
            logger.debug(f"Marked request {request.id} as LOST with complete timeline")

        self._pending_requests.clear()
        logger.info(
            "Flush complete: %s newly marked LOST, republished %s completed, %s rejected, skipped %s already-lost; %s already had terminal events",
            lost_new,
            republished_completed,
            republished_rejected,
            skipped_already_lost,
            already_terminal_seen,
        )

    def start(self) -> None:
        """Starts the request injection process."""
        for wl in self.workloads:
            self._active_processes.append(self.env.process(self._inject_requests(wl)))
            logger.debug(
                f"Started request injection process for workload {wl.app.name} "
            )

    async def _inject_requests(self, wl: Workload) -> None:
        """
        Inject all requests for a single workload (app) in FIFO order.
        """

        app_name: str = wl.app.name
        config = self.app_configs.get(app_name, {})
        # Get factory from plugin and call it with env to create iterator
        # Pass stop_time to ensure injection stops before simulation ends
        interarrival_factory = wl.distribution.get_interarrival_times_factory(
            config, stop_time=self.stop_time
        )
        interarrival_iter = interarrival_factory(self.env)
        logger.debug(
            f"Starting infinite injection for app '{app_name}' "
            f"using {wl.distribution.__class__.__name__} with config={config}"
        )
        i = 0
        try:
            while True:
                # Stop immediately if the simulation horizon has been reached
                if self.stop_time is not None and self.env.now >= self.stop_time:
                    logger.info(
                        f"Stop time ({self.stop_time}) reached at t={self.env.now}. "
                        f"Halting injection for app {app_name}."
                    )
                    return

                reqs, interval = next(interarrival_iter)

                for c in range(reqs):
                    logger.debug(f"Injecting request {i} for app {app_name}")
                    request_id = f"{app_name}_req_{uuid.uuid4().hex[:8]}_{i}"
                    request = Request(
                        request_id=request_id,
                        arrival_time=self.env.now,
                        cpu=1,
                        memory=1,
                        duration=1,  # Cannot be determined here. The duration depends on the application and the container it is assigned to.
                        app=wl.app,
                    )
                    # Timeline: Request created at client
                    request.add_timeline_entry("Client_generated", self.env.now)

                    self.event_bus.publish(
                        topic=EventTopic.REQUEST_GENERATED,
                        payload={
                            "request_id": request.id,
                            "app_id": wl.app.name,
                            "time": self.env.now,
                        },
                        origin="WorkloadInjector",
                    )

                    # Timeline: WorkloadInjector sends request to LoadBalancer
                    request.add_timeline_entry("Client_send_to_lb", self.env.now)

                    # Track pending request (Step 5: dict-based tracking)
                    # Will be removed by _track_requests_done() when terminal event arrives
                    self._pending_requests[request.id] = request

                    # Send via app-specific channel
                    channel = self.lb_duplex_channels[app_name]
                    await channel.send_forward(request)
                    logger.debug(
                        f"Injected request {request.id} for app {app_name} (pending: {len(self._pending_requests)}).",
                    )
                    i += 1

                # Wait for the next interval before injecting the next request
                # We do the await here because we consider that at instant 0
                # requests can already start being injected.
                # It could be done at the start of the loop if we want to avoid generating at t = 0 and instead after the first interval.
                if self.stop_time is not None:
                    remaining = self.stop_time - self.env.now
                    if remaining <= 0:
                        logger.info(
                            f"Stop time ({self.stop_time}) reached at t={self.env.now}. "
                            f"Halting injection for app {app_name}."
                        )
                        return

                    if interval > remaining:
                        logger.debug(
                            f"Clamping next interval from {interval} to {remaining} for app {app_name} "
                            f"to avoid injecting past stop_time."
                        )
                        interval = remaining

                await self.env.timeout(interval)
        except StopIteration:
            logger.warning(f"Interarrival generator exhausted for app {app_name}")
        except asimpy.Interrupt:
            logger.info(
                f"Request injection interrupted for app {app_name} at t={self.env.now}"
            )

    async def _listen_for_end_simulation(self) -> None:
        """
        Waits for the END_SIMULATION event and stops all active injection processes.

        Implements a graceful shutdown with two phases:
        1. Grace period: Wait to allow in-flight messages to complete delivery
        2. Interrupt: Force-stop any remaining active processes

        The grace period is critical because when a process is interrupted during
        a channel send operation (specifically during env.timeout), the message
        never reaches the store.put() and is lost. By waiting first, we allow
        ongoing send operations to complete naturally.
        """
        await self._end_sim_queue.get()
        logger.info(
            f"END_SIMULATION received. Beginning graceful shutdown of {len(self._active_processes)} injection process(es)."
        )

        # Phase 1: Grace period BEFORE interrupting to let injection complete naturally
        # This allows:
        # - Ongoing channel.send() operations to complete (env.timeout + store.put)
        # - Injection processes to finish their current iteration
        # - All in-flight messages to reach their destination
        #
        # Why this is necessary:
        # If we interrupt immediately, any process in the middle of channel.send()
        # (specifically during env.timeout) will have its execution aborted before
        # reaching store.put(), losing the message. The message was already published
        # as GENERATED and SENT, but never reaches the LoadBalancer (no ROUTED/REJECTED).
        #
        # The grace period allows these operations to complete naturally, ensuring
        # consistency between generated/sent/routed counts.
        grace_period = (
            0.2  # seconds - very conservative to catch even last-moment requests
        )
        logger.debug(
            f"Grace period: waiting {grace_period}s to allow injection processes to complete naturally..."
        )
        await self.env.timeout(grace_period)
        logger.debug("Grace period complete. Proceeding with process cleanup.")

        # Phase 2: Interrupt any remaining active processes
        # At this point, most should have finished naturally
        self._active_processes = [p for p in self._active_processes if p.is_alive]

        if self._active_processes:
            logger.debug(
                f"Interrupting {len(self._active_processes)} remaining processes..."
            )
            for p in self._active_processes:
                try:
                    p.interrupt()
                except RuntimeError:
                    logger.debug(f"{p} already dead, skip")
                    continue

        # Brief yield to allow interrupted processes to exit cleanly
        await self.env.timeout(0)

        self._active_processes.clear()
        logger.info("All injection processes stopped. Shutdown complete.")

    async def _receive_responses(self) -> None:
        """
        Continuously receive responses from LoadBalancer via all app channels.

        This method implements the final step of the bidirectional request-response
        pattern. It receives completed requests from the LoadBalancer via any of
        the per-app duplex channels, records the final timeline entry, and publishes
        a REQUEST_END event.

        Uses MultiChannelReceiver to wait for responses from any channel (one per app).

        This completes the round-trip: WI -> LB -> VM -> Container -> Runtime
                                        and back: Runtime -> Container -> VM -> LB -> WI
        """
        from ..channels import MultiChannelReceiver

        receiver = MultiChannelReceiver(self.env, self.lb_duplex_channels, "backward")

        try:
            while not receiver.is_exhausted:
                app_name, message = await receiver.receive_any()

                # Channel closed or all exhausted
                if message is None:
                    if app_name:
                        logger.debug(
                            f"LB backward channel for {app_name} closed, removing from active"
                        )
                    continue

                request: Request = message

                # Timeline: WorkloadInjector receives response (round-trip complete)
                request.add_timeline_entry("Client_receive_response", self.env.now)

                # Publish terminal event based on request state
                if request.state == RequestState.COMPLETED:
                    self._publish_terminal_event(
                        request,
                        EventTopic.REQUEST_COMPLETED,
                        finish_time=request.finish_time,
                        round_trip_complete=True,
                    )
                elif request.state == RequestState.REJECTED:
                    self._publish_terminal_event(
                        request,
                        EventTopic.REQUEST_REJECTED,
                        reason=request.rejection_reason or "unknown",
                    )

                logger.debug(
                    f"WorkloadInjector received response for request {request.id} (state: {request.state}) - round-trip complete (pending: {len(self._pending_requests)})"
                )

            logger.debug("All LB backward channels closed, exiting response receiver")

        except asimpy.Interrupt:
            logger.info(
                f"WorkloadInjector response receiver interrupted at {self.env.now}"
            )
            return
