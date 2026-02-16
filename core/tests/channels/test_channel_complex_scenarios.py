import asimpy
import pytest

from nuberu.channels.channel import Channel
from nuberu.channels.duplex_channel import DuplexChannel
from nuberu.channels.multi_channel_receiver import MultiChannelReceiver


class TestChannelStrategies:
    """Comprehensive tests for Channel EOT and multi-consumer behaviors."""

    @pytest.mark.asyncio
    async def test_shared_sentinel_basic(self):
        """Verify standard Channel allows multiple consumers to see EOT."""
        env = asimpy.Environment()
        channel = Channel(env)

        results = []

        async def consumer(idx):
            res = await channel.receive()
            results.append((idx, res))

        env.process(consumer(1))
        env.process(consumer(2))

        async def main():
            # Close immediately
            channel.close()
            # Give time for consumers
            await env.timeout(0.1)

        env.process(main())
        env.run()

        # Both should receive None
        assert len(results) == 2
        # Order is not strictly guaranteed but both must be None
        assert results[0][1] is None
        assert results[1][1] is None

    @pytest.mark.asyncio
    async def test_drain_before_close_shared(self):
        """Verify multiple consumers drain queue before seeing EOT."""
        env = asimpy.Environment()
        channel = Channel(env)

        received = []

        async def consumer():
            while True:
                msg = await channel.receive()
                if msg is None:
                    break
                received.append(msg)

        # Start 2 consumers
        env.process(consumer())
        env.process(consumer())

        async def main():
            # Put 2 messages
            await channel.send("msg1")
            await channel.send("msg2")
            channel.close()
            # Allow processing
            await env.timeout(0.1)

        env.process(main())
        env.run()

        # Should get both messages then stop
        assert sorted(received) == ["msg1", "msg2"]

    @pytest.mark.asyncio
    async def test_mcr_and_standard_consumer_shared(self):
        """Verify verification of fix: MCR and standard consumer sharing channel."""
        env = asimpy.Environment()
        d1 = DuplexChannel(env)
        channels = {"c1": d1}
        mcr = MultiChannelReceiver(env, channels, direction="forward")

        results_std = []
        results_mcr = []

        async def standard_consumer():
            res = await d1.receive_forward()
            results_std.append(res)

        env.process(standard_consumer())

        async def main():
            d1.close_forward()

            # Run MCR
            # We must wrap this in the process or await it here
            key, msg = await mcr.receive_any()
            results_mcr.append((key, msg))

            # Run enough for standard consumer to pick up re-queued sentinel
            await env.timeout(0)
            await env.timeout(0)

        env.process(main())
        env.run()

        # MCR should see close
        assert results_mcr == [("c1", None)]
        # Standard consumer should also see close (None)
        assert results_std == [None]


class TestMultiChannelReceiverEdgeCases:
    """Tests for MultiChannelReceiver specific edge cases."""

    @pytest.mark.asyncio
    async def test_mcr_exhaustion(self):
        """Verify MCR returns (None, None) when all channels close."""
        env = asimpy.Environment()
        d1 = DuplexChannel(env)
        d2 = DuplexChannel(env)

        mcr = MultiChannelReceiver(env, {"c1": d1, "c2": d2})

        async def main():
            d1.close_forward()
            d2.close_forward()

            # Should get c1 close
            k1, m1 = await mcr.receive_any()
            assert m1 is None

            # Should get c2 close
            k2, m2 = await mcr.receive_any()
            assert m2 is None

            # Should be exhausted
            k_end, m_end = await mcr.receive_any()
            assert k_end is None
            assert m_end is None
            assert mcr.is_exhausted

        env.process(main())
        env.run()

    @pytest.mark.asyncio
    async def test_mcr_dynamic_close(self):
        """Verify MCR handles channels closing mid-stream."""
        env = asimpy.Environment()
        d1 = DuplexChannel(env)
        mcr = MultiChannelReceiver(env, {"c1": d1})

        async def main():
            await d1.send_forward("msg1")
            # Ensure message is queued before closing (send is non-blocking)
            await env.timeout(0)
            d1.close_forward()

            # Receive msg1
            k1, m1 = await mcr.receive_any()
            assert m1 == "msg1"

            # Receive close
            k2, m2 = await mcr.receive_any()
            assert m2 is None
            assert mcr.is_exhausted

        env.process(main())
        env.run()


class TestHighConcurrency:
    """Tests for high concurrency scenarios."""

    @pytest.mark.asyncio
    async def test_massive_concurrency_on_close(self):
        """Verify 50 concurrent consumers all detect closure correctly."""
        env = asimpy.Environment()
        channel = Channel(env)

        num_consumers = 50
        results = [0] * num_consumers

        async def consumer(idx):
            # All wait on the same channel
            msg = await channel.receive()
            results[idx] = msg

        # Spawn 50 consumers
        for i in range(num_consumers):
            env.process(consumer(i))

        async def main():
            # Close the channel while everyone is waiting
            # This triggers the "sentinel cascade"
            channel.close()

            # Allow time for the cascade to propagate
            # Each 'put' might require a tick or a schedule cycle
            # We wait enough time
            await env.timeout(1)

        env.process(main())
        env.run()

        # Verify ALL received None
        assert len(results) == num_consumers
        assert all(r is None for r in results), (
            f"Some consumers did not get None: {results}"
        )

    @pytest.mark.asyncio
    async def test_race_messages_and_close(self):
        """Race condition: Many messages + Close vs Many consumers."""
        env = asimpy.Environment()
        channel = Channel(env)

        num_consumers = 20
        num_messages = 10

        received_messages = []
        closed_consumers = 0

        async def consumer():
            nonlocal closed_consumers
            while True:
                msg = await channel.receive()
                if msg is None:
                    closed_consumers += 1
                    break
                received_messages.append(msg)

        for _ in range(num_consumers):
            env.process(consumer())

        async def producer():
            # Send messages rapidly
            for i in range(num_messages):
                await channel.send(f"msg_{i}")
            # Then close
            channel.close()

        env.process(producer())

        # Run enough to drain
        env.run(until=10)

        # Check consistency
        # 1. All messages received
        assert len(received_messages) == num_messages
        # 2. All consumers saw the close
        assert closed_consumers == num_consumers
