import random
from nuberu.plugins.hookspecs import ArrivalDistributionSpecs
from nuberu.plugins import PluginBase
from typing import Callable, Iterator
from .config import ConfigValidator
import itertools

import pluggy

hookimpl = pluggy.HookimplMarker("nuberu")


class TraceBasedDistribution(ArrivalDistributionSpecs, PluginBase):
    plugin_name = "poisson_dynamic_distribution"

    def __init__(self):
        """
        Initializes the TraceBasedDistribution plugin.
        """
        PluginBase.__init__(self)

    @staticmethod
    def _parse_config(config: dict) -> dict:
        """
        Validates the configuration dictionary against the TraceConfig model.
        """
        if "mode" not in config:
            # Default mode is 'rps_from_file' if not specified
            # for backward compatibility
            config["mode"] = "rps_from_file"
        config = ConfigValidator.validate_python(config)
        return config.model_dump()

    @staticmethod
    def rate_iterator(
        csv_path: str, csv_offset: int = 0
    ) -> Iterator[tuple[float, int]]:
        """
        Generator that yields (rate, next_time) pairs from a CSV file.
        """
        with open(csv_path, newline=None) as f:

            def parse_lines():
                for line in itertools.islice(f, csv_offset, None):
                    parts = line.strip().split(",")
                    if len(parts) == 2:
                        yield (int(parts[0]), float(parts[1]))
                    elif len(parts) == 1:
                        yield (1, float(parts[0]))

            next_time = 0
            # Use 'groupby' to "compress" lines with the same value.
            for value, group in itertools.groupby(
                parse_lines(), key=lambda item: item[1]
            ):
                next_time += sum(item[0] for item in group)
                yield (value, next_time)
        yield 0, float("inf")  # Indicate no more rates available

    @hookimpl
    def get_interarrival_times_factory(
        self, config: dict, stop_time: float | None = None
    ) -> Callable:
        """
        Returns a factory function that creates a generator yielding requests and
        inter-arrival times based on a trace file.

        Args:
            config: Plugin configuration with distribution parameters
            stop_time: Maximum time for request injection. Takes precedence over
                      injecting_end_time if provided.
        """
        cfg = TraceBasedDistribution._parse_config(config)
        csvfile = cfg.get("rate_file_path")
        csv_offset = cfg.get("csv_offset", 0)
        injecting_end_time = cfg["injecting_end_time"]
        dist = cfg["inter_arrivals"]

        self.logger.info(f"Using rate file {csvfile} for interarrival times.")

        distributions = {
            "uniform": lambda lam: 1.0 / lam,  # Uniform distribution
            "poisson": lambda lam: random.expovariate(lam),  # Poisson distribution
        }

        def factory(env) -> Iterator[tuple[int, float]]:
            """Factory that creates the generator with captured config."""
            started_at = int(env.now)
            rate_from_file = self.rate_iterator(csvfile, csv_offset)
            # stop_time is absolute, injecting_end_time is already absolute
            effective_end_time = (
                stop_time if stop_time is not None else injecting_end_time
            )

            def generator() -> Iterator[tuple[int, float]]:
                next_time = 0
                while True:
                    if env.now >= effective_end_time:
                        self.logger.info(
                            "Reached the configured end of workload for app. Stopping injection."
                        )
                        break
                    pos = env.now - started_at
                    if pos >= next_time:
                        lam, next_time = next(rate_from_file)
                    if next_time == float("inf"):  # No more requests to inject
                        break
                    if lam == 0:  # No requests to inject, wait next_time - pos seconds
                        yield 0, next_time - pos
                    else:
                        interval = distributions[dist](lam)
                        yield 1, interval

            return generator()

        return factory
