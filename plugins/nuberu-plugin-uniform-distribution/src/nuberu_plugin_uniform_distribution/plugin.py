from nuberu.plugins.hookspecs import ArrivalDistributionSpecs
from typing import Callable, Iterator

import pluggy

hookimpl = pluggy.HookimplMarker("nuberu")


class UniformDistribution(ArrivalDistributionSpecs):
    def __init__(self):
        """
        Initializes the UniformDistribution plugin.
        """
        pass

    @hookimpl
    def get_interarrival_times_factory(
        self, config: dict, stop_time: float | None = None
    ) -> Callable:
        """
        Returns a factory function that creates an iterator yielding uniform inter-arrival times.

        Args:
            config: Plugin configuration with distribution parameters
            stop_time: Maximum time for request injection. If provided, may limit
                      the number of requests injected.
        """
        num_reqs = config["num_reqs"]
        time_slot_size = config["time_slot_size"]
        interval = time_slot_size / num_reqs

        def factory(env) -> Iterator[tuple[int, float]]:
            """Factory that creates the iterator with captured config."""
            # stop_time is absolute, time_slot_size is relative to env.now
            if stop_time is not None:
                adjusted_end_time = stop_time  # Absolute time
            else:
                adjusted_end_time = time_slot_size + env.now  # Relative time

            counter = 0
            while counter < num_reqs and env.now < adjusted_end_time:
                yield 1, interval
                counter += 1

        return factory
