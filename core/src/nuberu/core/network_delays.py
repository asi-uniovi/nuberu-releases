"""Network delay configuration for bidirectional request-response flow.

This module provides configuration structures for modeling network latencies
in the bidirectional communication between simulation components (RFC 001).

The configuration supports:
- Global default delays between component layers
- Per-VM delay overrides
- Per-workload delay overrides
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NetworkDelays(BaseModel):
    """Network delays and overheads for bidirectional request-response flow.

    Phase 1 assumes all components in same availability zone (low latency).
    Use per-VM overrides for heterogeneous setups, or Phase 2 Regions for
    realistic multi-region topologies.

    All values are in milliseconds. Network delays model actual data transfer,
    while overheads model virtualization/runtime initialization costs.

    Attributes:
        wi_to_lb: Network delay between WorkloadInjector and LoadBalancer
        lb_to_vm_default: Default network delay between LoadBalancer and VM (same AZ)
        vm_container_overhead: Container startup overhead within VM (NOT network)

    Note:
        runtime_init_overhead is defined but NOT currently used in simulation.
        Reserved for future cold-start overhead implementation in RuntimeModel.

    Examples:
        >>> delays = NetworkDelays(wi_to_lb=10.0, lb_to_vm_default=5.0)
        >>> delays.wi_to_lb
        10.0
    """

    wi_to_lb: float = Field(
        default=10.0,
        description="Network delay (ms) between WorkloadInjector and LoadBalancer",
        ge=0.0,
    )
    lb_to_vm_default: float = Field(
        default=5.0,
        description="Default network delay (ms) between LoadBalancer and VM (same AZ)",
        ge=0.0,
    )
    wi_to_lb_backward: Optional[float] = Field(
        default=None,
        description="Backward network delay (ms) LB->WI. If None, uses wi_to_lb (symmetric).",
        ge=0.0,
    )
    lb_to_vm_default_backward: Optional[float] = Field(
        default=None,
        description="Default backward accuracy delay (ms) VM->LB. If None, uses lb_to_vm_default (symmetric).",
        ge=0.0,
    )
    vm_container_overhead: float = Field(
        default=2.0,
        description="Container startup overhead (ms) within VM - NOT network delay",
        ge=0.0,
    )
    drain_grace_period: float = Field(
        default=500.0,
        description="Grace period (ms) for in-flight requests during container drain",
        ge=0.0,
    )
    # FUTURE: runtime_init_overhead reserved for cold-start overhead in RuntimeModel
    # Uncomment when implementing this feature:
    # runtime_init_overhead: float = Field(
    #     default=1.0,
    #     description="Runtime initialization overhead (ms) - NOT network delay",
    #     ge=0.0,
    # )

    @field_validator(
        "wi_to_lb",
        "wi_to_lb_backward",
        "lb_to_vm_default",
        "lb_to_vm_default_backward",
        "vm_container_overhead",
        "drain_grace_period",
    )
    @classmethod
    def validate_non_negative(cls, v: Optional[float]) -> Optional[float]:
        """Ensure all delays/overheads are non-negative."""
        if v is not None and v < 0:
            raise ValueError("Network delays and overheads must be >= 0")
        return v


class VMNetworkConfig(BaseModel):
    """Network configuration override for a specific VM.

    Allows overriding the global lb_to_vm_default delay for specific VMs.
    This is useful for modeling heterogeneous network conditions or
    VMs in different availability zones.

    Attributes:
        name: VM identifier (must match infrastructure config)
        network_delay: Override for lb_to_vm_default forward delay (ms)
        network_delay_backward: Override for VM->LB delay (ms). If None, uses network_delay.
    """

    name: str = Field(description="VM name (must match infrastructure config)")
    network_delay: Optional[float] = Field(
        default=None,
        description="Override for lb_to_vm_default delay (ms). If None, uses global default.",
        ge=0.0,
    )
    network_delay_backward: Optional[float] = Field(
        default=None,
        description="Override for VM->LB delay (ms). If None, uses network_delay (symmetric).",
        ge=0.0,
    )

    @field_validator("network_delay", "network_delay_backward")
    @classmethod
    def validate_non_negative_delay(cls, v: Optional[float]) -> Optional[float]:
        """Ensure delay override is non-negative."""
        if v is not None and v < 0:
            raise ValueError("VM network_delay must be >= 0")
        return v


class WorkloadNetworkConfig(BaseModel):
    """Network configuration override for a specific workload.

    Allows overriding the global wi_to_lb delay for specific workloads.
    This is useful for modeling workloads from different geographic regions
    or with different network characteristics.

    Attributes:
        app: Application identifier (must match workload config)
        network_delay: Override for wi_to_lb forward delay (ms)
        network_delay_backward: Override for LB->WI delay (ms). If None, uses network_delay.
    """

    app: str = Field(description="Application name (must match workload config)")
    network_delay: Optional[float] = Field(
        default=None,
        description="Override for wi_to_lb delay (ms). If None, uses global default.",
        ge=0.0,
    )
    network_delay_backward: Optional[float] = Field(
        default=None,
        description="Override for LB->WI delay (ms). If None, uses network_delay (symmetric).",
        ge=0.0,
    )

    @field_validator("network_delay", "network_delay_backward")
    @classmethod
    def validate_non_negative_delay(cls, v: Optional[float]) -> Optional[float]:
        """Ensure delay override is non-negative."""
        if v is not None and v < 0:
            raise ValueError("Workload network_delay must be >= 0")
        return v
