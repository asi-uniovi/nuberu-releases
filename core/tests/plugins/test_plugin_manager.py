from unittest.mock import MagicMock

import pytest

from nuberu import PluginManager


@pytest.fixture
def plugin_manager():
    """Create a PluginManager instance for testing."""
    return PluginManager()


def test_plugin_manager_initialization(plugin_manager):
    """Test that hookspecs are registered during initialization."""
    assert "get_allocations_factory" in plugin_manager.pm.hook.__dict__
    assert "get_distribution_params_for_app_factory" in plugin_manager.pm.hook.__dict__
    assert "get_load_balancer_factory" in plugin_manager.pm.hook.__dict__
    assert "get_cost_model_factory" in plugin_manager.pm.hook.__dict__
    assert "get_interarrival_times_factory" in plugin_manager.pm.hook.__dict__


def test_register_plugin(plugin_manager):
    """Test registering a plugin manually."""
    plugin = MagicMock()
    plugin_manager.register(plugin)

    assert plugin in plugin_manager.pm.get_plugins()


def test_get_plugin_existing(plugin_manager):
    """Test retrieving an existing plugin by type and name."""
    plugin = MagicMock()
    plugin.__class__.__name__ = "TestPlugin"
    plugin_manager._by_type["comp"] = {plugin.__class__.__name__: plugin}

    retrieved = plugin_manager.get_plugin("comp", "TestPlugin")
    assert retrieved is plugin


def test_get_plugin_nonexistent(plugin_manager):
    """Test retrieving a plugin that does not exist."""
    with pytest.raises(ValueError):
        plugin_manager.get_plugin("comp", "nonexistent")


def test_list_registered_plugins(plugin_manager):
    """Test listing registered plugins from type mapping."""
    plugin1 = MagicMock()
    plugin2 = MagicMock()
    plugin_manager._by_type = {
        "typeA": {"nameA": plugin1},
        "typeB": {"nameB": plugin2},
    }

    plugins = plugin_manager.list_registered_plugins()
    assert plugins == {"typeA": ["nameA"], "typeB": ["nameB"]}


def test_get_plugin_validates_protocol(plugin_manager):
    """Test that get_plugin validates that the plugin implements the required Protocol."""

    # Create a plugin that DOES implement RuntimeModelSpecs
    class ValidRuntimeModel:
        def get_runtime_model_factory(self, config):
            return (
                lambda env,
                container,
                performance,
                event_bus,
                duplex_channel,
                idle_sink,
                progress_sink: None
            )

    valid_plugin = ValidRuntimeModel()
    plugin_manager._by_type["runtime_model"] = {"valid": valid_plugin}

    # Should not raise any exception
    retrieved = plugin_manager.get_plugin("runtime_model", "valid")
    assert retrieved is valid_plugin

    # Create a plugin that does NOT implement RuntimeModelSpecs
    class InvalidPlugin:
        def some_other_method(self):
            pass

    invalid_plugin = InvalidPlugin()
    plugin_manager._by_type["runtime_model"]["invalid"] = invalid_plugin

    # Should raise TypeError because it doesn't implement the Protocol
    with pytest.raises(TypeError, match="does not implement the required interface"):
        plugin_manager.get_plugin("runtime_model", "invalid")
