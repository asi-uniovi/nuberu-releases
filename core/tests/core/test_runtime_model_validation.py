"""Tests for runtime model configuration validation."""

import pytest
import yaml

from nuberu.core.simulation_config import SimulationConfig


def test_runtime_model_missing_both(tmp_path):
    """Test that error is raised when neither runtime_model nor runtime_models is specified."""
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
  plugin_name: round_robin
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
"""

    with pytest.raises(ValueError, match="Runtime model configuration is missing"):
        config_dict = yaml.safe_load(yaml_content)
        SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})


def test_runtime_model_only_default(tmp_path):
    """Test that configuration with only runtime_model works."""
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
  plugin_name: round_robin
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

    # Should not raise
    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})
    assert cfg.runtime_model is not None
    assert cfg.runtime_model.plugin_name == "simple"


def test_runtime_model_only_per_app_complete(tmp_path):
    """Test that configuration with only runtime_models works when all apps are covered."""
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
  plugin_name: round_robin
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
    plugin_name: simple
    plugin_config:
      queue_size: 20
"""

    # Should not raise
    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})
    assert cfg.runtime_model is None
    assert "app1" in cfg.runtime_models
    assert "app2" in cfg.runtime_models


def test_runtime_model_only_per_app_incomplete(tmp_path):
    """Test that error is raised when runtime_models doesn't cover all apps."""
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
  - app: app3
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
load_balancer:
  plugin_name: round_robin
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
"""

    with pytest.raises(ValueError, match="app2.*app3"):
        config_dict = yaml.safe_load(yaml_content)
        SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})


def test_runtime_model_both_default_and_per_app(tmp_path):
    """Test that configuration with both runtime_model and runtime_models works."""
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
  plugin_name: round_robin
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
runtime_models:
  app1:
    plugin_name: advanced
    plugin_config:
      queue_size: 100
"""

    # Should not raise
    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})
    assert cfg.runtime_model is not None
    assert cfg.runtime_model.plugin_name == "simple"
    assert "app1" in cfg.runtime_models
    assert cfg.runtime_models["app1"].plugin_name == "advanced"


def test_runtime_model_partial_per_app_with_default_fallback(tmp_path):
    """Test that apps not in runtime_models use the default runtime_model as fallback."""
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
  - app: app3
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
  - app: app4
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100
        time_slot_size: 3600
load_balancer:
  plugin_name: round_robin
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
    plugin_name: custom_model_1
    plugin_config:
      queue_size: 100
  app2:
    plugin_name: custom_model_2
    plugin_config:
      queue_size: 200
"""

    # Should not raise - app3 and app4 will use runtime_model as fallback
    config_dict = yaml.safe_load(yaml_content)
    cfg = SimulationConfig.model_validate(config_dict, context={"base_dir": tmp_path})

    # Verify default is present
    assert cfg.runtime_model is not None
    assert cfg.runtime_model.plugin_name == "default_model"

    # Verify custom configs for app1 and app2
    assert "app1" in cfg.runtime_models
    assert cfg.runtime_models["app1"].plugin_name == "custom_model_1"
    assert "app2" in cfg.runtime_models
    assert cfg.runtime_models["app2"].plugin_name == "custom_model_2"

    # Verify app3 and app4 are NOT in runtime_models (they'll use default)
    assert "app3" not in cfg.runtime_models
    assert "app4" not in cfg.runtime_models
