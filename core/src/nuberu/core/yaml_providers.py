from pathlib import Path
from typing import Tuple

import yaml
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, ValidationError

from .infrastructure import App, ContainerClass, InstanceClass


# --------------------------------------------------------------------------- #
# 1.  Pydantic schemas  (only for validation)
# --------------------------------------------------------------------------- #
class _InstanceClassCfg(BaseModel):
    name: str
    cores: PositiveFloat
    mem: PositiveFloat
    price: PositiveFloat
    limit: PositiveInt


class _ContainerClassCfg(BaseModel):
    name: str
    cores: PositiveFloat
    mem: PositiveFloat
    app: str


class _InfrastructureFile(BaseModel):
    infrastructure: dict = Field(..., validation_alias="infrastructure")

    # deep-validate inner lists
    def model_post_init(self, _ctx):
        ic_list = self.infrastructure.get("instance_classes", [])
        cc_list = self.infrastructure.get("container_classes", [])
        [_InstanceClassCfg(**ic) for ic in ic_list]
        [_ContainerClassCfg(**cc) for cc in cc_list]


class _PerformanceEntry(BaseModel):
    cores: PositiveFloat
    rps: PositiveFloat


# The final structure is:
# Dict[str, Dict[str, List[_PerformanceEntry]]]
# app_name -> instance_class -> list of entries

# Each instance_class maps to a list of entries (cores -> rps)
_PerformancePerInstance = dict[str, list[_PerformanceEntry]]

# Each app maps to a dictionary of instance_classes -> performance entries
_PerformanceTable = dict[str, _PerformancePerInstance]


class _AllocVm(BaseModel):
    id: str
    instance_class: str


class _AllocContainer(BaseModel):
    id: str
    vm: str
    class_: str = Field(..., alias="class")
    image: str = "unknown"
    replicas: PositiveInt = 1


class _AllocationsFile(BaseModel):
    allocations: dict

    def model_post_init(self, _ctx):
        vms = self.allocations.get("vms", [])
        containers = self.allocations.get("containers", [])
        [_AllocVm(**vm) for vm in vms]
        [_AllocContainer(**ctr) for ctr in containers]


# --------------------------------------------------------------------------- #
# 2.  Public helpers
# --------------------------------------------------------------------------- #
def load_infrastructure_yaml(
    path: str | Path,
) -> Tuple[list[App], list[InstanceClass], list[ContainerClass]]:
    """
    Validate infrastructure YAML and return canonical objects.
    """
    data = _safe_yaml(path)
    try:
        _InfrastructureFile(**data)
    except ValidationError as exc:
        raise ValueError(f"Infrastructure YAML is invalid:\n{exc}") from None

    infra = data["infrastructure"]

    apps: dict[str, App] = {}
    ics: list[InstanceClass] = []
    ccs: list[ContainerClass] = []

    for raw in infra["instance_classes"]:
        ic = InstanceClass(**raw)
        ics.append(ic)

    for raw in infra["container_classes"]:
        app = apps.setdefault(raw["app"], App(name=raw["app"]))
        cc = ContainerClass(
            name=raw["name"],
            cores=raw["cores"],
            mem=raw["mem"],
            app=app,
        )
        ccs.append(cc)

    return list(apps.values()), ics, ccs


def load_allocations_yaml(
    path: str | Path,
    instance_classes: dict[str, InstanceClass],
    container_classes: dict[str, ContainerClass],
) -> list[list[dict[str, dict]]]:
    """
    Validate allocations YAML and return *one* time-window.

    Returns:
        list[list[dict[str, dict]]]: outer list = windows,
                                     inner list = instructions.
    """
    data = _safe_yaml(path)
    try:
        file = _AllocationsFile(**data)
    except ValidationError as exc:
        raise ValueError(f"Allocations YAML is invalid:\n{exc}") from None

    vms = file.allocations["vms"]
    containers = file.allocations["containers"]

    window: list[dict[str, dict]] = []

    for vm in vms:
        ic_name = vm["instance_class"]
        if ic_name not in instance_classes:
            raise ValueError(f"Unknown InstanceClass '{ic_name}' in allocations YAML")
        window.append(
            {
                "action": "start_vm",
                "data": {
                    "vm_id": vm["id"],
                    "instance_class": instance_classes[ic_name],
                },
            }
        )

    for ctr in containers:
        cc_name = ctr["class"]
        if cc_name not in container_classes:
            raise ValueError(f"Unknown ContainerClass '{cc_name}' in allocations YAML")
        replicas = ctr.get("replicas", 1)
        for i in range(replicas):
            cid = f"{ctr['id']}-{i}" if replicas > 1 else ctr["id"]
            window.append(
                {
                    "action": "create_container",
                    "data": {
                        "container_id": cid,
                        "container_class": container_classes[cc_name],
                        "vm_id": ctr["vm"],
                        "image_name": ctr.get("image", "unknown"),
                    },
                }
            )
    return [window]


def _safe_yaml(path: str | Path) -> dict:
    """Load YAML file safely and always return a dict."""
    with open(Path(path), "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Root element of {path} must be a mapping")
        return data


class YamlPerformanceProvider:
    def __init__(self, path: str | Path) -> None:
        self._path: Path = Path(path)
        self._performance: _PerformanceTable = {}

        try:
            with open(self._path, "r") as f:
                raw = yaml.safe_load(f)

            raw_table: dict = raw[
                "performance"
            ][
                "apps"
            ]  # Performance data structure: performance.apps[app_name][instance_class][entries]
            for app_name, app_data in raw_table.items():
                self._performance[app_name] = {}
                for ic_name, entries in app_data.items():
                    validated_entries = [
                        _PerformanceEntry(**entry) for entry in entries
                    ]
                    self._performance[app_name][ic_name] = validated_entries

        except (KeyError, TypeError, ValidationError) as e:
            raise ValueError(
                f"Performance YAML at '{self._path}' is invalid or malformed:\n{e}"
            ) from e

    def get_rps_for_app(
        self, app: App, cores: float, instance_class: InstanceClass
    ) -> float:
        app_data = self._performance.get(app.name)
        if app_data is None:
            raise ValueError(f"No performance data for app: {app.name}")

        instance_data = app_data.get(instance_class.name)
        if instance_data is None:
            raise ValueError(
                f"No performance data for instance class: {instance_class.name}"
            )

        for entry in instance_data:
            if entry.cores == cores:
                return entry.rps

        raise ValueError(
            f"No RPS entry for {cores} cores in app={app.name}, ic={instance_class.name}"
        )
