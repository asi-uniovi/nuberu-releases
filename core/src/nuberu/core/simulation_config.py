from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .network_delays import NetworkDelays, VMNetworkConfig, WorkloadNetworkConfig


class SimulationSection(BaseModel):
    seed: int = 12345
    stop_time: None | float = Field(
        None, description="Simulated seconds; *None* -> until idle"
    )
    eager_start: bool = False
    drain_pending_requests: bool = False
    # ToDo: This part is new, it wasn't configurable before.
    #       Maybe it should be a parameter of Allocator, not Simulation.
    allocator_interval: int = Field(
        250, description="Seconds between allocation cycles"
    )

    @field_validator("stop_time")
    @classmethod
    def _positive_or_none(cls, value: None | float) -> None | float:
        if value is not None and value <= 0:
            raise ValueError("stop_time must be > 0")
        return value


class LoggingConfig(BaseModel):
    log_to_file: bool = False
    log_to_console: bool = True
    level: str = "full"
    output_path: Path | None = None
    log_file_name: str | None = None

    # Allow extra fields in the logging config
    model_config = ConfigDict(extra="allow")

    @field_serializer("output_path")
    def serialize_output_path(self, v: Path | None, _info):
        return str(v) if v is not None else None

    @field_validator("output_path", mode="after")
    @classmethod
    def _resolve_paths(cls, value: Path | None, info):
        if value is None:
            return None
        base_dir: Path = info.context["base_dir"]
        return (base_dir / value.expanduser()).resolve(strict=False)


class PluginBasedConfig(BaseModel):
    """Base model for plugin-based configurations"""

    mode: Literal["plugin"] = Field(default="plugin", description="Configuration mode")
    plugin_name: str = Field(description="Plugin name to load")
    plugin_config: dict[str, Any] = Field(
        description="Plugin-specific configuration parameters. Use an empty dict {{}} if no configuration is needed."
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _validate_plugin_config_present(cls, data):
        """Ensure plugin_config key is present to avoid silent bugs."""
        if isinstance(data, dict):
            if "plugin_config" not in data:
                # Check if there are any extra keys that might have been intended for plugin_config
                known_keys = {"mode", "plugin_name", "plugin_config"}
                extra_keys = set(data.keys()) - known_keys
                if extra_keys:
                    raise ValueError(
                        f"Missing 'plugin_config' key. Found unexpected keys: {extra_keys}. "
                        f"These keys should be nested under 'plugin_config'. "
                        f"If you want to use default plugin values, use 'plugin_config: {{}}'"
                    )
                else:
                    raise ValueError(
                        "Missing required 'plugin_config' key. "
                        "If you want to use default plugin values, use 'plugin_config: {}'"
                    )
        return data


# Alias for distribution configuration (single-type, no Union needed)
DistributionConfig = PluginBasedConfig

LoadBalancerConfig = PluginBasedConfig

CustomPluginEntry = PluginBasedConfig


class AllocationConfigFromYaml(BaseModel):
    mode: Literal["yaml"] = Field(default="yaml", description="Configuration mode")
    yaml_path: Path | None = None


AllocationConfig = Annotated[
    Union[PluginBasedConfig, AllocationConfigFromYaml],
    Field(discriminator="mode", description="Allocation configuration mode"),
]


class InfrastructureConfigFromYaml(BaseModel):
    mode: Literal["yaml"] = Field(default="yaml", description="Configuration mode")
    yaml_path: Path | None = None


InfrastructureConfig = Annotated[
    Union[PluginBasedConfig, InfrastructureConfigFromYaml],
    Field(discriminator="mode", description="Infrastructure configuration mode"),
]


class WorkloadEntry(BaseModel):
    app: str
    distribution: DistributionConfig


class CostModelEntry(PluginBasedConfig):
    """Configuration for cost model plugins. Only accepts mode='plugin'."""

    pass


class RuntimeModelConfig(BaseModel):
    plugin_name: str = Field(description="Runtime model plugin name to load")
    plugin_config: dict[str, Any] = Field(
        description="Plugin-specific configuration parameters (e.g., queue_size). Use {{}} if no configuration is needed.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _validate_plugin_config_present(cls, data):
        """Ensure plugin_config key is present to avoid silent bugs."""
        if isinstance(data, dict):
            if "plugin_config" not in data:
                # Check if there are any extra keys that might have been intended for plugin_config
                known_keys = {"plugin_name", "plugin_config"}
                extra_keys = set(data.keys()) - known_keys
                if extra_keys:
                    raise ValueError(
                        f"Missing 'plugin_config' key in runtime_model. Found unexpected keys: {extra_keys}. "
                        f"These keys should be nested under 'plugin_config'. "
                        f"If you want to use default plugin values, use 'plugin_config: {{}}'"
                    )
                else:
                    raise ValueError(
                        "Missing required 'plugin_config' key in runtime_model. "
                        "If you want to use default plugin values, use 'plugin_config: {}'"
                    )
        return data


class PerformanceDataConfigFromYaml(BaseModel):
    """Configuration for performance data collection from a YAML file."""

    mode: Literal["yaml"] = Field(default="yaml", description="Configuration mode")
    yaml_path: Path | None = None


PerformanceDataConfig = Annotated[
    Union[PluginBasedConfig, PerformanceDataConfigFromYaml],
    Field(discriminator="mode", description="Performance data configuration mode"),
]


class SimulationConfig(BaseModel):
    config_version: Literal["2.1", "3.1", "3.2"] = Field(
        description="Configuration schema version"
    )
    simulation: SimulationSection
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    network_delays: Optional[NetworkDelays] = Field(
        default=None,
        description="Network delay configuration for bidirectional flow (RFC 001). Optional for backward compatibility.",
    )
    vm_network_overrides: list[VMNetworkConfig] = Field(
        default_factory=list,
        description="Per-VM network delay overrides. Overrides network_delays.lb_to_vm_default.",
    )
    workload_network_overrides: list[WorkloadNetworkConfig] = Field(
        default_factory=list,
        description="Per-workload network delay overrides. Overrides network_delays.wi_to_lb.",
    )
    allocation: AllocationConfig
    workloads: list[WorkloadEntry]
    load_balancer: LoadBalancerConfig
    cost_models: list[CostModelEntry] = Field(default_factory=list)
    custom_plugins: list[CustomPluginEntry] = Field(default_factory=list)
    runtime_model: Optional[RuntimeModelConfig] = Field(
        default=None,
        description="Default runtime model configuration for all applications",
    )
    runtime_models: dict[str, RuntimeModelConfig] = Field(
        default_factory=dict,
        description="Per-application runtime model overrides. Keys are app names.",
    )
    performance_data: PerformanceDataConfig

    infrastructure: InfrastructureConfig

    model_config = ConfigDict(extra="forbid")

    # Global validations

    @model_validator(mode="before")
    @classmethod
    def validate_version(cls, data):
        """Validate that config_version is present and supported"""
        if isinstance(data, dict) and "config_version" not in data:
            raise ValueError(
                "Configuration is missing 'config_version' field. "
                'Add \'config_version: "3.1"\' (or "2.1" for legacy) to the top of your YAML file. '
                "This appears to be a legacy configuration file."
            )
        return data

    @model_validator(mode="before")
    @classmethod
    def set_default_plugin_mode(cls, data):
        """Set appropriate mode based on available configuration keys.
        This is for backward compatibility with legacy configurations."""
        if isinstance(data, dict):
            for key in (
                "infrastructure",
                "performance_data",
                "allocation",
                "load_balancer",
            ):
                if (
                    key in data
                    and isinstance(data[key], dict)
                    and "mode" not in data[key]
                ):
                    # Only set plugin mode if plugin_name is present
                    if "plugin_name" in data[key]:
                        data[key]["mode"] = "plugin"
                    elif (
                        key in ("infrastructure", "performance_data", "allocation")
                        and "yaml_path" in data[key]
                    ):
                        data[key]["mode"] = "yaml"
                    else:
                        # For load_balancer, default to plugin mode since it's required
                        if key == "load_balancer":
                            data[key]["mode"] = "plugin"

            # Handle workloads distributions
            if "workloads" in data:
                for wl in data["workloads"]:
                    if isinstance(wl, dict) and "distribution" in wl:
                        dist = wl["distribution"]
                        if isinstance(dist, dict) and "mode" not in dist:
                            # Only set plugin mode if plugin_name is present
                            if "plugin_name" in dist:
                                dist["mode"] = "plugin"

            # Handle cost_models - convert legacy format to new plugin format
            if "cost_models" in data and isinstance(data["cost_models"], list):
                for cm in data["cost_models"]:
                    if isinstance(cm, dict):
                        # Convert legacy format {name: "plugin_name", ...} to new format.
                        # Legacy cost_model configs used "name" instead of "plugin_name" prior to v2.1.
                        # This backward compatibility logic ensures old configurations still work.
                        if "name" in cm and "plugin_name" not in cm:
                            cm["plugin_name"] = cm.pop("name")
                        # Set mode to plugin if not present
                        if "mode" not in cm:
                            cm["mode"] = "plugin"
                        # Move extra fields to plugin_config if not already there.
                        # This migration handles legacy configs where plugin parameters were
                        # defined at the top level instead of nested under plugin_config.
                        if "plugin_config" not in cm:
                            cm["plugin_config"] = {}
                        # Move any extra fields (except mode and plugin_name) to plugin_config
                        extra_fields = {
                            k: v
                            for k, v in cm.items()
                            if k not in ("mode", "plugin_name", "plugin_config")
                        }
                        if extra_fields:
                            cm["plugin_config"].update(extra_fields)
                            for k in extra_fields:
                                cm.pop(k)
        return data

    @model_validator(mode="after")
    def _check_workloads(self) -> "SimulationConfig":
        """Ensure at least one workload and unique app names."""
        if len(self.workloads) == 0:
            raise ValueError("workloads must contain at least one entry")
        apps = [wl.app for wl in self.workloads]
        if len(apps) != len(set(apps)):
            duplicates = [a for a in set(apps) if apps.count(a) > 1]
            raise ValueError(f"Duplicate app names in workloads: {duplicates}")
        return self

    @model_validator(mode="after")
    def _check_runtime_models(self) -> "SimulationConfig":
        """
        Validate runtime model configuration:
        1. At least one of runtime_model or runtime_models must be specified
        2. If only runtime_models is used, all apps must be covered
        """
        has_default = self.runtime_model is not None
        has_per_app = len(self.runtime_models) > 0

        # Case 1: Neither specified
        if not has_default and not has_per_app:
            raise ValueError(
                "Runtime model configuration is missing. You must specify either:\n"
                "  - 'runtime_model' (default for all apps), or\n"
                "  - 'runtime_models' (per-app configuration for all apps)"
            )

        # Case 2: Only per-app specified, check all apps are covered
        if not has_default and has_per_app:
            app_names = {wl.app for wl in self.workloads}
            configured_apps = set(self.runtime_models.keys())
            missing_apps = app_names - configured_apps

            if missing_apps:
                raise ValueError(
                    f"Runtime model configuration incomplete. "
                    f"No default 'runtime_model' specified and the following apps "
                    f"are missing from 'runtime_models': {sorted(missing_apps)}\n"
                    f"Either:\n"
                    f"  - Add 'runtime_model' as default configuration, or\n"
                    f"  - Add runtime model configuration for: {', '.join(sorted(missing_apps))}"
                )

        return self

    # Convenience aliases

    @property
    def stop_time(self) -> None | float:
        return self.simulation.stop_time

    @property
    def seed(self) -> int:
        return self.simulation.seed

    @property
    def eager_start(self) -> bool:
        return self.simulation.eager_start

    @property
    def drain(self) -> bool:
        return self.simulation.drain_pending_requests

    @property
    def allocator_interval(self) -> int:
        return self.simulation.allocator_interval
