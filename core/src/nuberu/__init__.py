# Version information
__version__ = "0.4.0"

# Core components from the simulation framework
# Channels for communication
from .channels import Channel
from .components.registry import Registry
from .components.vm import VM
from .core.events import EventBus, EventTopic

# Core infrastructure and states
from .core.infrastructure import (
    App,
    ContainerClass,
    InstanceClass,
    Workload,
)

# Core utilities
from .core.simulation import Simulation
from .core.simulation_builder import SimulationBuilder
from .core.states import ContainerState, RequestState, VMState

# Protocols
from .interfaces.protocols import (
    CostModelProtocol,
    LoadBalancerProtocol,
    RuntimeModelProtocol,
)

# Plugin system
from .plugins.hookspecs import (
    AllocationSpecs,
    ArrivalDistributionSpecs,
    CostModelSpecs,
    LoadBalancerSpecs,
    PerformanceSpecs,
    RuntimeModelSpecs,
    WorkloadSpecs,
)
from .plugins.plugin_manager import PluginManager

# Workloads and allocations
from .workload.request import Request
from .workload.workload_injector import WorkloadInjector

# Exported symbols for the module
__all__ = [
    "App",
    "Channel",
    "ContainerClass",
    "ContainerState",
    "InstanceClass",
    "PluginManager",
    "Request",
    "RequestState",
    "Simulation",
    "SimulationBuilder",
    "VM",
    "VMState",
    "Workload",
    "WorkloadSpecs",
    "AllocationSpecs",
    "ArrivalDistributionSpecs",
    "PerformanceSpecs",
    "LoadBalancerSpecs",
    "CostModelSpecs",
    "RuntimeModelSpecs",
    "WorkloadInjector",
    "Registry",
    "EventBus",
    "EventTopic",
    "CostModelProtocol",
    "LoadBalancerProtocol",
    "RuntimeModelProtocol",
]
