"""Timeline tracking for request lifecycle in the simulation.

This module provides data structures for tracking the complete
lifecycle of requests as they flow through the simulation components.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestTimestamp:
    """Timestamp record in the request lifecycle.

    Captures a single event in the request's journey through the system,
    including when it happened, which component instance recorded it,
    what action was performed, and the flow direction (source/target).

    Component IDs are self-describing strings that encode both type and instance:
    - "wi-1": WorkloadInjector instance 1
    - "lb-1": LoadBalancer instance 1
    - "vm-3": VM instance 3
    - "container-5": Container instance 5
    - "runtime-1": RuntimeModel instance 1

    Attributes:
        time: Simulation time when the event occurred
        component_id: Unique identifier of the component recording this event
        event: Type of event (e.g., "send", "receive", "processing_start")
        target_id: Destination component instance ID (for "send" events)
        source_id: Origin component instance ID (for "receive" events)
        metadata: Additional context-specific information

    Examples:
        >>> # VM-3 sends to Container-5
        >>> RequestTimestamp(
        ...     time=10.0,
        ...     component_id="vm-3",
        ...     event="send",
        ...     target_id="container-5"
        ... )

        >>> # Container-5 receives from VM-3
        >>> RequestTimestamp(
        ...     time=15.0,
        ...     component_id="container-5",
        ...     event="receive",
        ...     source_id="vm-3"
        ... )

        >>> # Processing with metadata
        >>> RequestTimestamp(
        ...     time=20.0,
        ...     component_id="runtime-1",
        ...     event="processing_start",
        ...     metadata={"queue_size": 3, "cpu_allocated": 2}
        ... )
    """

    time: float
    component_id: str
    event: str
    target_id: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert timestamp to dictionary for serialization.

        Returns:
            Dictionary with all timestamp fields
        """
        result: dict[str, Any] = {
            "time": self.time,
            "component_id": self.component_id,
            "event": self.event,
        }

        if self.target_id is not None:
            result["target_id"] = self.target_id

        if self.source_id is not None:
            result["source_id"] = self.source_id

        if self.metadata:
            result["metadata"] = self.metadata

        return result
