import re
import pytest
from pydantic import ValidationError
from nuberu_plugin_poisson_dynamic_distribution.plugin import TraceBasedDistribution

# --- Tests for valid cases


def test_valid_config_with_all_params():
    """Test config with a valid rate file."""
    config_data = {
        "mode": "rps_from_file",
        "rate_file_path": "path/to/rate_file.csv",
        "injecting_end_time": 100,
        "csv_offset": 5,
        "inter_arrivals": "poisson",
    }
    parsed = TraceBasedDistribution._parse_config(config_data)
    assert parsed["rate_file_path"] == "path/to/rate_file.csv"
    assert parsed["injecting_end_time"] == 100
    assert parsed["inter_arrivals"] == "poisson"
    assert parsed["csv_offset"] == 5


def test_valid_config_with_defaults():
    """Test config with default inter-arrivals type."""
    config_data = {
        "rate_file_path": "path/to/rate_file.csv",
    }
    parsed = TraceBasedDistribution._parse_config(config_data)
    assert parsed["mode"] == "rps_from_file"  # Default mode
    assert parsed["inter_arrivals"] == "uniform"  # Default value
    assert parsed["csv_offset"] == 0  # Default value
    assert parsed["injecting_end_time"] == float("inf")  # Default value
    assert parsed["rate_file_path"] == "path/to/rate_file.csv"


# --- Tests for invalid cases


def test_invalid_config_missing_file():
    """Test config without file."""
    config_data = {
        "injecting_end_time": 100,
    }
    expected_error = re.compile(
        r"1 validation error .*?rate_file_path\s+Field required", re.DOTALL
    )

    with pytest.raises(ValidationError, match=expected_error):
        TraceBasedDistribution._parse_config(config_data)


def test_invalid_config_no_params():
    """Test config without file."""
    config_data = {}
    expected_error = re.compile(
        r"1 validation error .*?rate_file_path\s+Field required", re.DOTALL
    )

    with pytest.raises(ValidationError, match=expected_error):
        TraceBasedDistribution._parse_config(config_data)
