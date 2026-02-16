"""Helper for receiving from multiple DuplexChannels using AnyOf pattern.

This module provides a utility class that encapsulates the boilerplate required
to wait on multiple aSimpy channels concurrently, handling the complexity of:
- Managing pending receive events per channel
- Using AnyOf to wait for any channel to have data
- Cleaning up triggered events to avoid "zombie gets"
- Handling channel closures (None returns)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

import asimpy

from .channel import Channel

if TYPE_CHECKING:
    from .duplex_channel import DuplexChannel

logger = logging.getLogger(__name__)


class MultiChannelReceiver:
    """Utility for receiving from multiple DuplexChannels efficiently.

    The receiver does NOT own the channels dictionary - it only holds a reference.
    The caller is responsible for managing channel lifecycle (add/remove).
    Changes to the referenced dict are automatically visible to the receiver.

    Example:
        ```python
        receiver = MultiChannelReceiver(env, channels_dict, "forward")

        while not receiver.is_exhausted:
            key, message = await receiver.receive_any()
            if message is None:
                continue  # Channel was closed
            # Process message...
        ```

    Args:
        env: aSimpy simulation environment.
        channels: Reference to dict mapping keys to DuplexChannels.
            Caller owns this dict; receiver just references it.
        direction: Which direction to receive from ("forward" or "backward").
    """

    def __init__(
        self,
        env: asimpy.Environment,
        channels: dict[str, DuplexChannel],
        direction: Literal["forward", "backward"] = "forward",
    ) -> None:
        self.env = env
        self._channels = channels  # Reference only, caller owns
        self._direction = direction
        self._pending_events: dict[str, asimpy.Event] = {}
        self._closed_keys: set[str] = set()  # Track closed channels

    @property
    def is_exhausted(self) -> bool:
        """True if no active channels remain."""
        # Active = in dict AND not closed
        return not any(k for k in self._channels if k not in self._closed_keys)

    async def receive_any(self) -> tuple[str | None, Any]:
        """Wait for a message from any active channel.

        Returns:
            (key, message): The channel key and received message.
            (key, None): The channel was closed (removed from active set).
            (None, None): All channels are exhausted.

        Note:
            When a channel returns None (closed), it is automatically marked
            as closed internally. Subsequent calls will not listen to it.
        """
        # Filter to only active channels (in dict and not closed)
        active_keys = [k for k in self._channels if k not in self._closed_keys]

        if not active_keys:
            return None, None

        # Clean up pending events for keys no longer active
        for key in list(self._pending_events.keys()):
            if key not in active_keys:
                del self._pending_events[key]

        # Create pending events for active channels that don't have one
        for key in active_keys:
            if key not in self._pending_events:
                channel = self._channels[key]
                if self._direction == "forward":
                    self._pending_events[key] = channel.receive_forward_event()
                else:
                    self._pending_events[key] = channel.receive_backward_event()

        if not self._pending_events:
            return None, None

        # Wait for any channel to have data
        condition = asimpy.AnyOf(self.env, list(self._pending_events.values()))
        results = await condition

        # Process triggered events
        for winner_event, message in results.items():
            # Find which key's event triggered
            winner_key = None
            for key, evt in self._pending_events.items():
                if evt is winner_event:
                    winner_key = key
                    break

            if winner_key is None:
                logger.warning("Winner event not found in pending_events")
                continue

            # Remove triggered event (it's consumed)
            del self._pending_events[winner_key]

            # Handle channel closure (sentinel or None)
            if message is None or message is Channel._CLOSED_SENTINEL:
                self._closed_keys.add(winner_key)

                # Put the closure signal (Sentinel OR None) back for other consumers
                # Safety check: channel might have been removed from the dict while waiting
                winner_channel = self._channels.get(winner_key)
                if winner_channel:
                    if self._direction == "forward":
                        winner_channel.forward.store.put(message)
                    else:
                        winner_channel.backward.store.put(message)

                logger.debug(f"MultiChannelReceiver: channel '{winner_key}' closed")
                return winner_key, None

            # Return first successful message
            return winner_key, message

        # Should not reach here, but safety fallback
        return None, None

    def reset_channel(self, key: str) -> None:
        """Re-enable a previously closed channel.

        Useful if a channel is replaced with a new one under the same key.
        """
        self._closed_keys.discard(key)
        self._pending_events.pop(key, None)
