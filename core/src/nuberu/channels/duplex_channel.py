import typing

import asimpy

from nuberu.channels.channel import Channel


class DuplexChannel:
    """Bidirectional communication channel using two unidirectional channels.

    This class provides a duplex (bidirectional) communication mechanism by wrapping
    two independent Channel instances: one for forward communication and one for
    backward communication. This design allows for realistic modeling of network
    round-trip scenarios with separate latencies for each direction.

    The DuplexChannel supports half-close semantics (like TCP):
    - close_forward(): Closes forward direction, backward remains open
    - close_backward(): Closes backward direction, forward remains open

    When a direction is closed:
    - Pending messages in that direction are delivered first
    - After pending messages, receive returns None
    - Further sends in that direction raise ChannelClosedError

    The DuplexChannel is intended for request-response patterns where messages flow
    in both directions between components (e.g., WorkloadInjector <-> LoadBalancer <-> VM).

    Example:
        >>> duplex = DuplexChannel(env, forward_delay=10, backward_delay=5)
        >>> await duplex.send_forward(request)
        >>> duplex.close_backward()  # Signal no more responses coming
        >>> response = await duplex.receive_backward()  # Returns None
    """

    def __init__(
        self,
        env: asimpy.Environment,
        forward_delay: float = 0,
        backward_delay: float = 0,
    ):
        """Initialize a bidirectional channel with separate delays.

        Args:
            env: The simulation environment
            forward_delay: Delay in seconds for forward direction (default: 0)
            backward_delay: Delay in seconds for backward direction (default: 0)
        """
        self.env = env
        self.forward = Channel(env, delay=forward_delay)
        self.backward = Channel(env, delay=backward_delay)

    # === Close methods ===

    def close_forward(self) -> None:
        """Close the forward direction. No more messages can be sent forward.

        Pending messages in the forward queue are delivered before signaling closure.
        After all pending messages are received, receive_forward() returns None.
        """
        self.forward.close()

    def close_backward(self) -> None:
        """Close the backward direction. No more messages can be sent backward.

        Pending messages in the backward queue are delivered before signaling closure.
        After all pending messages are received, receive_backward() returns None.
        """
        self.backward.close()

    @property
    def is_forward_closed(self) -> bool:
        """Returns True if the forward direction has been closed."""
        return self.forward.is_closed

    @property
    def is_backward_closed(self) -> bool:
        """Returns True if the backward direction has been closed."""
        return self.backward.is_closed

    # === Forward direction ===

    async def send_forward(self, message: typing.Any) -> None:
        """Send a message in the forward direction.

        Args:
            message: The message to send

        Raises:
            ChannelClosedError: If the forward direction has been closed
        """
        await self.forward.send(message)

    def receive_forward_event(self) -> asimpy.Event:
        """Get the underlying SimPy Event for receiving from forward direction.

        This method exposes the raw SimPy Event, allowing efficient use with
        asimpy.AnyOf/AllOf without creating intermediate Process objects.

        Note: Caller must check if returned value is None to detect channel closure.

        Returns:
            SimPy Event that will be triggered when a forward message is available
        """
        return self.forward.receive_event()

    async def receive_forward(self) -> typing.Any | None:
        """Receive a message from the forward direction.

        Returns:
            The received message, or None if the forward direction is closed and empty.

        This is an async wrapper for convenience. For use with AnyOf/AllOf,
        prefer receive_forward_event() directly.
        """
        return await self.forward.receive()

    # === Backward direction ===

    async def send_backward(self, message: typing.Any) -> None:
        """Send a message in the backward direction.

        Args:
            message: The message to send

        Raises:
            ChannelClosedError: If the backward direction has been closed
        """
        await self.backward.send(message)

    def receive_backward_event(self) -> asimpy.Event:
        """Get the underlying SimPy Event for receiving from backward direction.

        This method exposes the raw SimPy Event, allowing efficient use with
        asimpy.AnyOf/AllOf without creating intermediate Process objects.

        Note: Caller must check if returned value is None to detect channel closure.

        Returns:
            SimPy Event that will be triggered when a backward message is available
        """
        return self.backward.receive_event()

    async def receive_backward(self) -> typing.Any | None:
        """Receive a message from the backward direction.

        Returns:
            The received message, or None if the backward direction is closed and empty.

        This is an async wrapper for convenience. For use with AnyOf/AllOf,
        prefer receive_backward_event() directly.
        """
        return await self.backward.receive()

    # === Queue inspection ===

    def get_forward_queue_size(self) -> int:
        """Get the current size of the forward channel queue.

        Returns:
            Number of messages in the forward queue (excluding close sentinel)
        """
        return self.forward.get_queue_size()

    def get_backward_queue_size(self) -> int:
        """Get the current size of the backward channel queue.

        Returns:
            Number of messages in the backward queue (excluding close sentinel)
        """
        return self.backward.get_queue_size()
