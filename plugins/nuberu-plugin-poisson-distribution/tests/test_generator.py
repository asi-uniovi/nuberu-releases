import pytest
from nuberu_plugin_poisson_distribution.plugin import PoissonDistribution

import random


# --- Mock of the Simulation Environment ---
class MockSimEnvironment:
    def __init__(self, start_time=0):
        self._current_time = start_time

    @property
    def now(self):
        return self._current_time

    def advance_time(self, amount: float):
        self._current_time += amount


# --- Fixtures for Tests ---
@pytest.fixture
def mock_env():
    """Provides a mock simulation environment."""
    return MockSimEnvironment()


@pytest.fixture
def seeded_random():
    """Fixes the random seed for reproducibility."""
    random.seed(42)


def loop_injector(env, interarrival_times_iterator):
    """
    Emulates the loop that injects requests into the simulation environment.
    """
    requests = 0
    interarrival_times = []
    for reqs, next_time in interarrival_times_iterator:
        env.advance_time(next_time)
        interarrival_times.append(next_time)
        requests += reqs
    return interarrival_times, requests


# --- Tests for the PoissonDistribution Plugin ---
def test_generates_correct_number_of_requests(mock_env, seeded_random):
    """
    Verifies that the generator produces `num_reqs` request
    when no end time is specified.
    """

    # 1. Setup plugin
    plugin = PoissonDistribution()
    config = {"mode": "by_rate_and_num_reqs", "rate": 10, "num_reqs": 50}

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 3. Assertions
    # Correct number of requests generated
    assert requests == config["num_reqs"]
    assert mock_env.now == pytest.approx(sum(generated_times))

    # Average inter-arrival time should be close to 1/rate
    # (in this case, the tolerance is 0.03 for a rate of 10 and 50 requests)
    # since that value is 2 standard deviations away from the mean
    expected_avg_time = 1 / config["rate"]
    actual_avg_time = sum(generated_times) / requests
    stddef = expected_avg_time / (
        requests**0.5
    )  # Standard deviation for Poisson distribution
    assert actual_avg_time == pytest.approx(expected_avg_time, abs=2 * stddef)


def test_generates_until_correct_time(mock_env, seeded_random):
    """
    Verifies that the generator produces requests until the specified end time.
    """
    # 1. Setup plugin
    plugin = PoissonDistribution()
    config = {
        "mode": "by_rate_and_time",
        "rate": 5,  # 5 requests per second
        "total_time": 10,  # Total time of 10 seconds
    }

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, _ = loop_injector(mock_env, interarrival_times_iterator)

    # Remove the last time if it exceeds the total time
    if mock_env.now > config["total_time"]:
        generated_times.pop()

    # 4. Assertions
    total_generated_time = sum(generated_times)
    assert total_generated_time <= config["total_time"]

    num_requests = len(generated_times)
    expected_num_requests = config["rate"] * config["total_time"]
    stddev = expected_num_requests**0.5  # Standard deviation for Poisson distribution
    assert num_requests == pytest.approx(
        expected_num_requests, abs=2 * stddev
    )  # Allow 2 requests tolerance


def test_for_num_reqs_and_time(mock_env, seeded_random):
    """
    Verifies that the generator produces requests based on both num_reqs and total_time.
    """
    # 1. Setup plugin
    plugin = PoissonDistribution()
    config = {
        "mode": "by_num_reqs_and_time",
        "num_reqs": 1000,
        "time_slot_size": 60,  # 60 seconds
    }

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    total_generated_time = sum(generated_times)
    assert (
        total_generated_time <= config["time_slot_size"]
        or requests <= config["num_reqs"]
    )

    # Average inter-arrival time should be close to time_slot_size / num_reqs
    expected_avg_time = config["time_slot_size"] / config["num_reqs"]
    actual_avg_time = sum(generated_times) / requests
    stddev = expected_avg_time / (
        config["num_reqs"] ** 0.5
    )  # Standard deviation for Poisson distribution
    assert actual_avg_time == pytest.approx(
        expected_avg_time, abs=2 * stddev
    )  # Allow 2 standard deviations tolerance

    # Number of generated requests should be close to num_reqs
    stddev = config["num_reqs"] ** 0.5  # Standard deviation for Poisson distribution
    assert requests == pytest.approx(config["num_reqs"], abs=2 * stddev)

    # If not enough requests were generated, check that the last one exceeded the end time
    if requests < config["num_reqs"]:
        assert mock_env.now > config["time_slot_size"]
        assert mock_env.now - generated_times[-1] <= config["time_slot_size"]
    else:
        assert mock_env.now <= config["time_slot_size"]


def test_for_rate_only(mock_env, seeded_random):
    """
    Verifies that the generator produces requests based on the rate only.
    """
    # 1. Setup plugin
    plugin = PoissonDistribution()
    config = {
        "mode": "by_rate",
        "rate": 10,  # 10 requests per second
    }

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times = []
    requests = 0
    # Now there is an infinite loop, so we have to exit it manually
    reqs_to_generate = 1000  # Limit the number of requests to generate
    for i, (req, next_time) in enumerate(interarrival_times_iterator):
        if i == reqs_to_generate:  # Limit to 1000 iterations to avoid infinite loop
            break
        generated_times.append(next_time)
        mock_env.advance_time(next_time)
        requests += req

    # 4. Assertions
    assert requests == reqs_to_generate

    expected_num_requests = config["rate"] * mock_env.now
    stddev = expected_num_requests**0.5
    assert requests == pytest.approx(expected_num_requests, abs=2 * stddev)

    # Average inter-arrival time should be close to 1/rate
    expected_avg_time = 1 / config["rate"]
    actual_avg_time = sum(generated_times) / requests
    stddev = (
        expected_avg_time / expected_num_requests**0.5
    )  # Standard deviation for Poisson distribution
    assert actual_avg_time == pytest.approx(
        expected_avg_time, abs=2 * stddev
    )  # Allow 2 standard deviations tolerance
