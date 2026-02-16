from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..core.states import RequestState
from .timeline import RequestTimestamp

if TYPE_CHECKING:
    from ..core.infrastructure import App

logger = logging.getLogger(__name__)


class Request:
    """
    Class representing a request that arrives at the system.

    Attributes:
        id (str): Unique identifier for the request.
        arrival_time (int): Time when the request arrives.
        cpu (int): CPU required for the request.
        memory (int): Memory required for the request.
        duration (int | float): Duration for which resources are needed.
        app (App | None): Application associated with the request.
        state (RequestState): Current state of the request.
        start_time (int | float | None): Time when the request starts processing.
        finish_time (int | None): Time when the request finishes processing.
        timeline (list[RequestTimestamp]): Event timeline for bidirectional flow tracking.
    """

    # Terminal states that cannot transition to other states
    _TERMINAL_STATES = frozenset(
        [
            RequestState.REJECTED,
            RequestState.COMPLETED,
            RequestState.LOST,
        ]
    )

    id: str
    arrival_time: float
    cpu: int
    memory: int
    duration: int | float
    app: App | None
    state: RequestState
    start_time: int | float | None
    finish_time: int | float | None
    timeline: list[RequestTimestamp]
    assigned_container_id: str | None  # Container that is processing this request
    rejection_reason: str | None  # Reason for rejection (if applicable)

    def __init__(
        self,
        request_id: str,
        arrival_time: float,
        cpu: int,
        memory: int,
        duration: int,
        app: App | None = None,
        state: RequestState = RequestState.GENERATED,
    ):
        """
        Initialize a Request object.

        Args:
            request_id (str): Unique identifier for the request.
            arrival_time (int): Time when the request arrives.
            cpu (int): CPU required for the request.
            memory (int): Memory required for the request.
            duration (int): Duration for which resources are needed.
            app (App, optional): Application associated with the request. Defaults to None.
            state (RequestState, optional): Current state of the request. Defaults to RequestState.GENERATED.
        """
        self.id = request_id
        self.arrival_time = arrival_time
        self.cpu = cpu
        self.memory = memory
        self.duration = duration
        self.app = app
        self.state = state

        # Initially, start and finish times are None until the request is processed
        self.start_time = None
        self.finish_time = None

        # Container assignment for response routing (set by LoadBalancer)
        self.assigned_container_id = None

        # Rejection reason (if applicable)
        self.rejection_reason = None

        # Timeline for tracking bidirectional request-response flow (RFC 001)
        self.timeline: list[RequestTimestamp] = []

    def add_timeline_entry(self, component: str, timestamp: float) -> None:
        """
        Add a timeline entry to track request's journey through components.

        This replaces intermediate state transitions (ACCEPTED, ASSIGNED, PROCESSING)
        with a more flexible timeline-based approach.

        Args:
            component (str): Component ID (e.g., "Client_generated", "LB_1_receive")
            timestamp (float): Simulation time when request entered this component
        """
        entry = RequestTimestamp(
            time=timestamp, component_id=component, event="checkpoint"
        )
        self.timeline.append(entry)

    def set_request_rejected(self, reason: str | None = None) -> bool:
        """
        Set the request state to REJECTED.

        Args:
            reason (str | None): Optional reason for rejection (e.g., "no_container", "queue_full")

        Returns:
            bool: True if the state was changed to REJECTED, False if already in a terminal state.
        """
        if self.state in self._TERMINAL_STATES:
            return False
        self.state = RequestState.REJECTED
        self.rejection_reason = reason
        return True

    def set_request_completed(self, finish_time: int | float) -> bool:
        """
        Marks the request as completed by setting the end time and updating the state.

        Args:
            finish_time (int | float): The time at which the request was completed.

        Returns:
            bool: True if the state was changed to COMPLETED, False if already in a terminal state.

        Raises:
            ValueError: If the finish time is earlier than the start time.
        """
        if self.state in self._TERMINAL_STATES:
            return False
        if self.start_time is None:
            logger.warning(f"Request {self.id} completed without a start_time set")
        if self.start_time is not None and finish_time < self.start_time:
            raise ValueError(
                f"Finish time ({finish_time}) cannot be earlier than start time ({self.start_time})."
            )
        self.finish_time = finish_time
        self.state = RequestState.COMPLETED
        return True

    def set_request_lost(self) -> bool:
        """
        Marks the request as lost by updating its state to LOST.

        Returns:
            bool: True if the state was changed to LOST, False if already in a terminal state.
        """
        if self.state in self._TERMINAL_STATES:
            return False
        self.state = RequestState.LOST
        return True

    def set_duration(self, duration: int | float) -> None:
        """
        Set the duration for which resources are needed for the request.

        Args:
            duration (int): The duration in seconds.

        Raises:
            ValueError: If the duration is less than or equal to zero.
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than zero.")
        self.duration = duration
        logger.info(f"Request {self.id} duration set to {self.duration:.4f} seconds.")

    def set_assigned_container(self, container_id: str) -> None:
        """
        Set the container ID that will process this request.

        This is used by LoadBalancer for efficient response routing in bidirectional flow.

        Args:
            container_id (str): The ID of the container assigned to process this request.
        """
        self.assigned_container_id = container_id

    def get_assigned_container(self) -> str | None:
        """
        Get the container ID assigned to process this request.

        Returns:
            str | None: The container ID, or None if not yet assigned.
        """
        return self.assigned_container_id

    def __repr__(self) -> str:
        """
        Return a string representation of the Request object.

        Returns:
            str: A string that represents the Request object, including its id,
                 arrival_time, cpu, memory, duration, app, state, start_time, and finish_time.
        """
        app_name = self.app.name if self.app else "None"
        return (
            f"Request(id={self.id}, arrival_time={self.arrival_time}, cpu={self.cpu}, "
            f"memory={self.memory}, duration={self.duration}, app='{app_name}', "
            f"state='{self.state.value}', start_time={self.start_time}, finish_time={self.finish_time})"
        )

    def _to_dict(self) -> dict[str, object]:
        """
        Convert the request to a dictionary representation for serialization or logging.

        Returns:
            dict[str, object]: Dictionary containing request data.
        """
        return {
            "id": self.id,
            "arrival_time": self.arrival_time,
            "cpu": self.cpu,
            "memory": self.memory,
            "duration": self.duration,
            "app": self.app.name if self.app else None,
            "state": self.state.value,
            "start_time": self.start_time,
            "finish_time": self.finish_time,
            "rejection_reason": self.rejection_reason,
            "timeline": [ts.to_dict() for ts in self.timeline],
        }
