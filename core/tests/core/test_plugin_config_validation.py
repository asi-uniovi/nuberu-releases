"""
Tests for plugin_config validation in configuration models.

This test suite ensures that the plugin_config key is mandatory in plugin-based
configurations, preventing silent bugs when users accidentally put plugin parameters
at the wrong level in the YAML configuration.
"""

import pytest
from pydantic import ValidationError

from nuberu.core.simulation_config import (
    PluginBasedConfig,
    RuntimeModelConfig,
)


class TestPluginBasedConfigValidation:
    """Test validation of plugin_config in PluginBasedConfig."""

    def test_valid_config_with_empty_plugin_config(self):
        """plugin_config can be an empty dict if no configuration is needed."""
        config = PluginBasedConfig(plugin_name="test_plugin", plugin_config={})
        assert config.plugin_name == "test_plugin"
        assert config.plugin_config == {}

    def test_valid_config_with_parameters(self):
        """plugin_config can contain parameters."""
        config = PluginBasedConfig(
            plugin_name="test_plugin", plugin_config={"param1": "value1", "param2": 42}
        )
        assert config.plugin_name == "test_plugin"
        assert config.plugin_config == {"param1": "value1", "param2": 42}

    def test_missing_plugin_config_raises_error(self):
        """Missing plugin_config key should raise a clear error."""
        with pytest.raises(ValueError, match=r"Missing required 'plugin_config' key"):
            PluginBasedConfig(plugin_name="test_plugin")

    def test_extra_keys_outside_plugin_config_raises_error(self):
        """Extra keys that should be in plugin_config raise a helpful error."""
        with pytest.raises(
            ValueError,
            match=r"Missing 'plugin_config' key.*Found unexpected keys.*param1.*param2",
        ):
            PluginBasedConfig(plugin_name="test_plugin", param1="value1", param2=42)

    def test_extra_keys_after_plugin_config_forbidden(self):
        """Extra keys are forbidden even when plugin_config is present."""
        with pytest.raises(ValidationError, match=r"Extra inputs are not permitted"):
            PluginBasedConfig(
                plugin_name="test_plugin",
                plugin_config={"param1": "value1"},
                extra_key="should_fail",
            )


class TestRuntimeModelConfigValidation:
    """Test validation of plugin_config in RuntimeModelConfig."""

    def test_valid_runtime_model_with_empty_config(self):
        """RuntimeModelConfig with empty plugin_config is valid."""
        config = RuntimeModelConfig(plugin_name="simple", plugin_config={})
        assert config.plugin_name == "simple"
        assert config.plugin_config == {}

    def test_valid_runtime_model_with_queue_size(self):
        """RuntimeModelConfig with queue_size in plugin_config is valid."""
        config = RuntimeModelConfig(
            plugin_name="simple", plugin_config={"queue_size": 1000}
        )
        assert config.plugin_name == "simple"
        assert config.plugin_config == {"queue_size": 1000}

    def test_missing_plugin_config_in_runtime_model_raises_error(self):
        """Missing plugin_config in runtime_model should raise error."""
        with pytest.raises(
            ValueError, match=r"Missing required 'plugin_config' key in runtime_model"
        ):
            RuntimeModelConfig(plugin_name="simple")

    def test_queue_size_outside_plugin_config_raises_error(self):
        """
        This is the bug from issue #4: queue_size directly in runtime_model
        instead of inside plugin_config should raise a clear error.
        """
        with pytest.raises(
            ValueError,
            match=r"Missing 'plugin_config' key in runtime_model.*Found unexpected keys.*queue_size",
        ):
            RuntimeModelConfig(plugin_name="simple", queue_size=0)

    def test_extra_keys_forbidden_in_runtime_model(self):
        """Extra keys are forbidden in RuntimeModelConfig."""
        with pytest.raises(ValidationError, match=r"Extra inputs are not permitted"):
            RuntimeModelConfig(
                plugin_name="simple",
                plugin_config={"queue_size": 1000},
                extra_key="should_fail",
            )


class TestSimulationConfigWithRuntimeModel:
    """Integration tests with full SimulationConfig."""

    def test_runtime_model_without_plugin_config_in_yaml_dict(self):
        """
        Simulates the bug scenario: runtime_model without plugin_config key.
        This should fail during SimulationConfig validation.
        """
        from pathlib import Path

        from nuberu.core.simulation_config import SimulationConfig

        config_data = {
            "config_version": "2.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
            },
            "infrastructure": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "performance_data": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "allocation": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "load_balancer": {"plugin_name": "simple", "plugin_config": {}},
            "workloads": [
                {
                    "app": "app0",
                    "distribution": {
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 1000, "time_slot_size": 3600},
                    },
                }
            ],
            "cost_models": [
                {"plugin_name": "spot", "plugin_config": {"price_per_hour": 0.05}}
            ],
            # This is the problematic configuration from the bug report
            "runtime_model": {
                "plugin_name": "simple",
                "queue_size": 0,  # Should be inside plugin_config!
            },
        }

        with pytest.raises(
            ValueError,
            match=r"Missing 'plugin_config' key in runtime_model.*Found unexpected keys.*queue_size",
        ):
            SimulationConfig.model_validate(
                config_data, context={"base_dir": Path(".")}
            )

    def test_runtime_model_with_correct_plugin_config_succeeds(self):
        """
        The correct way: runtime_model with plugin_config key.
        """
        from pathlib import Path

        from nuberu.core.simulation_config import SimulationConfig

        config_data = {
            "config_version": "2.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
            },
            "infrastructure": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "performance_data": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "allocation": {
                "mode": "yaml",
                "yaml_path": Path("./test.yaml"),
            },
            "load_balancer": {"plugin_name": "simple", "plugin_config": {}},
            "workloads": [
                {
                    "app": "app0",
                    "distribution": {
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 1000, "time_slot_size": 3600},
                    },
                }
            ],
            "cost_models": [
                {"plugin_name": "spot", "plugin_config": {"price_per_hour": 0.05}}
            ],
            # Correct configuration
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
        }

        config = SimulationConfig.model_validate(
            config_data, context={"base_dir": Path(".")}
        )
        assert config.runtime_model.plugin_name == "simple"
        assert config.runtime_model.plugin_config["queue_size"] == 0
