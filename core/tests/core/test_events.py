import asimpy

from nuberu.core.events import EventBus, EventTopic


def test_publish_without_subscribers():
    env = asimpy.Environment()
    bus = EventBus(env)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-1"})
        await env.timeout(0.01)

    env.process(scenario())
    env.run(until=1)


def test_multiple_subscribers_receive_event():
    env = asimpy.Environment()
    bus = EventBus(env)
    q1 = asimpy.Store(env)
    q2 = asimpy.Store(env)

    bus.subscribe(EventTopic.VM_STARTED, q1)
    bus.subscribe(EventTopic.VM_STARTED, q2)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-123"})

        async def check():
            e1 = await q1.get()
            e2 = await q2.get()
            assert e1.payload["vm_id"] == "vm-123"
            assert e2.payload["vm_id"] == "vm-123"

        env.process(check())
        await env.timeout(0.1)

    env.process(scenario())
    env.run(until=1)


def test_multiple_events_different_times():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)
    bus.subscribe(EventTopic.VM_STARTED, q)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "a"})
        await env.timeout(1)
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "b"})

        e1 = await q.get()
        e2 = await q.get()
        assert e1.payload["vm_id"] == "a"
        assert e2.payload["vm_id"] == "b"
        assert e2.sim_time > e1.sim_time

    env.process(scenario())
    env.run(until=2)


def test_eventbus_stress_publish_many_events():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)
    bus.subscribe(EventTopic.REQUEST_COMPLETED, q)

    async def scenario():
        for i in range(1000):
            bus.publish(EventTopic.REQUEST_COMPLETED, {"request_id": f"req-{i}"})

        for i in range(1000):
            e = await q.get()
            assert e.payload["request_id"] == f"req-{i}"

    env.process(scenario())
    env.run(until=10)


def test_subscribe_different_topics():
    env = asimpy.Environment()
    bus = EventBus(env)
    q_vm = asimpy.Store(env)
    q_req = asimpy.Store(env)

    bus.subscribe(EventTopic.VM_STARTED, q_vm)
    bus.subscribe(EventTopic.REQUEST_COMPLETED, q_req)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-X"})
        bus.publish(EventTopic.REQUEST_COMPLETED, {"request_id": "req-Y"})

        e1 = await q_vm.get()
        e2 = await q_req.get()

        assert e1.topic == EventTopic.VM_STARTED
        assert e1.payload["vm_id"] == "vm-X"
        assert e2.topic == EventTopic.REQUEST_COMPLETED
        assert e2.payload["request_id"] == "req-Y"

    env.process(scenario())
    env.run(until=2)


def test_event_origin_tracked():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)

    bus.subscribe(EventTopic.VM_STARTED, q)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-42"}, origin="InfraManager")
        event = await q.get()
        assert event.origin == "InfraManager"

    env.process(scenario())
    env.run(until=2)


def test_event_with_empty_payload():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)

    bus.subscribe(EventTopic.VM_STARTED, q)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {})
        event = await q.get()
        assert event.payload == {}
        assert event.topic == EventTopic.VM_STARTED

    env.process(scenario())
    env.run(until=1)


def test_duplicate_subscription_same_queue():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)

    # Double subscription to the same queue
    bus.subscribe(EventTopic.VM_STARTED, q)
    bus.subscribe(EventTopic.VM_STARTED, q)

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-duplicate"})
        e = await q.get()
        assert e.payload["vm_id"] == "vm-duplicate"
        assert len(q.items) == 0  # Only one event delivered, queue is now empty

    env.process(scenario())
    env.run(until=1)


def test_prevent_duplicate_subscription():
    env = asimpy.Environment()
    bus = EventBus(env)
    q = asimpy.Store(env)

    bus.subscribe(EventTopic.VM_STARTED, q)
    bus.subscribe(EventTopic.VM_STARTED, q)  # Should not be added again

    async def scenario():
        bus.publish(EventTopic.VM_STARTED, {"vm_id": "vm-duplicate"})
        event = await q.get()
        assert event.payload["vm_id"] == "vm-duplicate"
        assert q.items == []  # Only one event should be present

    env.process(scenario())
    env.run(until=1)
