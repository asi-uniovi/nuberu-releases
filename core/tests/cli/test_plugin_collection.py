"""Tests for CLI plugin collection."""

import yaml

from nuberu.cli.main import _collect_required_plugins
from nuberu.core.simulation_config import SimulationConfig


def test_collect_required_plugins_includes_runtime_model(tmp_path):
    """Test that _collect_required_plugins includes runtime_model plugins."""

    # Create a minimal valid config with runtime_model
    yaml_content = """
config_version: "2.1"
simulation:
  seed: 42
workloads:
  - app: app1
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
load_balancer:
  plugin_name: simple
  plugin_config: {}
allocation:
  mode: yaml
  yaml_path: alloc.yaml
performance_data:
  mode: yaml
  yaml_path: perf.yaml
infrastructure:
  mode: yaml
  yaml_path: infra.yaml
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 0
"""

    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})

    # Collect plugins
    include = _collect_required_plugins(cfg)

    # Verify runtime_model is included
    assert "runtime_model" in include, "runtime_model should be in include dict"
    assert "simple" in include["runtime_model"], (
        "simple plugin should be in runtime_model list"
    )


def test_collect_required_plugins_includes_runtime_models_per_app(tmp_path):
    """Test that _collect_required_plugins includes per-app runtime_models."""

    yaml_content = """
config_version: "2.1"
simulation:
  seed: 42
workloads:
  - app: app1
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
  - app: app2
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
load_balancer:
  plugin_name: simple
  plugin_config: {}
allocation:
  mode: yaml
  yaml_path: alloc.yaml
performance_data:
  mode: yaml
  yaml_path: perf.yaml
infrastructure:
  mode: yaml
  yaml_path: infra.yaml
runtime_models:
  app1:
    plugin_name: simple
    plugin_config:
      queue_size: 10
  app2:
    plugin_name: advanced
    plugin_config:
      queue_size: 20
"""

    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})

    # Collect plugins
    include = _collect_required_plugins(cfg)

    # Verify runtime_model is included with both plugins
    assert "runtime_model" in include, "runtime_model should be in include dict"
    assert "simple" in include["runtime_model"], (
        "simple plugin should be in runtime_model list"
    )
    assert "advanced" in include["runtime_model"], (
        "advanced plugin should be in runtime_model list"
    )


def test_collect_required_plugins_with_default_and_override(tmp_path):
    """Test plugin collection with default runtime_model and per-app overrides."""

    yaml_content = """
config_version: "2.1"
simulation:
  seed: 42
workloads:
  - app: app1
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
  - app: app2
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
load_balancer:
  plugin_name: simple
  plugin_config: {}
allocation:
  mode: yaml
  yaml_path: alloc.yaml
performance_data:
  mode: yaml
  yaml_path: perf.yaml
infrastructure:
  mode: yaml
  yaml_path: infra.yaml
runtime_model:
  plugin_name: default_model
  plugin_config:
    queue_size: 0
runtime_models:
  app1:
    plugin_name: custom_model
    plugin_config:
      queue_size: 100
"""

    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})

    # Collect plugins
    include = _collect_required_plugins(cfg)

    # Verify both plugins are included
    assert "runtime_model" in include, "runtime_model should be in include dict"
    assert "default_model" in include["runtime_model"], (
        "default_model should be in list"
    )
    assert "custom_model" in include["runtime_model"], "custom_model should be in list"

    # Should have exactly 2 plugins
    assert len(include["runtime_model"]) == 2, "Should have 2 runtime_model plugins"
