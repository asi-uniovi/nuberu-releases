from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

import asimpy


class EventTopic(Enum):
    """
    Enumeration of all possible event topics that components can publish or subscribe to.
    Extend this enum as needed for new event types.
    """

    ALLOCATION_RECEIVED = "ALLOCATION_RECEIVED"
    ALLOCATION_APPLIED = "ALLOCATION_APPLIED"

    INFRASTRUCTURE_READY = "INFRASTRUCTURE_READY"

    VM_STARTED = "VM_STARTED"
    VM_STOPPED = "VM_STOPPED"

    CONTAINER_READY = "CONTAINER_READY"
    CONTAINER_DRAINING = (
        "CONTAINER_DRAINING"  # Container stops accepting new requests (drain mode)
    )
    CONTAINER_STOPPED = "CONTAINER_STOPPED"
    CONTAINER_REMOVED = "CONTAINER_REMOVED"

    # Request lifecycle events (simplified - RFC 004)
    REQUEST_GENERATED = "REQUEST_GENERATED"  # Request created by client
    REQUEST_REJECTED = "REQUEST_REJECTED"  # Request rejected by system
    REQUEST_LOST = "REQUEST_LOST"  # Request lost/timeout
    REQUEST_COMPLETED = "REQUEST_COMPLETED"  # Full round-trip complete

    END_SIMULATION = "END_SIMULATION"  # Signals stop_time reached, triggers shutdown
    SIMULATION_FINISHED = (
        "SIMULATION_FINISHED"  # All shutdown complete, triggers reporting
    )
    COST_FINAL = "COST_FINAL"  # Final cost report (published by CostModels after SIMULATION_FINISHED)


@dataclass
class Event:
    """
    Event represents a message broadcast through the EventBus.

    Attributes:
        topic (EventTopic): The type of event.
        payload (dict[str, object]): Event-specific data.
        sim_time (float): The simulation time when the event was published.
        origin (str | None): Optional identifier of the component that published the event.
        correlation_id (str | None): Optional identifier for correlating events (e.g., for tracing).
        event_id (str): Unique identifier for this event instance (used for tracing/debug).
    """

    topic: EventTopic
    payload: dict[str, object]
    sim_time: float
    origin: str | None = None
    correlation_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def _to_dict(self) -> dict[str, object]:
        """
        Convert the event to a dictionary representation for serialization or logging.

        Returns:
            dict[str, object]: Dictionary containing event data.
        """
        return {
            "topic": self.topic.value,
            "payload": self.payload,
            "sim_time": self.sim_time,
            "origin": self.origin,
            "correlation_id": self.correlation_id,
            "event_id": self.event_id,
        }


class EventBus:
    """
    EventBus is a publish/subscribe mechanism for communication between components in a decoupled way.
    Each subscriber listens on a dedicated queue for specific event topics.
    """

    def __init__(self, env: asimpy.Environment) -> None:
        self.env: asimpy.Environment = env
        self._subscribers: dict[EventTopic, list[asimpy.Store]] = {}

    def subscribe(self, topic: EventTopic, subscriber_queue: asimpy.Store) -> None:
        """
        Subscribe a queue to receive events for the given topic.

        Args:
            topic (EventTopic): Topic to subscribe to.
            subscriber_queue (asimpy.Store): Queue where events will be pushed.
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = []

        if subscriber_queue not in self._subscribers[topic]:
            self._subscribers[topic].append(subscriber_queue)

    def publish(
        self,
        topic: EventTopic,
        payload: dict[str, object],
        origin: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """
        Publish a new event to all subscribers of the given topic.

        Args:
            topic (EventTopic): The topic of the event.
            payload (dict): The event data.
            origin (str | None): Optional identifier of the sender.
            correlation_id (str | None): Optional identifier for correlating events (e.g., for tracing).
        """
        event = Event(
            topic=topic,
            payload=payload,
            sim_time=self.env.now,
            origin=origin,
            correlation_id=correlation_id,
        )
        for queue in self._subscribers.get(topic, []):
            queue.put(event)


class Signal:
    """
    A synchronization primitive that allows waiting for a notification.
    It automatically resets after being awaited, acting like an AutoResetEvent.
    """

    def __init__(self, env: asimpy.Environment):
        self.env = env
        self._event = env.event()

    def set(self) -> None:
        """Trigger the signal. Wakes up any current or future waiter."""
        if not self._event.triggered:
            self._event.succeed()

    async def wait(self) -> None:
        """Wait until the signal is set. Resets automatically after waking up."""
        await self._event
        self._event = self.env.event()

    def reset(self) -> None:
        """Manually reset the signal (re-arm) if it was triggered. Useful after external checks."""
        if self._event.triggered:
            self._event = self.env.event()

    @property
    def event(self) -> asimpy.Event:
        """Access the underlying event (e.g. for AnyOf)."""
        return self._event


class BlockingFlag:
    """
    A blocking condition variable (latch) implementation for SimPy.
    Once set, it remains set unless explicitly reset.
    """

    def __init__(self, env: asimpy.Environment):
        self.env = env
        self._event = self.env.event()

    def set(self) -> None:
        """
        Sets the condition to True.
        This operation is idempotent: if it is already True, nothing changes.
        """
        if not self._event.triggered:
            self._event.succeed()

    @property
    def event(self) -> asimpy.Event:
        """
        Returns the underlying simpy Event.
        Allows usage with AnyOf/AllOf.
        """
        return self._event

    def wait(self) -> asimpy.Event:
        """
        Returns the event object to be yielded/awaited directly.
        """
        return self._event

    @property
    def is_set(self) -> bool:
        """Returns True if the condition is currently met."""
        return self._event.triggered
