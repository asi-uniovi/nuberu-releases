"""Integration tests for v3.1 configuration with network delays."""

from nuberu.core.simulation_config import SimulationConfig


class TestConfigV31Integration:
    """Test v3.1 configuration parsing and validation."""

    def test_v31_config_with_network_delays(self, tmp_path):
        """Test parsing v3.1 config with network_delays section."""
        config_dict = {
            "config_version": "3.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
                "eager_start": True,
                "drain_pending_requests": False,
                "allocator_interval": 250,
            },
            "network_delays": {
                "wi_to_lb": 10.0,
                "lb_to_vm_default": 5.0,
                "vm_container_overhead": 2.0,
            },
            "infrastructure": {
                "mode": "plugin",
                "plugin_name": "test_infra",
                "plugin_config": {},
            },
            "performance_data": {
                "mode": "plugin",
                "plugin_name": "test_perf",
                "plugin_config": {},
            },
            "allocation": {
                "mode": "plugin",
                "plugin_name": "test_alloc",
                "plugin_config": {},
            },
            "load_balancer": {
                "mode": "plugin",
                "plugin_name": "smoothWRR",
                "plugin_config": {},
            },
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
            "workloads": [
                {
                    "app": "app_0",
                    "distribution": {
                        "mode": "plugin",
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 100, "time_slot_size": 10},
                    },
                }
            ],
        }

        config = SimulationConfig.model_validate(
            config_dict, context={"base_dir": tmp_path}
        )

        assert config.config_version == "3.1"
        assert config.network_delays is not None
        assert config.network_delays.wi_to_lb == 10.0
        assert config.network_delays.lb_to_vm_default == 5.0
        assert config.network_delays.vm_container_overhead == 2.0

    def test_v31_config_without_network_delays(self, tmp_path):
        """Test that network_delays is optional (backward compatibility)."""
        config_dict = {
            "config_version": "3.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
                "eager_start": True,
                "drain_pending_requests": False,
                "allocator_interval": 250,
            },
            # No network_delays section
            "infrastructure": {
                "mode": "plugin",
                "plugin_name": "test_infra",
                "plugin_config": {},
            },
            "performance_data": {
                "mode": "plugin",
                "plugin_name": "test_perf",
                "plugin_config": {},
            },
            "allocation": {
                "mode": "plugin",
                "plugin_name": "test_alloc",
                "plugin_config": {},
            },
            "load_balancer": {
                "mode": "plugin",
                "plugin_name": "smoothWRR",
                "plugin_config": {},
            },
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
            "workloads": [
                {
                    "app": "app_0",
                    "distribution": {
                        "mode": "plugin",
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 100, "time_slot_size": 10},
                    },
                }
            ],
        }

        config = SimulationConfig.model_validate(
            config_dict, context={"base_dir": tmp_path}
        )

        assert config.config_version == "3.1"
        assert config.network_delays is None

    def test_v21_config_still_works(self, tmp_path):
        """Test that v2.1 configs still parse correctly (no network_delays)."""
        config_dict = {
            "config_version": "2.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
                "eager_start": True,
                "drain_pending_requests": False,
                "allocator_interval": 250,
            },
            "infrastructure": {
                "mode": "plugin",
                "plugin_name": "test_infra",
                "plugin_config": {},
            },
            "performance_data": {
                "mode": "plugin",
                "plugin_name": "test_perf",
                "plugin_config": {},
            },
            "allocation": {
                "mode": "plugin",
                "plugin_name": "test_alloc",
                "plugin_config": {},
            },
            "load_balancer": {
                "mode": "plugin",
                "plugin_name": "smoothWRR",
                "plugin_config": {},
            },
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
            "workloads": [
                {
                    "app": "app_0",
                    "distribution": {
                        "mode": "plugin",
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 100, "time_slot_size": 10},
                    },
                }
            ],
        }

        config = SimulationConfig.model_validate(
            config_dict, context={"base_dir": tmp_path}
        )

        assert config.config_version == "2.1"
        assert config.network_delays is None

    def test_v31_custom_network_delays(self, tmp_path):
        """Test v3.1 with custom network delay values."""
        config_dict = {
            "config_version": "3.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
                "eager_start": True,
                "drain_pending_requests": False,
                "allocator_interval": 250,
            },
            "network_delays": {
                "wi_to_lb": 50.0,
                "lb_to_vm_default": 25.0,
                "vm_container_overhead": 10.0,
            },
            "infrastructure": {
                "mode": "plugin",
                "plugin_name": "test_infra",
                "plugin_config": {},
            },
            "performance_data": {
                "mode": "plugin",
                "plugin_name": "test_perf",
                "plugin_config": {},
            },
            "allocation": {
                "mode": "plugin",
                "plugin_name": "test_alloc",
                "plugin_config": {},
            },
            "load_balancer": {
                "mode": "plugin",
                "plugin_name": "smoothWRR",
                "plugin_config": {},
            },
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
            "workloads": [
                {
                    "app": "app_0",
                    "distribution": {
                        "mode": "plugin",
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 100, "time_slot_size": 10},
                    },
                }
            ],
        }

        config = SimulationConfig.model_validate(
            config_dict, context={"base_dir": tmp_path}
        )

        assert config.network_delays.wi_to_lb == 50.0
        assert config.network_delays.lb_to_vm_default == 25.0
        assert config.network_delays.vm_container_overhead == 10.0

    def test_v31_zero_network_delays(self, tmp_path):
        """Test v3.1 with zero delays (for fast testing)."""
        config_dict = {
            "config_version": "3.1",
            "simulation": {
                "seed": 12345,
                "stop_time": 100,
                "eager_start": True,
                "drain_pending_requests": False,
                "allocator_interval": 250,
            },
            "network_delays": {
                "wi_to_lb": 0.0,
                "lb_to_vm_default": 0.0,
                "vm_container_overhead": 0.0,
            },
            "infrastructure": {
                "mode": "plugin",
                "plugin_name": "test_infra",
                "plugin_config": {},
            },
            "performance_data": {
                "mode": "plugin",
                "plugin_name": "test_perf",
                "plugin_config": {},
            },
            "allocation": {
                "mode": "plugin",
                "plugin_name": "test_alloc",
                "plugin_config": {},
            },
            "load_balancer": {
                "mode": "plugin",
                "plugin_name": "smoothWRR",
                "plugin_config": {},
            },
            "runtime_model": {
                "plugin_name": "simple",
                "plugin_config": {"queue_size": 0},
            },
            "workloads": [
                {
                    "app": "app_0",
                    "distribution": {
                        "mode": "plugin",
                        "plugin_name": "poisson",
                        "plugin_config": {"num_reqs": 100, "time_slot_size": 10},
                    },
                }
            ],
        }

        config = SimulationConfig.model_validate(
            config_dict, context={"base_dir": tmp_path}
        )

        assert config.network_delays.wi_to_lb == 0.0
        assert config.network_delays.lb_to_vm_default == 0.0
        assert config.network_delays.vm_container_overhead == 0.0
