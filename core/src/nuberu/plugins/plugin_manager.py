import importlib.metadata as metadata
import logging

import pluggy

from ..plugins import hookspecs

logger = logging.getLogger(__name__)


class PluginManager:
    """
    Manages the loading and execution of plugins for Allocations, Workloads and Performance.
    """

    pm: pluggy.PluginManager

    def __init__(self) -> None:
        self.pm = pluggy.PluginManager("nuberu")
        # Register the hookspecs for Allocations, Workloads and Performance
        self.pm.add_hookspecs(hookspecs.AllocationSpecs)
        self.pm.add_hookspecs(hookspecs.WorkloadSpecs)
        self.pm.add_hookspecs(hookspecs.PerformanceSpecs)
        self.pm.add_hookspecs(hookspecs.LoadBalancerSpecs)
        self.pm.add_hookspecs(hookspecs.CostModelSpecs)
        self.pm.add_hookspecs(hookspecs.InfrastructureSpecs)
        self.pm.add_hookspecs(hookspecs.ArrivalDistributionSpecs)
        self.pm.add_hookspecs(hookspecs.RuntimeModelSpecs)
        self.pm.add_hookspecs(hookspecs.CustomPluginSpecs)

        self._by_type: dict[str, dict[str, object]] = {}

    def load_plugins(self, include: dict[str, list[str]] | None) -> None:
        """
         Loads all setuptools entry points under the group "nuberu", but only registers those
        whose plugin_name is in the 'include' list for the corresponding comp_type. If the same
        class is encountered twice (e.g. under "allocation.conlloovia" and "performance_data.conlloovia"),
        we catch the ValueError raised by Pluggy and reuse the existing instance instead of crashing.

        Args:
            include: A dict mapping each comp_type to a list of allowed plugin_names.
                     E.g. { "allocation": ["conlloovia"], "performance_data": ["conlloovia"], ... }
                     If None, plugin discovery is skipped entirely.
        """
        if include is None:
            logger.warning("Plugin discovery skipped: no include list provided.")
            return

        # 1) pluggy itself automatically registers all hook implementations
        # self.pm.load_setuptools_entrypoints("nuberu")

        # Iterate over all entry points registered under "nuberu"
        for ep in metadata.entry_points(group="nuberu"):
            # Each entry point name is of the form "<comp_type>.<plugin_name>"
            # For example: "allocation.conlloovia"
            comp_type, _, plugin_name = ep.name.partition(".")
            # if there is a filter and it's not in the list, skip it
            if include and plugin_name not in include.get(comp_type, []):
                continue
            # Load the plugin definition (could be a class or an instance)
            plugin_def = ep.load()  # load the plugin class (or instance)
            # if it is a class, instantiate it
            if isinstance(plugin_def, type):
                plugin_obj = plugin_def()
            else:
                plugin_obj = plugin_def

            # Attempt to register with Pluggy under the simple name 'plugin_name'.
            # If it was already registered (same class), catch ValueError and ignore it.
            try:
                self.pm.register(plugin_obj, name=plugin_name)
            except ValueError:
                # The same class has already been registered under this name; reuse it.
                pass

            # Store in our own mapping for get_plugin lookups
            self._by_type.setdefault(comp_type, {})[plugin_name] = plugin_obj

    def register(self, plugin: object) -> None:
        """Register a plugin manually."""
        self.pm.register(plugin)

    def get_plugin(self, comp_type: str, plugin_name: str) -> object:
        """
        Return the plugin instance for given component type and name.
        Validates that the plugin implements the required Protocol.
        Raises ValueError if not found or if it doesn't implement the required interface.
        """
        # Map component types to their corresponding Protocol classes
        protocol_map = {
            "allocation": hookspecs.AllocationSpecs,
            "workload": hookspecs.WorkloadSpecs,
            "performance": hookspecs.PerformanceSpecs,
            "load_balancer": hookspecs.LoadBalancerSpecs,
            "cost_model": hookspecs.CostModelSpecs,
            "infrastructure": hookspecs.InfrastructureSpecs,
            "arrival_distribution": hookspecs.ArrivalDistributionSpecs,
            "runtime_model": hookspecs.RuntimeModelSpecs,
            "custom": hookspecs.CustomPluginSpecs,
        }

        type_map = self._by_type.get(comp_type, {})
        # 1) Search by exact key (entry-point suffix)
        inst = type_map.get(plugin_name)
        if not inst:
            # 2) If not found, search by class name
            for inst_ in type_map.values():
                if inst_.__class__.__name__.lower() == plugin_name.lower():
                    inst = inst_
                    break

        if not inst:
            raise ValueError(
                f"No plugin for type '{comp_type}' and name '{plugin_name}'. "
                f"Available: {list(type_map.keys())}"
            )

        # 3) Verify that the plugin implements the required Protocol
        expected_protocol = protocol_map.get(comp_type)
        if expected_protocol and not isinstance(inst, expected_protocol):
            # Get protocol methods for helpful error message
            protocol_methods = [
                attr
                for attr in dir(expected_protocol)
                if not attr.startswith("_")
                and callable(getattr(expected_protocol, attr, None))
            ]
            raise TypeError(
                f"Plugin '{plugin_name}' for type '{comp_type}' does not implement "
                f"the required interface ({expected_protocol.__name__}). "
                f"Required methods: {', '.join(protocol_methods) if protocol_methods else 'see protocol definition'}"
            )

        return inst

    def list_registered_plugins(self) -> dict[str, list[str]]:
        """Map each component type to its available plugin names."""
        return {t: list(names.keys()) for t, names in self._by_type.items()}
