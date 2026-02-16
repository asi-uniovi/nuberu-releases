import io
import pytest
from nuberu_plugin_poisson_dynamic_distribution.plugin import TraceBasedDistribution

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


@pytest.fixture(scope="function")
def fake_csv(monkeypatch):
    """
    Fixture to mock the open function for reading CSV files.
    This allows us to simulate reading from a CSV file without needing an actual file.
    """

    def _setup(csv_text: str, *, expect_path="/tmp/foo.csv"):
        def _fake(path, *a, **kw):
            assert path == expect_path
            return io.StringIO(csv_text)

        monkeypatch.setattr("builtins.open", _fake)

    return _setup


def loop_injector(env, interarrival_times_iterator, max_iter=1000):
    """
    Emulates the loop that injects requests into the simulation environment.
    """
    requests = 0
    interarrival_times = []
    loop_count = 0
    for reqs, next_time in interarrival_times_iterator:
        if loop_count >= max_iter:
            break
        loop_count += 1
        env.advance_time(next_time)
        interarrival_times.append(next_time)
        requests += reqs
    return interarrival_times, requests


# --- Tests for the TraceBasedDistribution Plugin ---


def test_generator_uniform_stops_when_csv_ends(mock_env, seeded_random, fake_csv):
    """
    Verifies that the generator stops at the end of the CSV file.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv("1\n1\n1\n1\n1\n")  # 5 lines of 1 request per second

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    # Correct number of requests generated
    assert len(generated_times) == 5  # Based on the mock CSV

    assert generated_times == [1.0, 1.0, 1.0, 1.0, 1.0]  # Each request takes 1 second


def test_generator_uniform_stops_at_injecting_end_time(
    mock_env, seeded_random, fake_csv
):
    """
    Verifies that the generator stops at the specified injecting end time.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "injecting_end_time": 3,  # Stop after 3 seconds
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv("1\n1\n1\n1\n1\n")  # 5 lines of 1 request per second

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    # Correct number of requests generated
    assert requests == 3  # Based on the mock CSV

    assert generated_times == [1.0, 1.0, 1.0]  # Each request takes 1 second


def test_generator_uniform_starts_at_specified_csv_offset(
    mock_env, seeded_random, fake_csv
):
    """
    Verifies that the generator starts reading from the specified CSV offset.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "csv_offset": 2,  # Start reading from the third line
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv("2\n2\n1\n1\n1\n")  # 5 lines of 1 request per second

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    # Correct number of requests generated
    assert requests == 3  # Based on the mock CSV starting from offset 2

    assert generated_times == [1.0, 1.0, 1.0]


def test_generator_uniform_offset_after_end_of_file(mock_env, seeded_random, fake_csv):
    """
    Verifies that the generator starts reading from the specified CSV offset.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "csv_offset": 10,  # Start reading from the third line
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv("2\n2\n1\n1\n1\n")  # 5 lines of 1 request per second

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(
        mock_env, interarrival_times_iterator, max_iter=5
    )

    # 4. Assertions
    # Correct number of requests generated
    assert requests == 0  # Based on the mock CSV starting from offset 2
    assert generated_times == []


@pytest.mark.parametrize(
    "csv_data, expected_requests",
    [
        ("2\n4\n1\n", 7),  # 3 lines of requests
        ("3\n3\n3\n", 9),  # 3 lines of requests
        ("100\n", 100),  # 4 lines of requests
    ],
)
def test_generator_uniform_generates_correct_requests(
    mock_env, seeded_random, fake_csv, csv_data, expected_requests
):
    """
    Verifies that the generator produces the correct number of requests based on the CSV file.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv(csv_data)

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect requests
    _, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    assert requests == expected_requests  # Based on the mock CSV


def test_generator_uniform_with_empty_csv(mock_env, seeded_random, fake_csv):
    """
    Verifies that the generator handles a CSV file with zero requests correctly.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with no content
    fake_csv("")

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times = list(interarrival_times_iterator)

    # 4. Assertions
    assert len(generated_times) == 0


# @pytest.mark.xfail(
#     reason="Expected to fail. CSVs with 0 rps are not dealt properly yet", strict=True
# )
def test_generator_uniform_with_zero_requests_intervals(
    mock_env, seeded_random, fake_csv
):
    """
    Verifies that the generator handles a CSV file with zero requests correctly.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with zero requests
    # Three zeros, 1, two zeros, 1, so ony two requests
    fake_csv("0\n0\n0\n1\n0\n0\n1\n")

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    assert requests == 2
    # Check that the generator "skips" regions of zero requests
    assert generated_times == [3.0, 1.0, 2.0, 1.0]


def test_generator_poisson(mock_env, seeded_random, fake_csv):
    """
    Verifies that the generator produces interarrival times based on a Poisson distribution.
    """

    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "poisson",
    }

    # Mock the open function to return a StringIO object with CSV content
    fake_csv("100\n50\n")

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    # The number of generated times should be greater than 0, but we cannot predict the exact number
    assert requests > 0

    # Separate requests into 1s intervals
    first_second = []
    second_second = []
    clock = 0
    for t in generated_times:
        if 0 <= clock < 1:
            first_second.append(t)
        elif 1 <= clock < 2:
            second_second.append(t)
        else:
            # If the time is beyond the first two seconds, we can stop
            break
        clock += t

    # Check that the first second has more requests than the second
    assert len(first_second) > len(second_second), (
        "First second should have more requests than the second second"
    )

    def test_coef_var(data):
        # Tests if the data has a deviation compatible with a Poisson distribution
        import statistics

        μ = statistics.mean(data)
        σ = statistics.stdev(data)  # ddof = 1
        cv = σ / μ  # para exponencial debe ≈ 1
        assert cv == pytest.approx(1.0, rel=0.2)

    # Check that the number of request is close to the expected rate for each second
    for data, expected_requests in [(first_second, 100), (second_second, 50)]:
        stddev = expected_requests**0.5
        actual_requests = len(data)
        assert actual_requests == pytest.approx(expected_requests, abs=2 * stddev)

    # Check that the average interarrival time is close to the expected rate
    for data, expected_rate in [(first_second, 100), (second_second, 50)]:
        avg_interarrival_time = sum(data) / len(data)
        expected_interarrival_time = 1.0 / expected_rate
        stddev = expected_interarrival_time * (1.0 / expected_rate) ** 0.5
        assert avg_interarrival_time == pytest.approx(
            expected_interarrival_time, abs=2 * stddev
        )

    # Check that the stddev in each second is close to the expected stddev for Poisson distribution
    # (this would fail if the injector used "uniform" instead of "poisson")
    for data, expected_rate in [(first_second, 100), (second_second, 50)]:
        test_coef_var(data)


def test_generator_uniform_complex_csv(mock_env, seeded_random, fake_csv):
    """
    Verifies that the generator handles a complex CSV file which
    contains in each line the time in which the rate must be sustained
    """
    # 1. Setup plugin
    plugin = TraceBasedDistribution()
    config = {
        "mode": "rps_from_file",
        "rate_file_path": "/tmp/foo.csv",
        "inter_arrivals": "uniform",
    }

    # Mock the open function to return a StringIO object with complex CSV content
    fake_csv("5,1\n3,0\n1,1\n")
    # This CSV means:
    # - 5 seconds using 1 rps
    # - 3 seconds generating 0 requests
    # - 1 second using 1 rps

    # So this should produce 5 request in the first 5 and 1 request in the last second

    # 2. Run the generator
    factory = plugin.get_interarrival_times_factory(config=config)
    interarrival_times_iterator = factory(mock_env)

    # 3. Collect generated times
    generated_times, requests = loop_injector(mock_env, interarrival_times_iterator)

    # 4. Assertions
    assert requests == 6

    # Check that the generator "skips" regions of zero requests
    # The inter-arrival times should be 1 for the first 5 seconds, then 3 secs
    # of waiting, and finally one request with 1.0s of inter-arrival time for the next one
    # (which is never injected because the "simulation" ends)
    assert generated_times == [1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 1.0]
