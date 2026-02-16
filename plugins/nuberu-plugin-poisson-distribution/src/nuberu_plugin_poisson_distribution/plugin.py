import random

from nuberu.plugins.hookspecs import ArrivalDistributionSpecs
from typing import Callable, Iterator
from .config import ConfigValidator

import pluggy

hookimpl = pluggy.HookimplMarker("nuberu")


class PoissonDistribution(ArrivalDistributionSpecs):
    def __init__(self):
        """
        Initializes the PoissonDistribution plugin.
        """
        pass

    @staticmethod
    def _parse_config(config: dict) -> None:
        """
        Validates the configuration dictionary against the PoissonConfig model.
        Raises ValueError if validation fails.
        """
        if "mode" not in config:
            # Default mode is 'calculate_lambda' if not specified (backward compatibility)
            config["mode"] = "by_num_reqs_and_time"
        config = ConfigValidator.validate_python(config)

        # Compute parameters for the generator
        match config.mode:
            case "by_num_reqs_and_time":
                rate = config.num_reqs / config.time_slot_size
                end_time = config.time_slot_size
                num_reqs = config.num_reqs
            case "by_rate_and_num_reqs":
                rate = config.rate
                num_reqs = config.num_reqs
                end_time = float("inf")  # No end time specified
            case "by_rate_and_time":
                rate = config.rate
                end_time = config.total_time
                num_reqs = float("inf")  # No specific number of requests
            case "by_rate":
                rate = config.rate
                num_reqs = float("inf")  # No specific number of requests
                end_time = float("inf")
            case _:
                # This should never happen if the config is validated correctly
                raise ValueError(
                    f"Invalid mode: {config.mode}, undetected by pydantic."
                )
        return rate, num_reqs, end_time

    @hookimpl
    def get_interarrival_times_factory(
        self, config: dict, stop_time: float | None = None
    ) -> Callable:
        """
        Returns a factory function that creates a generator yielding requests and
        inter-arrival times drawn from an exponential distribution with rate (lambda_per_second).

        Args:
            config: Plugin configuration with distribution parameters
            stop_time: Maximum time for request injection. Takes precedence over
                      time_slot_size if provided.
        """
        rate, num_reqs, end_time = PoissonDistribution._parse_config(config)

        def factory(env) -> Iterator[tuple[int, float]]:
            """Factory that creates the generator with captured config."""
            # stop_time is absolute, end_time is relative to env.now
            if stop_time is not None:
                adjusted_end_time = stop_time  # Absolute time
            else:
                adjusted_end_time = end_time + env.now  # Relative time

            def generator() -> Iterator[tuple[int, float]]:
                """Yields number of requests to inject and time to next arrival."""
                counter = 0
                lam = rate
                while counter < num_reqs and env.now < adjusted_end_time:
                    # Yield 1 request and the time to the next arrival
                    yield 1, random.expovariate(lam)
                    counter += 1

            return generator()

        return factory
