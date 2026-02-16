"""Tests for DuplexChannel class."""

import asimpy
import pytest

from nuberu.channels import DuplexChannel


class TestDuplexChannelBasic:
    """Basic functionality tests for DuplexChannel."""

    def test_creation_with_defaults(self):
        """Test DuplexChannel creation with default parameters."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env)

        assert duplex.env == env
        assert duplex.forward.delay == 0
        assert duplex.backward.delay == 0

    def test_creation_with_custom_delays(self):
        """Test DuplexChannel creation with custom delays."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=10, backward_delay=5)

        assert duplex.forward.delay == 10
        assert duplex.backward.delay == 5

    def test_queue_size_initial_state(self):
        """Test that queues start empty."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env)

        assert duplex.get_forward_queue_size() == 0
        assert duplex.get_backward_queue_size() == 0


class TestDuplexChannelForwardCommunication:
    """Test forward direction communication."""

    @pytest.mark.asyncio
    async def test_send_receive_forward_no_delay(self):
        """Test forward send/receive with no delay."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=0)

        message = {"type": "request", "id": 1}
        received = None

        async def sender():
            await duplex.send_forward(message)

        async def receiver():
            nonlocal received
            received = await duplex.receive_forward()

        env.process(sender())
        env.process(receiver())
        env.run()

        assert received == message

    @pytest.mark.asyncio
    async def test_send_receive_forward_with_delay(self):
        """Test forward send/receive with delay."""
        env = asimpy.Environment()
        forward_delay = 10
        duplex = DuplexChannel(env, forward_delay=forward_delay)

        message = {"type": "request", "id": 2}
        timestamps = []

        async def sender():
            timestamps.append(("send_start", env.now))
            await duplex.send_forward(message)
            timestamps.append(("send_end", env.now))

        async def receiver():
            timestamps.append(("receive_start", env.now))
            await duplex.receive_forward()
            timestamps.append(("receive_end", env.now))

        env.process(sender())
        env.process(receiver())
        env.run()

        # Verify non-blocking send: sender returns immediately at t=0
        # Message arrives at receiver after delay
        send_end_time = next(t[1] for t in timestamps if t[0] == "send_end")
        receive_end_time = next(t[1] for t in timestamps if t[0] == "receive_end")
        assert send_end_time == 0  # Non-blocking: sender returns immediately
        assert receive_end_time == forward_delay  # Message arrives after delay

    @pytest.mark.asyncio
    async def test_multiple_messages_forward(self):
        """Test sending multiple messages forward."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=0)

        messages = [{"id": i} for i in range(5)]
        received = []

        async def sender():
            for msg in messages:
                await duplex.send_forward(msg)

        async def receiver():
            for _ in range(5):
                msg = await duplex.receive_forward()
                received.append(msg)

        env.process(sender())
        env.process(receiver())
        env.run()

        assert received == messages

    @pytest.mark.asyncio
    async def test_forward_queue_size(self):
        """Test forward queue size tracking.

        With non-blocking send, messages are queued after the spawned process runs.
        With delay=0, this happens in the same simulation instant but after send returns.
        """
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=0)

        messages = [{"id": i} for i in range(3)]

        async def sender():
            for msg in messages:
                await duplex.send_forward(msg)

        env.process(sender())
        env.run()

        # After simulation completes, all messages should be in queue (no receiver)
        assert duplex.get_forward_queue_size() == 3


class TestDuplexChannelBackwardCommunication:
    """Test backward direction communication."""

    @pytest.mark.asyncio
    async def test_send_receive_backward_no_delay(self):
        """Test backward send/receive with no delay."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, backward_delay=0)

        message = {"type": "response", "id": 1}
        received = None

        async def sender():
            await duplex.send_backward(message)

        async def receiver():
            nonlocal received
            received = await duplex.receive_backward()

        env.process(sender())
        env.process(receiver())
        env.run()

        assert received == message

    @pytest.mark.asyncio
    async def test_send_receive_backward_with_delay(self):
        """Test backward send/receive with delay."""
        env = asimpy.Environment()
        backward_delay = 5
        duplex = DuplexChannel(env, backward_delay=backward_delay)

        message = {"type": "response", "id": 2}
        timestamps = []

        async def sender():
            timestamps.append(("send_start", env.now))
            await duplex.send_backward(message)
            timestamps.append(("send_end", env.now))

        async def receiver():
            timestamps.append(("receive_start", env.now))
            await duplex.receive_backward()
            timestamps.append(("receive_end", env.now))

        env.process(sender())
        env.process(receiver())
        env.run()

        # Verify non-blocking send: sender returns immediately at t=0
        # Message arrives at receiver after delay
        send_end_time = next(t[1] for t in timestamps if t[0] == "send_end")
        receive_end_time = next(t[1] for t in timestamps if t[0] == "receive_end")
        assert send_end_time == 0  # Non-blocking: sender returns immediately
        assert receive_end_time == backward_delay  # Message arrives after delay

    @pytest.mark.asyncio
    async def test_backward_queue_size(self):
        """Test backward queue size tracking.

        With non-blocking send, messages are queued after the spawned process runs.
        With delay=0, this happens in the same simulation instant but after send returns.
        """
        env = asimpy.Environment()
        duplex = DuplexChannel(env, backward_delay=0)

        messages = [{"id": i} for i in range(3)]

        async def sender():
            for msg in messages:
                await duplex.send_backward(msg)

        env.process(sender())
        env.run()

        # After simulation completes, all messages should be in queue (no receiver)
        assert duplex.get_backward_queue_size() == 3


class TestDuplexChannelBidirectional:
    """Test bidirectional communication scenarios."""

    @pytest.mark.asyncio
    async def test_request_response_pattern(self):
        """Test typical request-response pattern."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=10, backward_delay=5)

        request = {"type": "request", "id": 1}
        response = {"type": "response", "id": 1, "result": "success"}
        received_request = None
        received_response = None
        timeline = []

        async def client():
            nonlocal received_response
            timeline.append(("client_send", env.now))
            await duplex.send_forward(request)
            timeline.append(("client_sent", env.now))
            received_response = await duplex.receive_backward()
            timeline.append(("client_received", env.now))

        async def server():
            nonlocal received_request
            timeline.append(("server_start", env.now))
            received_request = await duplex.receive_forward()
            timeline.append(("server_received", env.now))
            await duplex.send_backward(response)
            timeline.append(("server_sent", env.now))

        env.process(client())
        env.process(server())
        env.run()

        assert received_request == request
        assert received_response == response

        # Verify timing with non-blocking sends
        client_sent = next(t[1] for t in timeline if t[0] == "client_sent")
        server_received = next(t[1] for t in timeline if t[0] == "server_received")
        server_sent = next(t[1] for t in timeline if t[0] == "server_sent")
        client_received = next(t[1] for t in timeline if t[0] == "client_received")

        # Client send returns immediately (non-blocking)
        assert client_sent == 0
        # Server receives after forward delay
        assert server_received == 10
        # Server send returns immediately (non-blocking)
        assert server_sent == 10
        # Client receives after forward + backward delay
        assert client_received == 10 + 5

    @pytest.mark.asyncio
    async def test_independent_channels(self):
        """Test that forward and backward channels are independent."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=0, backward_delay=0)

        forward_msg = {"direction": "forward"}
        backward_msg = {"direction": "backward"}
        received_forward = None
        received_backward = None

        async def sender():
            # Send to both directions
            await duplex.send_forward(forward_msg)
            await duplex.send_backward(backward_msg)

        async def receiver():
            nonlocal received_forward, received_backward
            # Receive from correct directions
            received_forward = await duplex.receive_forward()
            received_backward = await duplex.receive_backward()

        env.process(sender())
        env.process(receiver())
        env.run()

        assert received_forward == forward_msg
        assert received_backward == backward_msg

    @pytest.mark.asyncio
    async def test_asymmetric_delays(self):
        """Test different delays for forward and backward."""
        env = asimpy.Environment()
        forward_delay = 20
        backward_delay = 5
        duplex = DuplexChannel(
            env, forward_delay=forward_delay, backward_delay=backward_delay
        )

        forward_time = None
        backward_time = None

        async def test_forward():
            nonlocal forward_time
            await duplex.send_forward({"test": "forward"})
            forward_time = env.now

        async def test_backward():
            nonlocal backward_time
            await duplex.send_backward({"test": "backward"})
            backward_time = env.now

        env.process(test_forward())
        env.process(test_backward())
        env.run()

        # Non-blocking: both sends return immediately at t=0
        assert forward_time == 0
        assert backward_time == 0


class TestDuplexChannelEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_receive_blocks_until_message(self):
        """Test that receive blocks until a message is sent."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env)

        received = None
        receive_time = None

        async def delayed_sender():
            await env.timeout(15)  # Wait 15 time units
            await duplex.send_forward({"delayed": True})

        async def receiver():
            nonlocal received, receive_time
            received = await duplex.receive_forward()
            receive_time = env.now

        env.process(delayed_sender())
        env.process(receiver())
        env.run()

        assert received == {"delayed": True}
        assert receive_time == 15

    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        """Test that messages maintain FIFO order."""
        env = asimpy.Environment()
        duplex = DuplexChannel(env, forward_delay=0)

        messages = [{"order": i} for i in range(10)]
        received = []

        async def sender():
            for msg in messages:
                await duplex.send_forward(msg)

        async def receiver():
            for _ in range(10):
                msg = await duplex.receive_forward()
                received.append(msg)

        env.process(sender())
        env.process(receiver())
        env.run()

        # Verify FIFO order
        assert received == messages
        assert [msg["order"] for msg in received] == list(range(10))


class TestNonBlockingSendBehavior:
    """Tests specifically for non-blocking send behavior with delays.

    These tests verify that the Channel correctly implements non-blocking
    semantics: send() returns immediately, messages arrive after delay.
    """

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sends_no_cumulative_delay(self):
        """Verify that multiple sends at t=0 don't accumulate delays.

        This is the KEY test for the bug fix. Previously, 100 sends at t=0
        with delay=10 would cause messages to arrive at t=10, 20, 30...1000.

        Correct behavior: all sends at t=0 should arrive at t=delay.
        """
        env = asimpy.Environment()
        channel_delay = 10
        duplex = DuplexChannel(env, forward_delay=channel_delay)

        num_messages = 100
        arrival_times = []
        send_times = []

        async def sender():
            for i in range(num_messages):
                send_times.append(env.now)
                await duplex.send_forward({"id": i})

        async def receiver():
            for _ in range(num_messages):
                await duplex.receive_forward()
                arrival_times.append(env.now)

        env.process(sender())
        env.process(receiver())
        env.run()

        # All sends should complete at t=0 (non-blocking)
        assert all(t == 0 for t in send_times), "All sends should return at t=0"

        # ALL messages should arrive at the SAME time (delay, not cumulative)
        assert all(t == channel_delay for t in arrival_times), (
            f"All messages should arrive at t={channel_delay}, got {set(arrival_times)}"
        )

    @pytest.mark.asyncio
    async def test_send_returns_immediately_with_large_delay(self):
        """Verify send returns at t=0 even with a very large delay."""
        env = asimpy.Environment()
        large_delay = 1000
        duplex = DuplexChannel(env, forward_delay=large_delay)

        send_return_time = None

        async def sender():
            nonlocal send_return_time
            await duplex.send_forward({"test": "message"})
            send_return_time = env.now

        env.process(sender())
        # Only run until t=1 - if send is blocking, it would need to run to t=1000
        env.run(until=1)

        # Send should have returned at t=0, not blocked until t=1000
        assert send_return_time == 0
