from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Iterator, Protocol, runtime_checkable

import asimpy
import pluggy

if TYPE_CHECKING:
    from ..core.events import EventBus
    from ..core.infrastructure import (
        App,
        ContainerClass,
        InstanceClass,
    )
    from ..interfaces.protocols import CustomPluginProtocol


hookspec = pluggy.HookspecMarker("nuberu")


@runtime_checkable
class InfrastructureSpecs(Protocol):
    @hookspec
    def get_infrastructure_factory(
        self, config: dict[str, Any]
    ) -> callable[[], tuple[list[App], list[InstanceClass], list[ContainerClass]]]:
        """
        Return a factory function that, when called, returns (apps, instance_classes, container_classes).

        The factory allows lazy loading and internal caching by the plugin.

        Returns:
            Callable that takes no arguments and returns infrastructure tuples.
        """
        raise NotImplementedError


@runtime_checkable
class PerformanceSpecs(Protocol):
    """Define the methods that plugins must implement for Performance."""

    @hookspec
    def get_rps_for_app_factory(
        self, config: dict[str, Any]
    ) -> callable[[App, float, InstanceClass], float]:
        """
        Return a factory function that computes RPS for a given (app, cores, instance_class).

        The factory allows lazy loading of pickle data and internal caching.

        Args:
            config: Plugin configuration (e.g., {"pickle_path": "..."})

        Returns:
            Callable that takes (app, cores, instance_class) and returns RPS as float.
        """
        raise NotImplementedError


@runtime_checkable
class AllocationSpecs(Protocol):
    """Define the methods that plugins must implement for Allocations."""

    @hookspec
    def get_allocations_factory(
        self, config: dict[str, Any]
    ) -> callable[
        [dict[str, InstanceClass], dict[str, ContainerClass]],
        Iterable[list[dict[str, Any]]],
    ]:
        """
        Return a factory function that generates allocation instructions for the first time window.

        The factory takes instance_classes and container_classes dicts and returns
        an iterable of instruction lists (one per time window, typically just [instructions]).

        Each instruction is a dict with:
            {
                "action": "start_vm" | "create_container",
                "data": {
                    "vm_id": str,
                    "instance_class": InstanceClass,
                    ...
                }
            }

        Args:
            config: Plugin configuration

        Returns:
            Callable that takes (instance_classes, container_classes) and returns Iterable[list[dict]].
        """
        raise NotImplementedError


@runtime_checkable
class WorkloadSpecs(Protocol):
    """Define the methods that plugins must implement for Workloads."""

    @hookspec
    def get_distribution_params_for_app_factory(
        self, config: dict[str, Any]
    ) -> callable[[str], dict[str, int]]:
        """
        Return a factory function that extracts distribution params for a given app.

        Args:
            config: Plugin configuration (e.g., {"pickle_path": "..."})

        Returns:
            Callable that takes app_name (str) and returns:
            {
                "num_reqs": int,
                "time_slot_size": int  # in seconds
            }
        """
        raise NotImplementedError


@runtime_checkable
class ArrivalDistributionSpecs(Protocol):
    """Define the methods that plugins must implement for Workload distribution."""

    @hookspec
    def get_interarrival_times_factory(
        self, config: dict[str, Any], stop_time: float | None = None
    ) -> callable[[asimpy.Environment], Iterator[tuple[int, float]]]:
        """
        Return a factory function that creates interarrival time iterators.

        The factory takes (env) and returns an Iterator of (num_requests, interval) tuples.
        This allows the plugin to capture config and create the iterator lazily when
        the environment is available.

        Args:
            config: Plugin configuration (e.g., {"num_reqs": 1000, "time_slot_size": 3600})
            stop_time: Maximum time for request injection. If provided, the generator
                      should stop injecting requests at this time, regardless of other
                      config parameters (num_reqs, time_slot_size, etc.)

        Returns:
            Callable that takes (env) and returns Iterator[tuple[int, float]].
        """
        raise NotImplementedError


@runtime_checkable
class LoadBalancerSpecs(Protocol):
    """Define the methods that plugins can implement for core simulation components."""

    @hookspec
    def get_load_balancer_factory(self, config: dict[str, Any]) -> callable:
        """
        Return a factory function that creates LoadBalancer instances.

        The factory takes (env, registry, event_bus, request_channel) and returns
        a LoadBalancer instance.

        Args:
            config: Plugin configuration (e.g., {"policy": "round_robin"})

        Returns:
            Callable that takes simulation dependencies and returns LoadBalancer instance.
        """
        raise NotImplementedError


@runtime_checkable
class CostModelSpecs(Protocol):
    """Define the methods that plugins can implement for cost models."""

    @hookspec
    def get_cost_model_factory(self, config: dict[str, Any]) -> callable:
        """
        Return a factory function (typically the class constructor) that creates CostModel instances.

        The factory takes (env, event_bus) and returns a CostModelProtocol instance.

        Args:
            config: Plugin configuration

        Returns:
            Callable that takes (env, event_bus) and returns CostModelProtocol instance.
            Typically this is just the class itself, which acts as a factory.
        """
        raise NotImplementedError


@runtime_checkable
class RuntimeModelSpecs(Protocol):
    """Define the methods that plugins must implement for Runtime Models."""

    @hookspec
    def get_runtime_model_factory(self, config: dict[str, Any]) -> callable:
        """
        Return a factory function that creates RuntimeModel instances.

        The factory captures configuration (e.g., queue_size) and returns a function
        that accepts runtime dependencies and creates a RuntimeModel instance.

        The factory signature is:
            (env, container, performance, event_bus, duplex_channel, idle_sink, progress_sink) -> RuntimeModelProtocol

        Where:
            - env: asimpy.Environment - The simulation environment
            - container: Container - The container this runtime model belongs to
            - performance: float - Requests per second (RPS) that the container can handle
            - event_bus: EventBus - Event bus for communication between components
            - duplex_channel: DuplexChannel - Bidirectional channel Container<->RuntimeModel
            - idle_sink: asimpy.Store | None - Private point-to-point signal to notify drain completion
            - progress_sink: asimpy.Store | None - Private signal to report completed requests during drain

        Args:
            config: Plugin configuration (e.g., {"queue_size": 1})

        Returns:
            Callable that takes (env, container, performance, event_bus, duplex_channel, idle_sink, progress_sink)
            and returns a RuntimeModel instance.
        """
        raise NotImplementedError


@runtime_checkable
class CustomPluginSpecs(Protocol):
    """Define the methods that plugins must implement for Custom Plugins."""

    @hookspec
    def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with the provided configuration.

        Args:
            config: Plugin configuration
        """
        raise NotImplementedError

    @hookspec
    def get_factory(
        self, config: dict[str, Any]
    ) -> callable[[asimpy.Environment, EventBus], CustomPluginProtocol]:
        """
        Return a factory function that creates CustomPluginProtocol instances.

        The factory takes (env, event_bus) and returns a CustomPluginProtocol instance.

        Args:
            config: Plugin configuration

        Returns:
            Callable that takes (env, event_bus) and returns CustomPluginProtocol instance.
        """
        raise NotImplementedError
