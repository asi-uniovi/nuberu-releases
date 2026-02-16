from __future__ import annotations

import logging
import random
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

import asimpy
import yaml

from nuberu.plugins.hookspecs import (
    AllocationSpecs,
    InfrastructureSpecs,
    PerformanceSpecs,
)

from .simulation_config import SimulationConfig
from .yaml_providers import (
    YamlPerformanceProvider,
    load_allocations_yaml,
    load_infrastructure_yaml,
)

if TYPE_CHECKING:
    from ..channels.channel import Channel
    from ..core.events import EventBus
    from ..core.infrastructure import App, InstanceClass
    from ..workload.workload_injector import WorkloadInjector

if TYPE_CHECKING:
    from .simulation import Simulation

logger = logging.getLogger(__name__)


class SimulationBuilder:
    """Build a :class:`Simulation` object from YAML"""

    def __init__(
        self,
        config_source: Path | dict[str, Any],
        base_dir: Path | None = None,
    ):
        _raw_cfg = self._load(config_source)

        self._get_rps_cb: Callable[[App, float, InstanceClass], float]

        if base_dir is not None:
            self._base_dir = base_dir.resolve()
        elif isinstance(config_source, Path):
            self._base_dir = config_source.parent.resolve()
        else:
            self._base_dir = Path.cwd()

        # Resolve dynamic paths in the configuration
        _raw_cfg = self._resolve_dynamic_paths(_raw_cfg)

        # Validate and parse the configuration
        self.cfg = SimulationConfig.model_validate(
            _raw_cfg, context={"base_dir": self._base_dir}
        )

        self.env = asimpy.Environment()
        self.env.stop_time = self.cfg.simulation.stop_time

        # -- Logging hooked to sim-time first --------------------------------
        self._setup_logging()
        from ..core.setup_logging import set_sim_time_getter

        set_sim_time_getter(lambda: self.env.now)

        logger.debug("Simulation configuration:")
        logger.debug(f"Logging config: {self.cfg.logging}")

        # Set the random seed for reproducibility
        random.seed(self.cfg.simulation.seed)
        logger.debug(f"Simulation seed set to: {self.cfg.simulation.seed}")

        mode_str = "ENABLED" if self.cfg.simulation.eager_start else "disabled"
        logger.info(
            f"Eager start mode is {mode_str}. "
            f"{'All VMs and containers will be created at t=0 before any request.' if self.cfg.simulation.eager_start else 'Requests will start as soon as the injector is initialized.'}",
        )

        # Initialize the plugin manager and load plugins
        from ..plugins.plugin_manager import PluginManager

        self.pm = PluginManager()
        self.pm.load_plugins(include=self._build_include_map())
        logger.debug(f"Plugins registered: {self.pm.list_registered_plugins()}")

    def _build_include_map(self) -> dict[str, list[str]]:
        """
        Build the {comp_type: [plugin_name, …]} map that tells the PluginManager
        which plugins to load. Empty lists mean "nothing to load" for that type.
        """

        def _maybe(name: str | None) -> list[str]:
            return [name] if name else []

        return {
            "infrastructure": (
                _maybe(self.cfg.infrastructure.plugin_name)
                if self.cfg.infrastructure.mode == "plugin"
                else []
            ),
            "performance": (
                _maybe(self.cfg.performance_data.plugin_name)
                if self.cfg.performance_data.mode == "plugin"
                else []
            ),
            "allocation": (
                _maybe(self.cfg.allocation.plugin_name)
                if self.cfg.allocation.mode == "plugin"
                else []
            ),
            "load_balancer": _maybe(self.cfg.load_balancer.plugin_name),
            "distribution": [
                wl.distribution.plugin_name
                for wl in self.cfg.workloads
                if wl.distribution.plugin_name
            ],
            "cost_model": [cm.plugin_name for cm in self.cfg.cost_models],
            "runtime_model": (
                (
                    [self.cfg.runtime_model.plugin_name]
                    if self.cfg.runtime_model is not None
                    else []
                )
                + [rm.plugin_name for rm in self.cfg.runtime_models.values()]
            ),
            "custom": [cp.plugin_name for cp in self.cfg.custom_plugins],
            "workload": [
                wl.distribution.workloads_plugin_name
                for wl in self.cfg.workloads
                if getattr(wl.distribution, "workloads_plugin_name", None)
            ],
        }

    # CLI overrides ---------------------------------------------------------

    def set_drain_mode(self, drain_pending_requests: bool) -> None:
        """Force drain policy to the provided value (CLI overrides config)."""

        self.cfg = self.cfg.model_copy(
            update={
                "simulation": self.cfg.simulation.model_copy(
                    update={"drain_pending_requests": drain_pending_requests}
                )
            }
        )
        logger.info(
            f"Drain pending requests set via override: {drain_pending_requests}"
        )

    # Public ------------------------------------------------------------------

    def build(self) -> Simulation:
        """Return a fully wired Simulation ready to `.run()`."""

        # -- Event bus -----------------------------------------

        from ..core.events import EventBus

        event_bus = EventBus(self.env)

        # -- Unique channels --------------------------------------------------
        from ..channels import Channel, DuplexChannel

        allocator_channel = Channel(self.env)

        # Create DuplexChannel per app for WorkloadInjector <-> LoadBalancer com
        # Each app can have different network delay via workload_network_overrides
        # Forward: WI -> LB (requests), Backward: LB -> WI (responses)
        lb_duplex_channels: dict[str, DuplexChannel] = {}
        for wl_entry in self.cfg.workloads:
            app_name = wl_entry.app
            delay_fwd, delay_bwd = self._get_wi_to_lb_delays(app_name)
            lb_duplex_channels[app_name] = DuplexChannel(
                env=self.env,
                forward_delay=delay_fwd,
                backward_delay=delay_bwd,
            )

        # -- Load Infrastructure (from YAML or plugin) -------------------
        # Save the infrastructure data into canonical variables
        self._load_infrastructure()

        # -- InfrastructureManager & Allocator (share allocator_channel) -----------
        # Load PerformanceData necessary for the allocations and infrastructure manager
        logger.debug(f"Initial performance data: {self.cfg.performance_data}.")
        self._load_performance()

        # Create runtime model factories for each app
        runtime_model_factories = self._create_runtime_model_factories(
            list(self.apps.values())
        )

        infra_manager = self._make_infrastructure_manager(
            event_bus, allocator_channel, runtime_model_factories
        )

        allocator = self._make_allocator(event_bus, allocator_channel)

        # -- Registry & LoadBalancer ------------
        registry = self._make_registry(event_bus)
        load_balancer = self._make_load_balancer(
            registry, event_bus, lb_duplex_channels
        )

        # -- Workload injector ---------------------
        injector = self._make_workload_injector(
            lb_duplex_channels,
            event_bus,
            self.cfg.stop_time,
            self.cfg.eager_start,
        )

        # -- Cost models ------------------------------------------------------
        cost_models = self._instantiate_cost_models(event_bus)

        # -- Custom plugins ---------------------------------------------------
        custom_plugins = self._instantiate_custom_plugins(event_bus)

        # -- Wrap it all into Simulation -------------------------------------
        from ..core.simulation import Simulation  # local import to avoid cycles

        return Simulation(
            env=self.env,
            allocator=allocator,
            infra_manager=infra_manager,
            registry=registry,
            load_balancer=load_balancer,
            workload_injector=injector,
            cost_models=cost_models,
            custom_plugins=custom_plugins,
            event_bus=event_bus,
            stop_time=self.cfg.stop_time,
        )

    ############################################################################
    # Helper methods -----------------------------------------------------------
    ############################################################################

    @staticmethod
    def _load(src: Path | dict[str, Any]) -> dict[str, Any]:
        if isinstance(src, Path):
            return yaml.safe_load(src.read_text())
        return src

    # -- Logging -------------------------------------------------------------

    def _setup_logging(self) -> None:
        from ..core.setup_logging import setup_logging_from_config

        setup_logging_from_config(self.cfg.logging.model_dump())

    # -- Infrastructure / Allocator -----------------------------------------

    def _get_wi_to_lb_delays(self, app_name: str) -> tuple[float, float]:
        """Get forward and backward network delays for workload (seconds).

        Args:
            app_name: Application name to lookup.

        Returns:
            Tuple (forward_delay, backward_delay) in seconds.
        """
        # 1. Check overrides
        for override in self.cfg.workload_network_overrides:
            if override.app == app_name and override.network_delay is not None:
                delay_fwd_ms = override.network_delay
                # Backward defaults to forward if not specified (symmetric)
                delay_bwd_ms = (
                    override.network_delay_backward
                    if override.network_delay_backward is not None
                    else delay_fwd_ms
                )

                logger.info(
                    f"Using WI->LB delay OVERRIDE for app '{app_name}': "
                    f"FWD={delay_fwd_ms}ms, BWD={delay_bwd_ms}ms"
                )
                return delay_fwd_ms / 1000.0, delay_bwd_ms / 1000.0

        # 2. Check global defaults
        if self.cfg.network_delays:
            delay_fwd_ms = self.cfg.network_delays.wi_to_lb
            delay_bwd_ms = (
                self.cfg.network_delays.wi_to_lb_backward
                if self.cfg.network_delays.wi_to_lb_backward is not None
                else delay_fwd_ms
            )

            if delay_fwd_ms > 0 or delay_bwd_ms > 0:
                logger.info(
                    f"Using global WI->LB delay for app '{app_name}': "
                    f"FWD={delay_fwd_ms}ms, BWD={delay_bwd_ms}ms"
                )
            return delay_fwd_ms / 1000.0, delay_bwd_ms / 1000.0

        return 0.0, 0.0

    def _make_infrastructure_manager(
        self,
        event_bus: EventBus,
        channel: Channel,
        runtime_model_factories: dict[str, Callable],
    ):
        from ..components.infrastructure_manager import InfrastructureManager

        # Get vm_container_overhead and drain_grace_period from network_delays config (convert ms to seconds)
        vm_container_overhead = 0.0
        lb_to_vm_delay = 0.0
        drain_grace_period = 0.5  # Default 500ms
        if self.cfg.network_delays:
            vm_container_overhead = (
                self.cfg.network_delays.vm_container_overhead / 1000.0
            )
            lb_to_vm_delay = self.cfg.network_delays.lb_to_vm_default / 1000.0
            drain_grace_period = self.cfg.network_delays.drain_grace_period / 1000.0
            # Resolve backward default logic here
            backward_ms = (
                self.cfg.network_delays.lb_to_vm_default_backward
                if self.cfg.network_delays.lb_to_vm_default_backward is not None
                else self.cfg.network_delays.lb_to_vm_default
            )
            lb_to_vm_delay_backward = backward_ms / 1000.0
        else:
            lb_to_vm_delay_backward = 0.0

        return InfrastructureManager(
            env=self.env,
            allocator_channel=channel,
            event_bus=event_bus,
            runtime_model_factories=runtime_model_factories,
            eager_start=self.cfg.eager_start,
            get_rps_cb=self._get_rps_cb,
            vm_container_overhead=vm_container_overhead,
            lb_to_vm_delay=lb_to_vm_delay,
            lb_to_vm_delay_backward=lb_to_vm_delay_backward,
            drain_grace_period=drain_grace_period,
            vm_network_overrides=self.cfg.vm_network_overrides,
            drain_pending_requests=self.cfg.drain,
        )

    def _make_allocator(self, event_bus, channel):
        from ..components.allocator import Allocator

        allocations_iter = self._load_allocations()

        return Allocator(
            env=self.env,
            allocations=allocations_iter,
            channel=channel,
            event_bus=event_bus,
            eager_start=self.cfg.eager_start,
            allocator_interval=self.cfg.allocator_interval,
        )

    # -- Registry ------------------------------------------------------------

    def _make_registry(self, event_bus):
        from ..components.registry import Registry

        return Registry(env=self.env, event_bus=event_bus)

    # -- Load balancer -------------------------------------------------------

    def _make_load_balancer(self, registry, event_bus, wi_duplex_channels):
        """Create LoadBalancer with per-app DuplexChannels for bidirectional communication."""
        wrapper = self.pm.get_plugin(
            "load_balancer", self.cfg.load_balancer.plugin_name
        )
        # Get factory from plugin
        lb_factory = wrapper.get_load_balancer_factory(
            config=self.cfg.load_balancer.plugin_config
        )
        logger.debug(
            f"Using LoadBalancer plugin with name: {self.cfg.load_balancer.plugin_name}"
        )
        # Call factory to create instance with per-app DuplexChannels
        return lb_factory(
            env=self.env,
            registry=registry,
            event_bus=event_bus,
            wi_duplex_channels=wi_duplex_channels,
        )

    # -- Workload injector ---------------------------------------------------

    def _make_workload_injector(
        self,
        lb_duplex_channels: dict,  # dict[str, DuplexChannel] per app
        event_bus: EventBus,
        stop_time: float,
        eager_start: bool,
    ) -> WorkloadInjector:
        """Create WorkloadInjector with per-app DuplexChannels for bidirectional communication."""
        from ..core.infrastructure import App, Workload
        from ..workload.workload_injector import WorkloadInjector

        workloads: list[Workload] = []
        app_configs: dict[str, dict[str, Any]] = {}

        logger.info(f"Loading {len(self.cfg.workloads)} workloads (one for each app)")

        for workload_entry in self.cfg.workloads:
            app_name = workload_entry.app
            dist_cfg = workload_entry.distribution

            # Get the distribution plugin using the plugin_name
            dist_plugin = self.pm.get_plugin("distribution", dist_cfg.plugin_name)
            logger.debug(
                f"Using Distribution plugin: {dist_cfg.plugin_name} for app {app_name}"
            )

            # Create the Workload object with the app name and distribution plugin
            workloads.append(Workload(app=App(app_name), distribution=dist_plugin))

            # Store the plugin configuration for this app
            app_configs[app_name] = dist_cfg.plugin_config

            logger.debug(f"Distribution for app '{app_name}': {dist_cfg.plugin_config}")

        return WorkloadInjector(
            env=self.env,
            lb_duplex_channels=lb_duplex_channels,
            workloads=workloads,
            event_bus=event_bus,
            stop_time=stop_time,
            app_configs=app_configs,
            eager_start=eager_start,
        )

    # -- Cost models ---------------------------------------------------------

    def _instantiate_cost_models(self, event_bus) -> list:
        """
        Gets the factory from the PluginManager and calls it to create instances.
        The factory receives env and event_bus as arguments.
        """
        from ..interfaces.protocols import CostModelProtocol

        instances: list[CostModelProtocol] = []

        for cm_cfg in self.cfg.cost_models:
            plugin_name = cm_cfg.plugin_name
            wrapper = self.pm.get_plugin("cost_model", plugin_name)

            # For backward compatibility with legacy cost model plugins that expect
            # the 'name' field in their configuration dictionary (pre-v2.1 plugin API),
            # we explicitly set 'name' here. Some older plugins rely on this field
            # for identification and may fail or misbehave if it is missing.
            config_for_plugin = {"name": plugin_name}
            config_for_plugin.update(cm_cfg.plugin_config)

            # Get factory from plugin
            cost_model_factory = wrapper.get_cost_model_factory(
                config=config_for_plugin
            )
            if cost_model_factory is None:
                raise RuntimeError(
                    f"Plugin '{plugin_name}' does not implement get_cost_model_factory()"
                )

            # Call factory to create instance (factory is the class constructor)
            instance = cost_model_factory(self.env, event_bus)
            logger.debug(
                f"Instantiated CostModel {instance.__class__.__name__} from factory"
            )

            instances.append(instance)

        return instances

    # -- Custom plugins ------------------------------------------------------

    def _instantiate_custom_plugins(self, event_bus) -> list:
        """
        Instantiate custom plugins defined in the simulation configuration.

        Args:
            event_bus: The event bus instance to be passed to the plugin factories.

        Returns:
            List of instantiated custom plugins.
        """
        from ..interfaces.protocols import CustomPluginProtocol

        instances: list[CustomPluginProtocol] = []

        for cp_cfg in self.cfg.custom_plugins:
            plugin_name = cp_cfg.plugin_name
            wrapper = self.pm.get_plugin("custom", plugin_name)

            # Configure the plugin
            wrapper.configure(cp_cfg.plugin_config)

            # Get factory from plugin
            factory = wrapper.get_factory(cp_cfg.plugin_config)
            if factory is None:
                raise RuntimeError(
                    f"Plugin '{plugin_name}' does not implement get_factory()"
                )

            # Call factory to create instance
            instance = factory(self.env, event_bus)
            logger.debug(f"Instantiated CustomPlugin '{plugin_name}' from factory")

            instances.append(instance)

        return instances

    # -- Runtime model -------------------------------------------------------

    def _get_runtime_model_config_for_app(self, app_name: str) -> dict[str, Any]:
        """
        Get the runtime model configuration for a specific app.
        Returns per-app override if exists, otherwise returns default config.

        Args:
            app_name: Name of the application

        Returns:
            Dictionary with plugin_name and plugin_config

        Raises:
            RuntimeError: If no configuration is found for the app
        """
        # Check if there's a per-app override
        if app_name in self.cfg.runtime_models:
            app_config = self.cfg.runtime_models[app_name]
            return {
                "plugin_name": app_config.plugin_name,
                "plugin_config": app_config.plugin_config,
            }

        # Otherwise use default (if exists)
        if self.cfg.runtime_model is not None:
            return {
                "plugin_name": self.cfg.runtime_model.plugin_name,
                "plugin_config": self.cfg.runtime_model.plugin_config,
            }

        # This should never happen due to validation in SimulationConfig
        raise RuntimeError(
            f"No runtime model configuration found for app '{app_name}'. "
            f"This should have been caught during configuration validation."
        )

    def _create_runtime_model_factories(self, apps: list[App]) -> dict[str, Callable]:
        """
        Create runtime model factories for each app using the plugin system.

        Args:
            apps: List of application objects

        Returns:
            Dictionary mapping app_name to factory function
        """
        factories: dict[str, Callable] = {}
        runtime_info: list[str] = []

        for app in apps:
            app_name = app.name
            config = self._get_runtime_model_config_for_app(app_name)
            plugin_name = config["plugin_name"]
            plugin_config = config["plugin_config"]

            # Check if this app uses the default configuration
            is_default = app_name not in (self.cfg.runtime_models or {})

            # Get the runtime model plugin
            runtime_plugin = self.pm.get_plugin("runtime_model", plugin_name)
            logger.debug(f"Using RuntimeModel plugin: {plugin_name} for app {app_name}")

            # Get factory from plugin (captures plugin_config)
            factory = runtime_plugin.get_runtime_model_factory(config=plugin_config)
            if factory is None:
                raise RuntimeError(
                    f"Plugin '{plugin_name}' does not implement get_runtime_model_factory()"
                )

            factories[app_name] = factory
            logger.debug(
                f"Runtime model factory created for app '{app_name}' with config: {plugin_config}"
            )

            # Collect runtime info for logging
            if is_default:
                runtime_info.append(f"  - {app_name}: {plugin_name} (default)")
            else:
                runtime_info.append(f"  - {app_name}: {plugin_name}")

        # Log runtime model assignment for all apps
        logger.info("Runtime models per application:")
        for line in runtime_info:
            logger.info(line)

        return factories

    def _resolve_dynamic_paths(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Returns a **copy** of `data` where any *str* value whose key name ends with
        `_path` or `_file` is converted to an absolute path based on `self._base_dir`.
        """
        clone = deepcopy(data)

        def _walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        _walk(value)
                    elif isinstance(value, str) and (
                        key.endswith(("_path", "_file", "_dir"))  # + _dir
                        or ("/" in value or "\\" in value)  # contains slash
                    ):
                        node[key] = str(
                            (self._base_dir / Path(value).expanduser()).resolve(
                                strict=False
                            )
                        )
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(clone)
        return clone

    def _load_infrastructure(self) -> None:
        """
        Load infrastructure (apps, instance classes, container classes) from either
        a plugin or a YAML file and store them in dictionaries keyed by name.
        """
        if self.cfg.infrastructure.mode == "plugin":
            plugin: InfrastructureSpecs = self.pm.get_plugin(
                "infrastructure", self.cfg.infrastructure.plugin_name
            )
            plugin_config = self.cfg.infrastructure.plugin_config
            # Get factory and call it to get infrastructure
            infrastructure_factory = plugin.get_infrastructure_factory(plugin_config)
            apps, ics, ccs = infrastructure_factory()
            logger.debug(
                f"Using infrastructure plugin '{self.cfg.infrastructure.plugin_name}' -> {len(apps)} apps, {len(ics)} instance classes, {len(ccs)} container classes"
            )
        else:
            apps, ics, ccs = load_infrastructure_yaml(self.cfg.infrastructure.yaml_path)
            logger.debug(
                f"Loaded {len(apps)} apps, {len(ics)} InstanceClasses, {len(ccs)} ContainerClasses from YAML '{self.cfg.infrastructure.yaml_path}'"
            )

        self.apps = {a.name: a for a in apps}
        self.ics = {ic.name: ic for ic in ics}
        self.ccs = {cc.name: cc for cc in ccs}

    def _load_performance(self) -> None:
        """
        Load performance data using YamlPerformanceProvider or a plugin.
        """
        performance_config = self.cfg.performance_data
        if performance_config.mode == "plugin":
            self.performance_plugin: PerformanceSpecs = self.pm.get_plugin(
                "performance", performance_config.plugin_name
            )
            plugin_config = performance_config.plugin_config
            # Get factory and store the resulting callback
            self._get_rps_cb = self.performance_plugin.get_rps_for_app_factory(
                plugin_config
            )
            logger.debug(
                f"Using PerformanceData plugin: {performance_config.plugin_name}"
            )
        elif performance_config.mode == "yaml":
            logger.debug(
                f"Loading performance data from YAML: {performance_config.yaml_path}"
            )
            self._yaml_perf = YamlPerformanceProvider(performance_config.yaml_path)
            self._get_rps_cb = lambda app, cores, ic: self._yaml_perf.get_rps_for_app(
                app, cores, ic
            )
            logger.debug(
                f"Loaded PerformanceData from YAML: {performance_config.yaml_path}"
            )
        else:
            raise ValueError(
                f"Unknown performance data mode: {performance_config.mode}"
            )

    def _load_allocations(self) -> Iterable:
        alloc_cfg = self.cfg.allocation
        if alloc_cfg.mode == "plugin":
            plugin: AllocationSpecs = self.pm.get_plugin(
                "allocation", alloc_cfg.plugin_name
            )
            plugin_config = alloc_cfg.plugin_config
            # Get factory and call it with instance_classes and container_classes
            allocations_factory = plugin.get_allocations_factory(plugin_config)
            allocations_iter: Iterable = allocations_factory(self.ics, self.ccs)
            logger.debug(f"Using Allocations plugin: {alloc_cfg.plugin_name}")
        elif alloc_cfg.mode == "yaml":
            allocations_iter = load_allocations_yaml(
                alloc_cfg.yaml_path,
                self.ics,
                self.ccs,
            )
            logger.info(f"Loaded allocations from YAML: {alloc_cfg.yaml_path}")
        else:
            raise ValueError(f"Unknown allocation mode: {alloc_cfg.mode}")
        logger.debug(
            f"Loaded: {len(list(allocations_iter))} allocations (instructions)"
        )
        return allocations_iter

    def generate_performance_yaml(self, output_path: str) -> None:
        """
        Generate a YAML file with performance data using the hook `get_rps_for_app`.

        Args:
            output_path (str): Path to save the generated YAML file.
        """
        import yaml

        performance_data = {"performance": {"apps": {}}}

        for app_name, app in self.apps.items():
            app_data = {}
            for ic_name, ic in self.ics.items():
                samples = []
                for cc_name, cc in self.ccs.items():
                    if cc.app.name != app_name:
                        continue
                    try:
                        rps = self._get_rps_cb(app, cc.cores, ic)
                        samples.append({"cores": cc.cores, "rps": rps})
                    except ValueError as e:
                        logger.warning(
                            f"Skipping cores={cc.cores} for app={app_name}, IC={ic_name}: {e}"
                        )
                if samples:
                    app_data[ic_name] = samples
            if app_data:
                performance_data["performance"]["apps"][app_name] = app_data

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(performance_data, f, default_flow_style=False)

        logger.info(f"Performance YAML generated at: {output_path}")
