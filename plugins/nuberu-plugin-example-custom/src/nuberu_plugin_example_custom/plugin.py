import logging
from typing import Any, Callable

import asimpy
import pluggy
from nuberu.core.events import Event, EventBus, EventTopic
from nuberu.interfaces.protocols import CustomPluginProtocol
from nuberu.plugins import PluginBase

hookimpl = pluggy.HookimplMarker("nuberu")


class ExampleCustomPluginImplementation:
    """This example implements a 'sampling' pattern. The plugin wakes up periodically to
    perform some action (here, just logging a message). It also listens for the
    END_SIMULATION event to stop its operation gracefully.

    The simulator will call the prepare(), run() and finish() methods at the appropriate
    times during the simulation lifecycle.
    """

    def __init__(
        self,
        env: asimpy.Environment,
        event_bus: EventBus,
        message: str,
        period: float = 1.0,
        bar_width: int = 40,
        show_percentage: bool = True,
        logger: logging.Logger | None = None,
    ):
        # We receive important simulation objects via constructor
        self.env = env  # The simulation environment (asimpy.Environment)
        self.event_bus = event_bus  # The global event bus for pub/sub
        self.message = message  # Custom message received from config, as demo
        self.logger = logger or logging.getLogger(__name__)  # Logger for this plugin

        # Sampling and display configuration
        self.period = float(period)
        self.bar_width = int(bar_width)
        self.show_percentage = bool(show_percentage)
        # total_time is not passed via config by default; the runtime will
        # read `env.stop_time` when drawing the bar if available.
        self.total_time = None

        # We can also set up other internal state here
        self.class_name = self.__class__.__name__

    def prepare(self) -> None:
        # Subscribe to END_SIMULATION so the runtime can stop promptly
        self._end_sim_queue = asimpy.Store(self.env)
        self.event_bus.subscribe(EventTopic.END_SIMULATION, self._end_sim_queue)
        self.logger.info(
            f"{self.class_name}: subscribed to END_SIMULATION at t={self.env.now}"
        )

    def run(self) -> None:
        # Entry point. It simply launches the main sampling loop as a process
        self.logger.info(f"{self.class_name}: Running...")
        self._main_proc = self.env.process(self._sampling_loop())

    async def _sampling_loop(self) -> None:
        """Main sampling loop. Wakes up every 'period' time units to perform work.
        Ends when END_SIMULATION event is received.
        """
        self.logger.info(
            f"{self.class_name}: Starting sampling loop. (period={self.period})"
        )
        end_event = (
            self._end_sim_queue.get()
        )  # get() returns a future; it will be awaited below via AnyOf
        while True:
            # Await is done here via AnyOf to wait for either timeout or end_event
            c = await asimpy.AnyOf(self.env, [self.env.timeout(self.period), end_event])
            if end_event in c.events:
                event: Event = end_event.value
                self.logger.debug(
                    f"{self.class_name}: END_SIMULATION[{event.payload}] received at t={self.env.now}, exiting main loop"
                )
                break

            # Timeout completed -> periodic work
            self.every_tick()

    def finish(self) -> None:
        """Called from nuberu, after the simulation ends. Not used here"""
        # Ensure progress bar terminates with a newline so the terminal/logs are clean
        try:
            print()
        except Exception:
            pass
        self.logger.info(f"{self.class_name}: Finishing...")

    def every_tick(self) -> None:
        """Method called every tick (period) to perform work."""
        now = float(self.env.now)
        total = (
            self.total_time
            if self.total_time is not None
            else getattr(self.env, "stop_time", None)
        )
        if total is not None and total > 0:
            pct = min(max(now / float(total), 0.0), 1.0)
            filled = int(self.bar_width * pct)
            bar = "█" * filled + "-" * (self.bar_width - filled)
            # Print progress bar to stdout directly (overwrite the line)
            if self.show_percentage:
                out = f"{self.message}: [{bar}] {pct * 100:5.1f}% (t={now:.2f}/{total})"
            else:
                out = f"{self.message}: [{bar}] t={now:.2f}/{total} {self.message}"
            print(f"\r{out}", end="", flush=True)
        else:
            # Fallback: show elapsed time only
            print(f"{self.message}: t={now:.2f}")


class ExampleCustomPlugin(PluginBase):
    plugin_name = "custom_example"

    def __init__(self) -> None:
        super().__init__()

    @hookimpl
    def configure(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger.info(f"ExampleCustomPlugin configured with: {config}")

    @hookimpl
    def get_factory(
        self, config: dict[str, Any]
    ) -> Callable[[asimpy.Environment, EventBus], CustomPluginProtocol]:
        message = config.get("message", "[No message provided]")
        period = float(config.get("period", 1.0))
        bar_width = int(config.get("bar_width", 40))
        show_percentage = bool(config.get("show_percentage", True))

        def factory(
            env: asimpy.Environment, event_bus: EventBus
        ) -> CustomPluginProtocol:
            return ExampleCustomPluginImplementation(
                env,
                event_bus,
                message,
                period=period,
                bar_width=bar_width,
                show_percentage=show_percentage,
                logger=self.logger,
            )

        return factory
