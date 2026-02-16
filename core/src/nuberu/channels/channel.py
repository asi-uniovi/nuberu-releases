import typing

import asimpy


class Channel:
    """Communication channel with configurable latency and close support.

    This class implements a basic communication channel that simulates latency by
    delaying message transmission via the simulation environment's timeout. It uses
    an asimpy.Store to queue messages for asynchronous communication.

    The channel supports graceful closing via the close() method. When closed:
    - All pending messages in the queue are delivered first
    - After pending messages are delivered, receive() returns None
    - Further sends raise ChannelClosedError

    This mimics TCP half-close semantics where one end can signal "no more data"
    while still allowing in-flight data to be delivered.

    Example:
        >>> channel = Channel(env, delay=0.1)
        >>> await channel.send(message)
        >>> channel.close()
        >>> msg = await channel.receive()  # Returns pending message
        >>> msg = await channel.receive()  # Returns None (closed)
    """

    # Internal sentinel to mark end of channel (never exposed to application)
    _CLOSED_SENTINEL = object()

    def __init__(self, env: asimpy.Environment, delay: float = 0):
        self.env = env
        self.delay = delay
        self.store: asimpy.Store = asimpy.Store(env)
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """Returns True if the channel has been closed."""
        return self._closed

    def close(self) -> None:
        """Close the channel. Pending messages are delivered before signaling closure.

        After calling close():
        - No more messages can be sent (raises ChannelClosedError)
        - Receivers will get all pending messages, then None

        This method is idempotent - calling it multiple times has no effect.
        """
        if not self._closed:
            self._closed = True
            # Put sentinel into the channel with the same delay mechanics as regular messages
            # This ensures that messages sent before close() arrive before the sentinel
            self.env.process(self._delayed_put(self._CLOSED_SENTINEL))

    def get_queue_size(self) -> int:
        """Get the current size of the message queue (excluding close sentinel)."""
        count = len(self.store.items)
        # Don't count the sentinel in queue size
        if self._closed and self._CLOSED_SENTINEL in self.store.items:
            count -= 1
        return max(0, count)

    def receive_event(self) -> asimpy.Event:
        """Get the underlying SimPy Event for receiving a message.

        This method exposes the raw SimPy Event from store.get(), which can be
        used directly with asimpy.AnyOf/AllOf for efficient event-based waiting
        without creating intermediate Process objects.

        Note: When using this directly, caller must check if returned value is None
        to detect channel closure.

        Returns:
            SimPy Event that will be triggered when a message is available
        """
        return self.store.get()

    async def send(self, message: typing.Any) -> None:
        """Send a message after applying a delay.

        The sender returns immediately. The message is placed in the channel's
        queue after the delay expires, simulating network latency correctly.

        Raises:
            ChannelClosedError: If the channel has been closed
        """
        if self._closed:
            raise ChannelClosedError("Cannot send on a closed channel")
        # Spawn a process to handle the delay - sender returns immediately
        self.env.process(self._delayed_put(message))

    async def _delayed_put(self, message: typing.Any) -> None:
        """Internal: apply delay then put message in store.

        This runs as a separate process, allowing the sender to continue
        immediately while the message is "in flight" through the channel.
        """
        if self.delay > 0:
            await self.env.timeout(self.delay)
        await self.store.put(message)

    async def receive(self) -> typing.Any | None:
        """Receive a message from the channel.

        Returns:
            The received message, or None if the channel is closed and empty.

        This is an async wrapper around receive_event() for convenience.
        For use with AnyOf/AllOf, prefer receive_event() directly but remember
        to check for None (channel closed).
        """
        msg = await self.store.get()
        if msg is self._CLOSED_SENTINEL:
            # Put the sentinel back for other receivers
            self.store.put(self._CLOSED_SENTINEL)
            return None
        return msg


class ChannelClosedError(Exception):
    """Raised when attempting to send on a closed channel."""

    pass
