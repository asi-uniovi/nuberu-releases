# Fichero: poisson_plugin/tests/test_config_validation.py

import pytest
from pydantic import ValidationError
from nuberu_plugin_poisson_distribution.plugin import PoissonDistribution

# --- Tests for valid cases


def test_valid_config_by_duration():
    """Test config in mode 'by_rate_and_time'."""
    config_data = {"mode": "by_rate_and_time", "rate": 10.0, "total_time": 60}
    rate, num_reqs, end_time = PoissonDistribution._parse_config(config_data)
    assert rate == 10.0
    assert end_time == 60
    assert num_reqs == float("inf")  # No specific number of requests


def test_valid_config_by_count():
    """Test config in mode 'by_rate_and_num_reqs'."""
    config_data = {"mode": "by_rate_and_num_reqs", "rate": 5.0, "num_reqs": 1000}
    rate, num_reqs, end_time = PoissonDistribution._parse_config(config_data)
    assert rate == 5.0
    assert num_reqs == 1000
    assert end_time == float("inf")


def test_valid_config_calculate_lambda():
    """Test config in mode 'by_num_reqs_and_time'."""
    config_data = {
        "mode": "by_num_reqs_and_time",
        "num_reqs": 1000,
        "time_slot_size": 60,
    }
    rate, num_reqs, end_time = PoissonDistribution._parse_config(config_data)
    assert rate == pytest.approx(1000 / 60)  # Lambda = num_reqs / time_slot_size
    assert end_time == 60
    assert num_reqs == 1000


def test_valid_config_with_default_mode():
    """Test config with default mode 'by_num_reqs_and_time'."""
    config_data = {"num_reqs": 1000, "time_slot_size": 60}
    rate, num_reqs, end_time = PoissonDistribution._parse_config(config_data)
    assert rate == pytest.approx(1000 / 60)


def test_valid_config_by_rate_only():
    """Test config in mode 'by_rate'."""
    config_data = {"mode": "by_rate", "rate": 10.0}
    rate, num_reqs, end_time = PoissonDistribution._parse_config(config_data)
    assert rate == 10.0
    assert num_reqs == float("inf")
    assert end_time == float("inf")  # No specific end time


# --- Tests for invalid cases


def test_invalid_config_missing_mode():
    """Test config without 'mode' key, but bad parameters for 'calculate_lambda' default"""
    config_data = {"rate": 10.0, "total_time": 60}
    with pytest.raises(ValidationError):
        PoissonDistribution._parse_config(config_data)


def test_invalid_config_bad_mode():
    """Test config with an unsupported mode."""
    config_data = {"mode": "unsupported_mode", "rate": 10.0, "total_time": 60}
    with pytest.raises(ValidationError):
        PoissonDistribution._parse_config(config_data)


def test_invalid_config_missing_required_fields():
    """Test config missing required fields for 'by_rate_and_num_reqs'."""
    config_data = {
        "mode": "by_rate_and_num_reqs",
        "rate": 5.0,
        # Missing 'num_reqs'
    }
    with pytest.raises(ValidationError):
        PoissonDistribution._parse_config(config_data)


def test_invalid_config_zero_rate():
    """Test config with zero rate, which is invalid."""
    config_data = {
        "mode": "by_rate_and_time",
        "rate": 0,  # Invalid rate
        "total_time": 60,
    }
    with pytest.raises(ValidationError):
        PoissonDistribution._parse_config(config_data)


def test_invalid_config_zero_values():
    config_data = {
        "mode": "by_num_reqs_and_time",
        "num_reqs": 1000,  # Invalid number of requests
        "time_slot_size": 0,
    }
    with pytest.raises(ValidationError):
        PoissonDistribution._parse_config(config_data)
