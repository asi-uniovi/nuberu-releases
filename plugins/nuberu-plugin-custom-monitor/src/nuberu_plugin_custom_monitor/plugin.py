import logging
from typing import Any, Callable

import asimpy
import pluggy
from nuberu.core.events import EventBus, EventTopic
from nuberu.interfaces.protocols import CustomPluginProtocol
from nuberu.plugins import PluginBase
import json

hookimpl = pluggy.HookimplMarker("nuberu")


class CustomSimpleMonitorPluginImplementation:
    """A simple custom monitor plugin implementation that dumps completed/failed requests to a file."""

    def __init__(
        self,
        env: asimpy.Environment,
        event_bus: EventBus,
        dump_file: str | None = None,
        topics: list[EventTopic] | None = None,
        logger: logging.Logger | None = None,
    ):
        # We receive important simulation objects via constructor
        self.env = env  # The simulation environment (asimpy.Environment)
        self.event_bus = event_bus  # The global event bus for pub/sub
        self.dump_file = dump_file  # File to dump request logs to
        self.logger = logger or logging.getLogger(__name__)  # Logger for this plugin
        if topics is None:
            self.topics = [
                # EventTopic.REQUEST_GENERATED,
                EventTopic.REQUEST_COMPLETED,
                EventTopic.REQUEST_LOST,
                EventTopic.REQUEST_REJECTED,
                EventTopic.COST_FINAL,
            ]
        else:
            self.topics = topics
        self.topics.append(EventTopic.END_SIMULATION)

        # We can also set up other internal state here
        self.class_name = self.__class__.__name__
        self.total_cost: float = 0.0

    def prepare(self) -> None:
        # Subscribe to END_SIMULATION so the runtime can stop promptly
        self.queue = asimpy.Store(self.env)
        for topic in self.topics:
            self.event_bus.subscribe(topic, self.queue)
            self.logger.debug(
                f"{self.class_name}: subscribed to {topic.value} at t={self.env.now}"
            )
        self.file = open(self.dump_file, "w") if self.dump_file else None

    def run(self) -> None:
        # Entry point. It simply launches the main sampling loop as a process
        self.logger.info(f"{self.class_name}: Running...")
        self._main_proc = self.env.process(self._loop())

    async def _loop(self) -> None:
        """Main loop. Receives all requests events and logs them."""
        self.logger.info(f"{self.class_name}: Starting monitor loop.")
        simulation_ended = False
        try:
            while True:
                event = await self.queue.get()
                if event.topic == EventTopic.END_SIMULATION:
                    self.logger.info(
                        f"{self.class_name}: END_SIMULATION[{event.payload}] received at t={self.env.now}, entering drain mode"
                    )
                    simulation_ended = True
                    continue
                if event.topic == EventTopic.COST_FINAL:
                    self.logger.info(
                        f"{self.class_name}: COST_FINAL[{event.payload}] received at t={self.env.now}"
                    )
                    self.total_cost = event.payload.get("total_cost", 0.0)
                    continue
                self.logger.debug(
                    f"{self.class_name}: Event {event.topic.value}. Request ID: {event.payload.get('request_id')}"
                )
                self.dump_line(event.topic, event.payload, simulation_ended)
        except Exception as e:
            self.logger.error(f"CustomMonitor loop CRASHED: {e}", exc_info=True)
            raise

    def dump_line(
        self, topic: EventTopic, payload: dict[str, object], simulation_ended: bool
    ) -> None:
        """Dump a single line to the dump file or stdout."""

        if not self.file:
            return  # No dump file specified, skip dumping
        status_map = {
            EventTopic.REQUEST_COMPLETED: "completed",
            EventTopic.REQUEST_LOST: "dropped",
            EventTopic.REQUEST_REJECTED: "rejected",
        }
        payload.update({"status": status_map.get(topic, "unknown")})
        payload.update({"simulation_ended": simulation_ended})
        line = json.dumps(payload)
        self.file.write(line + "\n")

    def finish(self) -> None:
        """Called from nuberu, after the simulation ends.

        All events should have been processed by _loop() during env.run().
        We just need to close the file and write final stats.
        """
        # Sanity check: queue should be empty after env.run()
        if self.queue.items:
            self.logger.warning(
                f"{self.class_name}: Queue not empty after env.run()! "
                f"{len(self.queue.items)} events remaining (this indicates a bug)"
            )

        # Write final cost
        if self.file:
            self.file.write(
                json.dumps({"total_cost": self.total_cost, "simulation_ended": True})
                + "\n"
            )
            self.file.close()

        self.logger.info(f"{self.class_name}: Finishing...")


class CustomSimpleMonitorPlugin(PluginBase):
    plugin_name = "monitor_simple"

    def __init__(self) -> None:
        super().__init__()

    @hookimpl
    def configure(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger.info(f"CustomSimpleMonitorPlugin configured with: {config}")

    @hookimpl
    def get_factory(
        self, config: dict[str, Any]
    ) -> Callable[[asimpy.Environment, EventBus], CustomPluginProtocol]:
        dump_file = config.get("dump_file", None)

        def factory(
            env: asimpy.Environment, event_bus: EventBus
        ) -> CustomPluginProtocol:
            return CustomSimpleMonitorPluginImplementation(
                env,
                event_bus,
                dump_file=dump_file,
                logger=self.logger,
            )

        return factory
