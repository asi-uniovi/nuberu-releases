"""Tests for network delay configuration (RFC 001)."""

import pytest
from pydantic import ValidationError

from nuberu.core.network_delays import (
    NetworkDelays,
    VMNetworkConfig,
    WorkloadNetworkConfig,
)


class TestNetworkDelays:
    """Test NetworkDelays configuration."""

    def test_default_values(self):
        """Test that defaults are set correctly."""
        delays = NetworkDelays()

        assert delays.wi_to_lb == 10.0
        assert delays.lb_to_vm_default == 5.0
        assert delays.vm_container_overhead == 2.0

    def test_custom_values(self):
        """Test creating NetworkDelays with custom values."""
        delays = NetworkDelays(
            wi_to_lb=15.0,
            lb_to_vm_default=8.0,
            vm_container_overhead=3.0,
        )

        assert delays.wi_to_lb == 15.0
        assert delays.lb_to_vm_default == 8.0
        assert delays.vm_container_overhead == 3.0

    def test_zero_delays_allowed(self):
        """Test that zero delays are valid (for testing)."""
        delays = NetworkDelays(
            wi_to_lb=0.0,
            lb_to_vm_default=0.0,
            vm_container_overhead=0.0,
        )

        assert delays.wi_to_lb == 0.0
        assert delays.lb_to_vm_default == 0.0
        assert delays.vm_container_overhead == 0.0

    def test_negative_wi_to_lb_rejected(self):
        """Test that negative wi_to_lb is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            NetworkDelays(wi_to_lb=-5.0)

        assert "wi_to_lb" in str(exc_info.value)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_negative_lb_to_vm_rejected(self):
        """Test that negative lb_to_vm_default is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            NetworkDelays(lb_to_vm_default=-2.0)

        assert "lb_to_vm_default" in str(exc_info.value)

    def test_negative_vm_container_overhead_rejected(self):
        """Test that negative vm_container_overhead is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            NetworkDelays(vm_container_overhead=-1.0)

        assert "vm_container_overhead" in str(exc_info.value)

    def test_partial_overrides(self):
        """Test that partial overrides work with defaults."""
        delays = NetworkDelays(wi_to_lb=20.0, lb_to_vm_default=12.0)

        assert delays.wi_to_lb == 20.0
        assert delays.lb_to_vm_default == 12.0
        assert delays.vm_container_overhead == 2.0  # default

    def test_realistic_cloud_latencies(self):
        """Test realistic cloud network latencies and overheads."""
        # Typical intra-AZ latencies and virtualization overheads
        delays = NetworkDelays(
            wi_to_lb=10.0,  # 10ms network to load balancer
            lb_to_vm_default=5.0,  # 5ms network to VM (same AZ)
            vm_container_overhead=2.0,  # 2ms container startup
        )

        assert delays.wi_to_lb == 10.0
        assert delays.lb_to_vm_default == 5.0

    def test_large_delays(self):
        """Test that large delays (inter-region) are accepted."""
        delays = NetworkDelays(
            wi_to_lb=150.0,  # Cross-region: 150ms
            lb_to_vm_default=100.0,  # Cross-AZ: 100ms
        )

        assert delays.wi_to_lb == 150.0
        assert delays.lb_to_vm_default == 100.0


class TestVMNetworkConfig:
    """Test VM-specific network configuration."""

    def test_vm_basic_creation(self):
        """Test basic VM network config creation."""
        vm = VMNetworkConfig(name="vm_1", network_delay=50.0)

        assert vm.name == "vm_1"
        assert vm.network_delay == 50.0

    def test_vm_no_override(self):
        """Test VM config without delay override."""
        vm = VMNetworkConfig(name="vm_default")

        assert vm.name == "vm_default"
        assert vm.network_delay is None

    def test_vm_explicit_none(self):
        """Test explicit None for network_delay."""
        vm = VMNetworkConfig(name="vm_2", network_delay=None)

        assert vm.network_delay is None

    def test_vm_zero_delay(self):
        """Test VM with zero delay override."""
        vm = VMNetworkConfig(name="vm_local", network_delay=0.0)

        assert vm.network_delay == 0.0

    def test_vm_negative_delay_rejected(self):
        """Test that negative VM delay is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            VMNetworkConfig(name="vm_bad", network_delay=-10.0)

        assert "network_delay" in str(exc_info.value)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_vm_name_required(self):
        """Test that VM name is required."""
        with pytest.raises(ValidationError) as exc_info:
            VMNetworkConfig(network_delay=20.0)

        assert "name" in str(exc_info.value)

    def test_vm_high_latency_zone(self):
        """Test VM in high-latency availability zone."""
        vm = VMNetworkConfig(name="vm_remote_az", network_delay=100.0)

        assert vm.network_delay == 100.0


class TestWorkloadNetworkConfig:
    """Test workload-specific network configuration."""

    def test_workload_basic_creation(self):
        """Test basic workload network config creation."""
        wl = WorkloadNetworkConfig(app="app_0", network_delay=20.0)

        assert wl.app == "app_0"
        assert wl.network_delay == 20.0

    def test_workload_no_override(self):
        """Test workload config without delay override."""
        wl = WorkloadNetworkConfig(app="app_local")

        assert wl.app == "app_local"
        assert wl.network_delay is None

    def test_workload_explicit_none(self):
        """Test explicit None for network_delay."""
        wl = WorkloadNetworkConfig(app="app_1", network_delay=None)

        assert wl.network_delay is None

    def test_workload_zero_delay(self):
        """Test workload with zero delay override."""
        wl = WorkloadNetworkConfig(app="app_colocated", network_delay=0.0)

        assert wl.network_delay == 0.0

    def test_workload_negative_delay_rejected(self):
        """Test that negative workload delay is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WorkloadNetworkConfig(app="app_bad", network_delay=-5.0)

        assert "network_delay" in str(exc_info.value)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_workload_app_required(self):
        """Test that app name is required."""
        with pytest.raises(ValidationError) as exc_info:
            WorkloadNetworkConfig(network_delay=15.0)

        assert "app" in str(exc_info.value)

    def test_workload_remote_region(self):
        """Test workload from remote region."""
        wl = WorkloadNetworkConfig(app="app_us_west", network_delay=150.0)

        assert wl.network_delay == 150.0


class TestNetworkConfigIntegration:
    """Test integration scenarios with multiple configs."""

    def test_mixed_overrides(self):
        """Test scenario with both VM and workload overrides."""
        # Global defaults
        global_delays = NetworkDelays(wi_to_lb=10.0, lb_to_vm=5.0)

        # Some VMs with overrides
        vm_fast = VMNetworkConfig(name="vm_1")  # uses default
        vm_slow = VMNetworkConfig(name="vm_2", network_delay=50.0)  # override

        # Some workloads with overrides
        wl_local = WorkloadNetworkConfig(app="app_0")  # uses default
        wl_remote = WorkloadNetworkConfig(app="app_1", network_delay=100.0)  # override

        assert global_delays.wi_to_lb == 10.0
        assert global_delays.lb_to_vm_default == 5.0
        assert vm_fast.network_delay is None
        assert vm_slow.network_delay == 50.0
        assert wl_local.network_delay is None
        assert wl_remote.network_delay == 100.0

    def test_resolution_logic_simulation(self):
        """Test delay resolution logic (simulates builder behavior)."""
        global_delays = NetworkDelays(wi_to_lb=10.0, lb_to_vm_default=5.0)

        vm_configs = [
            VMNetworkConfig(name="vm_1"),  # None
            VMNetworkConfig(name="vm_2", network_delay=50.0),
        ]

        wl_configs = [
            WorkloadNetworkConfig(app="app_0"),  # None
            WorkloadNetworkConfig(app="app_1", network_delay=20.0),
        ]

        # Simulate resolution: override if present, else default
        def get_wi_to_lb_delay(wl: WorkloadNetworkConfig) -> float:
            return (
                wl.network_delay
                if wl.network_delay is not None
                else global_delays.wi_to_lb
            )

        def get_lb_to_vm_delay(vm: VMNetworkConfig) -> float:
            return (
                vm.network_delay
                if vm.network_delay is not None
                else global_delays.lb_to_vm_default
            )

        # Test resolution
        assert get_wi_to_lb_delay(wl_configs[0]) == 10.0  # uses default
        assert get_wi_to_lb_delay(wl_configs[1]) == 20.0  # uses override
        assert get_lb_to_vm_delay(vm_configs[0]) == 5.0  # uses default
        assert get_lb_to_vm_delay(vm_configs[1]) == 50.0  # uses override

    def test_all_zero_delays_fast_simulation(self):
        """Test that all zero delays are valid (for fast testing)."""
        global_delays = NetworkDelays(
            wi_to_lb=0.0,
            lb_to_vm_default=0.0,
            vm_container_overhead=0.0,
            runtime_init_overhead=0.0,
        )
        vm = VMNetworkConfig(name="vm_1", network_delay=0.0)
        wl = WorkloadNetworkConfig(app="app_0", network_delay=0.0)

        assert global_delays.wi_to_lb == 0.0
        assert vm.network_delay == 0.0
        assert wl.network_delay == 0.0
