from nuberu import App, Request, RequestState


def test_request_initialization():
    """Test the initialization of a Request object."""
    request = Request(
        request_id="R1",
        arrival_time=10,
        cpu=2,
        memory=1024,
        duration=30,
        app=App("App1"),
    )

    assert request.id == "R1"
    assert request.arrival_time == 10
    assert request.cpu == 2
    assert request.memory == 1024
    assert request.duration == 30
    assert request.app.name == App("App1").name
    assert request.state == RequestState.GENERATED
    assert request.start_time is None
    assert request.finish_time is None


def test_add_timeline_entry():
    """Test adding timeline entries (RFC 004)."""
    request = Request("R2", 5, 4, 512, 20)
    request.add_timeline_entry("Client_generated", 5.0)
    request.add_timeline_entry("LB_receive", 5.1)
    assert len(request.timeline) == 2
    assert request.timeline[0].component_id == "Client_generated"
    assert request.timeline[1].component_id == "LB_receive"


def test_add_timeline_entry_for_processing():
    """Test adding timeline entries for processing (RFC 004)."""
    request = Request("R4", 5, 2, 256, 15)
    request.add_timeline_entry("Container_start_processing", 6)
    assert len(request.timeline) == 1
    assert request.timeline[0].time == 6
    assert request.timeline[0].component_id == "Container_start_processing"


def test_timeline_preserves_chronological_order():
    """Test that timeline entries preserve chronological order."""
    request = Request("R5", 10, 2, 256, 15)
    request.add_timeline_entry("Client_send", 10)
    request.add_timeline_entry("LB_receive", 10.1)
    request.add_timeline_entry("Container_receive", 10.5)
    assert len(request.timeline) == 3
    assert request.timeline[0].time == 10
    assert request.timeline[1].time == 10.1
    assert request.timeline[2].time == 10.5


def test_set_request_rejected():
    """Test rejecting a request (RFC 004)."""
    request = Request("R7", 3, 1, 128, 10)
    assert request.state == RequestState.GENERATED
    request.set_request_rejected(reason="queue_full")
    assert request.state == RequestState.REJECTED
    assert request.rejection_reason == "queue_full"


def test_set_request_rejected_invalid():
    """Test rejecting a request in a terminal state returns False (RFC 004)."""
    request = Request("R8", 3, 1, 128, 10)
    assert request.set_request_completed(10) is True
    assert request.state == RequestState.COMPLETED
    # Attempting to reject a completed request should return False (idempotent)
    assert request.set_request_rejected() is False
    assert request.state == RequestState.COMPLETED  # State unchanged


def test_set_request_completed():
    """Test completing a request successfully (RFC 004)."""
    request = Request("R9", 5, 2, 256, 15)
    # Add timeline entries to simulate processing flow
    request.add_timeline_entry("Container_start_processing", 6)
    request.add_timeline_entry("Container_end_processing", 21)
    # Complete the request
    request.set_request_completed(21)
    assert request.state == RequestState.COMPLETED
    assert request.finish_time == 21


def test_set_request_completed_invalid_state():
    """Test completing a request in a terminal state returns False (RFC 004)."""
    request = Request("R10", 5, 2, 256, 15)
    assert request.set_request_rejected() is True
    assert request.state == RequestState.REJECTED
    # Attempting to complete a rejected request should return False (idempotent)
    assert request.set_request_completed(15) is False
    assert request.state == RequestState.REJECTED  # State unchanged


def test_set_request_completed_with_timeline():
    """Test completing a request with timeline tracking (RFC 004)."""
    request = Request("R11", 5, 2, 256, 15)
    request.add_timeline_entry("Container_start_processing", 10)
    request.add_timeline_entry("Container_end_processing", 15)
    # Complete the request successfully
    assert request.set_request_completed(15) is True
    assert request.state == RequestState.COMPLETED
    assert request.finish_time == 15
    assert len(request.timeline) == 2


def test_request_repr():
    """Test the string representation of a Request object."""
    request = Request("R12", 5, 2, 256, 15, app=App("AppTest"))
    print(request)
    expected_repr = (
        "Request(id=R12, arrival_time=5, cpu=2, memory=256, duration=15, "
        "app='AppTest', state='GENERATED', start_time=None, finish_time=None)"
    )
    assert repr(request) == expected_repr
