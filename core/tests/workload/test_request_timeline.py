"""Tests for Request timeline functionality."""

from nuberu.core.states import RequestState
from nuberu.workload import Request, RequestTimestamp


class TestRequestTimestamp:
    """Test RequestTimestamp dataclass."""

    def test_creation_basic(self):
        """Test basic RequestTimestamp creation."""
        ts = RequestTimestamp(time=10.5, component_id="lb-1", event="receive")

        assert ts.time == 10.5
        assert ts.component_id == "lb-1"
        assert ts.event == "receive"
        assert ts.target_id is None
        assert ts.source_id is None
        assert ts.metadata == {}

    def test_creation_with_target(self):
        """Test creating timestamp with target component."""
        ts = RequestTimestamp(
            time=10.0, component_id="wi-1", event="send", target_id="lb-1"
        )

        assert ts.target_id == "lb-1"
        assert ts.source_id is None

    def test_creation_with_source(self):
        """Test creating timestamp with source component."""
        ts = RequestTimestamp(
            time=15.0, component_id="lb-1", event="receive", source_id="wi-1"
        )

        assert ts.source_id == "wi-1"
        assert ts.target_id is None

    def test_creation_with_metadata(self):
        """Test creating timestamp with metadata."""
        ts = RequestTimestamp(
            time=20.0,
            component_id="vm-3",
            event="processing_start",
            metadata={"cpu_load": 0.75},
        )

        assert ts.metadata == {"cpu_load": 0.75}

    def test_to_dict_minimal(self):
        """Test serialization of minimal timestamp."""
        ts = RequestTimestamp(time=15.0, component_id="vm-2", event="processing_end")

        result = ts.to_dict()

        assert result == {
            "time": 15.0,
            "component_id": "vm-2",
            "event": "processing_end",
        }

    def test_to_dict_with_target(self):
        """Test serialization with target component."""
        ts = RequestTimestamp(
            time=10.0, component_id="wi-1", event="send", target_id="lb-1"
        )

        result = ts.to_dict()

        assert result == {
            "time": 10.0,
            "component_id": "wi-1",
            "event": "send",
            "target_id": "lb-1",
        }

    def test_to_dict_with_metadata(self):
        """Test serialization with metadata."""
        ts = RequestTimestamp(
            time=20.0,
            component_id="runtime-1",
            event="processing_end",
            metadata={"duration_ms": 150},
        )

        result = ts.to_dict()

        assert result == {
            "time": 20.0,
            "component_id": "runtime-1",
            "event": "processing_end",
            "metadata": {"duration_ms": 150},
        }

    def test_equality(self):
        """Test RequestTimestamp equality comparison."""
        ts1 = RequestTimestamp(10.0, "container-1", "send")
        ts2 = RequestTimestamp(10.0, "container-1", "send")
        ts3 = RequestTimestamp(20.0, "container-1", "send")

        assert ts1 == ts2
        assert ts1 != ts3


class TestRequestTimeline:
    """Test Request timeline functionality."""

    def test_request_initializes_with_empty_timeline(self):
        """Test that new requests have empty timeline."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        assert req.timeline == []
        assert isinstance(req.timeline, list)

    def test_timeline_can_be_appended(self):
        """Test that timestamps can be appended to timeline."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        ts1 = RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1")
        ts2 = RequestTimestamp(5.0, "lb-1", "receive", source_id="wi-1")

        req.timeline.append(ts1)
        req.timeline.append(ts2)

        assert len(req.timeline) == 2
        assert req.timeline[0] == ts1
        assert req.timeline[1] == ts2

    def test_timeline_preserves_order(self):
        """Test that timeline maintains insertion order."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        timestamps = [
            RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1"),
            RequestTimestamp(5.0, "lb-1", "receive", source_id="wi-1"),
            RequestTimestamp(10.0, "lb-1", "send", target_id="vm-1"),
            RequestTimestamp(15.0, "vm-1", "receive", source_id="lb-1"),
            RequestTimestamp(20.0, "runtime-1", "processing_start"),
        ]

        for ts in timestamps:
            req.timeline.append(ts)

        assert req.timeline == timestamps

    def test_timeline_in_to_dict(self):
        """Test that timeline is included in request serialization."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        req.timeline.append(RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1"))
        req.timeline.append(RequestTimestamp(5.0, "lb-1", "receive", source_id="wi-1"))

        result = req._to_dict()

        assert "timeline" in result
        assert isinstance(result["timeline"], list)
        assert len(result["timeline"]) == 2
        assert result["timeline"][0] == {
            "time": 0.0,
            "component_id": "wi-1",
            "event": "send",
            "target_id": "lb-1",
        }
        assert result["timeline"][1] == {
            "time": 5.0,
            "component_id": "lb-1",
            "event": "receive",
            "source_id": "wi-1",
        }

    def test_empty_timeline_in_to_dict(self):
        """Test that empty timeline is serialized correctly."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        result = req._to_dict()

        assert "timeline" in result
        assert result["timeline"] == []


class TestRequestTimelineScenarios:
    """Test realistic timeline scenarios."""

    def test_complete_forward_flow(self):
        """Test timeline for complete forward request flow."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        # Simulate forward flow
        req.timeline.append(RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1"))
        req.timeline.append(RequestTimestamp(10.0, "lb-1", "receive", source_id="wi-1"))
        req.timeline.append(RequestTimestamp(10.0, "lb-1", "send", target_id="vm-1"))
        req.timeline.append(RequestTimestamp(15.0, "vm-1", "receive", source_id="lb-1"))
        req.timeline.append(
            RequestTimestamp(15.0, "vm-1", "send", target_id="container-1")
        )
        req.timeline.append(
            RequestTimestamp(20.0, "container-1", "receive", source_id="vm-1")
        )
        req.timeline.append(RequestTimestamp(20.0, "runtime-1", "processing_start"))
        req.timeline.append(RequestTimestamp(30.0, "runtime-1", "processing_end"))

        assert len(req.timeline) == 8

    def test_bidirectional_flow(self):
        """Test timeline for complete bidirectional flow (request + response)."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        # Forward flow
        req.timeline.append(RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1"))
        req.timeline.append(RequestTimestamp(10.0, "lb-1", "receive", source_id="wi-1"))
        req.timeline.append(RequestTimestamp(10.0, "lb-1", "send", target_id="vm-1"))
        req.timeline.append(RequestTimestamp(15.0, "vm-1", "receive", source_id="lb-1"))
        req.timeline.append(RequestTimestamp(20.0, "runtime-1", "processing_start"))
        req.timeline.append(RequestTimestamp(30.0, "runtime-1", "processing_end"))

        # Backward flow (responses)
        req.timeline.append(
            RequestTimestamp(30.0, "runtime-1", "send", target_id="vm-1")
        )
        req.timeline.append(
            RequestTimestamp(35.0, "vm-1", "receive", source_id="runtime-1")
        )
        req.timeline.append(RequestTimestamp(35.0, "vm-1", "send", target_id="lb-1"))
        req.timeline.append(RequestTimestamp(40.0, "lb-1", "receive", source_id="vm-1"))
        req.timeline.append(RequestTimestamp(40.0, "lb-1", "send", target_id="wi-1"))
        req.timeline.append(RequestTimestamp(50.0, "wi-1", "receive", source_id="lb-1"))

        assert len(req.timeline) == 12

        # Verify first and last events
        assert req.timeline[0].component_id == "wi-1"
        assert req.timeline[0].event == "send"
        assert req.timeline[-1].component_id == "wi-1"
        assert req.timeline[-1].event == "receive"

    def test_timeline_latency_calculation(self):
        """Test that timeline enables latency calculations."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        req.timeline.append(RequestTimestamp(0.0, "wi-1", "send", target_id="lb-1"))
        req.timeline.append(RequestTimestamp(10.0, "lb-1", "receive", source_id="wi-1"))
        req.timeline.append(RequestTimestamp(50.0, "wi-1", "receive", source_id="lb-1"))

        # Calculate network latency (WI to LB)
        sent_time = next(
            ts.time
            for ts in req.timeline
            if ts.component_id == "wi-1" and ts.event == "send"
        )
        received_time = next(
            ts.time
            for ts in req.timeline
            if ts.component_id == "lb-1" and ts.event == "receive"
        )
        network_latency = received_time - sent_time
        assert network_latency == 10.0

        # Calculate round-trip time
        response_time = next(
            ts.time
            for ts in req.timeline
            if ts.component_id == "wi-1" and ts.event == "receive"
        )
        round_trip = response_time - sent_time
        assert round_trip == 50.0


class TestBackwardCompatibility:
    """Test that existing Request functionality still works."""

    def test_request_creation_without_timeline_usage(self):
        """Test that Request works normally without using timeline."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        # All existing functionality should work
        assert req.id == "req1"
        assert req.arrival_time == 0
        assert req.state == RequestState.GENERATED
        assert req.start_time is None
        assert req.finish_time is None

    def test_request_state_transitions_with_timeline(self):
        """Test that state transitions work alongside timeline (RFC 004 - simplified)."""
        req = Request(request_id="req1", arrival_time=0, cpu=1, memory=100, duration=10)

        # Add timeline entries using new API
        req.add_timeline_entry("wi-1_send", 0.0)
        req.add_timeline_entry("lb-1_receive", 0.1)
        req.add_timeline_entry("container-5_start_processing", 5.0)
        req.add_timeline_entry("container-5_end_processing", 15.0)

        # Perform state transition (GENERATED -> COMPLETED)
        req.set_request_completed(15.0)
        assert req.state == RequestState.COMPLETED
        assert req.finish_time == 15.0

        # Timeline should have all our entries
        assert len(req.timeline) == 4
