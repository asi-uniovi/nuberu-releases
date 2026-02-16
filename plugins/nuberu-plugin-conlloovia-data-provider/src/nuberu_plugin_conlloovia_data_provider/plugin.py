import logging
import pickle
from pathlib import Path
from typing import Any, Callable, Iterable

import pluggy

from nuberu import App, ContainerClass, InstanceClass
from nuberu.plugins import PluginBase

# Suppress pint redefinition warnings before importing cloudmodel
logging.getLogger("pint.util").setLevel(logging.ERROR)

# Set the application registry for the Pint library
from cloudmodel.unified.units import ureg
from pint import set_application_registry
import pint

# Only set registry if not already configured (avoid redefinition warnings)
try:
    current_registry = pint.get_application_registry()
    if current_registry is not ureg:
        set_application_registry(ureg)
except Exception:
    set_application_registry(ureg)

hookimpl = pluggy.HookimplMarker("nuberu")


class ConllooviaDataProvider(PluginBase):
    """
    Plugin that loads Allocations from a pickle file.
    It extracts VM and container assignments for the first time window (1 hour).
    """

    # Define plugin name for hierarchical logging (prefix "nuberu.plugins." is added automatically)
    plugin_name = "conlloovia_data_provider"

    instance_classes: dict[str, InstanceClass]
    container_classes: dict[str, ContainerClass]
    apps: dict[str, App]
    queue_size: int

    def __init__(self):
        """
        Initialize the plugin.
        """
        super().__init__()  # Initialize PluginBase (sets up self.logger)
        self._cache: dict[str, Any] = {}
        self._rps_cache: dict[tuple[str, float, str], float] = {}
        self.queue_size = 1

    def _load_pickle(self, pickle_path: Path) -> None:
        if "_system" in self._cache:
            return
        if not pickle_path.exists():
            raise FileNotFoundError(f"Pickle file not found: {pickle_path}")
        with open(pickle_path, "rb") as f:
            solution = pickle.load(f)

        system = solution.problem.system

        self._cache["_pickle_path"] = pickle_path
        self._cache["_solution"] = solution
        self._cache["_system"] = system

    def _build_raw_infrastructure(
        self,
    ) -> tuple[list[App], list[InstanceClass], list[ContainerClass]]:
        """
        Loads InstanceClass, ContainerClass, and App objects from the System.

        Returns:
            tuple[list[App], list[InstanceClass], list[ContainerClass]]: A tuple containing lists of App, InstanceClass, and ContainerClass objects.
        """
        system = self._cache["_system"]

        # Load Applications
        self.apps = {app.name: App(name=app.name) for app in system.apps}

        # Load Instance Classes
        self.instance_classes = {
            ic.name: InstanceClass(
                name=ic.name,
                cores=strip_units(ic.cores),
                mem=strip_units(ic.mem),
                price=strip_units(ic.price),
                limit=ic.limit if hasattr(ic, "limit") else 10,
            )
            for ic in system.ics
        }

        # Load Container Classes
        self.container_classes = {
            cc.name: ContainerClass(
                name=cc.name,
                cores=strip_units(cc.cores),
                mem=strip_units(cc.mem),
                app=self.apps[cc.app.name],
            )
            for cc in system.ccs
        }
        self.logger.debug(f"Instance_classes: {self.instance_classes}")
        self.logger.debug(f"Container_classes: {self.container_classes}")
        self.logger.info(
            f"Built infrastructure: {len(self.apps)} apps, "
            f"{len(self.instance_classes)} instance_classes, "
            f"{len(self.container_classes)} container_classes"
        )
        return (
            list(self.apps.values()),
            list(self.instance_classes.values()),
            list(self.container_classes.values()),
        )

    def _process_solution(self, solution) -> list[dict]:
        """
        From the 'solution' object from Conlloovia, builds the list of instructions
        for the Nuberu YAML:
          - 'start_vm' only for active VMs.
          - 'create_container' for each replica of each container with replicas > 0,
            adding suffix '-i' to the container_id.

        Args:
            solution: The Solution object loaded from the pickle file.

        Returns:
            list[dict]: A list of formatted instructions.
        """
        instructions: list[dict] = []

        # Process VM assignments
        for vm, is_active in solution.alloc.vms.items():
            if not is_active:
                continue

            action = "start_vm"
            instance_class_obj = self.instance_classes.get(vm.ic.name)

            if not instance_class_obj:
                raise ValueError(f"Instance class {vm.ic.name} not found.")

            instructions.append(
                {
                    "action": action,
                    "data": {
                        "vm_id": vm.name(),
                        "instance_class": instance_class_obj,
                    },
                }
            )

        for container, replicas in solution.alloc.containers.items():
            if replicas <= 0:
                continue

            cc_name = container.cc.name
            if cc_name not in self.container_classes:
                raise ValueError(f"Container class '{cc_name}' not found.")

            container_class_obj = self.container_classes[cc_name]
            base_container_id = container.name()  # ej. "frontend" o "db"

            # The target VM must come from container_obj.vm.name()
            target_vm_id = container.vm.name()

            # For each replica, generate an instruction with suffix "-i"
            for i in range(int(replicas)):
                if replicas == 1:
                    cid = base_container_id
                else:
                    cid = f"{base_container_id}-{i}"

                instructions.append(
                    {
                        "action": "create_container",
                        "data": {
                            "container_id": cid,
                            "container_class": container_class_obj,
                            "vm_id": target_vm_id,
                            "image_name": (
                                container.image
                                if hasattr(container, "image")
                                else "default_image"
                            ),
                            "queue_size": self.queue_size,
                        },
                    }
                )
        return instructions

    @hookimpl
    def get_infrastructure_factory(
        self, config: dict[str, Any]
    ) -> Callable[[], tuple[list[App], list[InstanceClass], list[ContainerClass]]]:
        """Return factory for apps/ICs/CCs from Conlloovia pickle."""
        pickle_path = Path(config["pickle_path"])

        def get_infrastructure() -> tuple[
            list[App], list[InstanceClass], list[ContainerClass]
        ]:
            self._load_pickle(pickle_path)
            if "infra" not in self._cache:
                self._cache["infra"] = self._build_raw_infrastructure()
            self.logger.debug(
                f"Returning cached infrastructure data: {self._cache['infra']}"
            )
            return self._cache["infra"]

        return get_infrastructure

    @hookimpl
    def get_rps_for_app_factory(
        self, config: dict[str, Any]
    ) -> Callable[[App, float, InstanceClass], float]:
        """Return factory for getting RPS for a specific app, instance class, and cores."""
        pickle_path = Path(config["pickle_path"])

        def get_rps_for_app(
            app: App,
            cores: float,
            instance_class: InstanceClass,
        ) -> float:
            key = (app.name, cores, instance_class.name)
            # Check if the RPS is already cached
            if key in self._rps_cache:
                return self._rps_cache[key]

            self._load_pickle(pickle_path)
            system = self._cache["_system"]
            # Search for a combination (ic, cc) with that app and cores
            for (ic, cc), perf_value in system.perfs.items():
                if (
                    ic.name == instance_class.name
                    and cc.app.name == app.name
                    and float(cc.cores.to("cores").magnitude) == float(cores)
                ):
                    if hasattr(perf_value, "to"):
                        return float(perf_value.to("req/second").magnitude)
                    else:
                        return float(perf_value)

            raise ValueError(
                f"No RPS found for App={app.name}, IC={instance_class.name}, cores={cores}. "
                f"Available combinations: "
                f"{[(ic.name, cc.name, cc.app.name, float(cc.cores.to('cores').magnitude)) for (ic, cc) in system.perfs]}"
            )

        return get_rps_for_app

    @hookimpl
    def get_allocations_factory(
        self, config: dict[str, Any]
    ) -> Callable[
        [dict[str, InstanceClass], dict[str, ContainerClass]], Iterable[list[dict]]
    ]:
        """Return factory for allocations for the first time window.
        Args:
            config (dict): Configuration dictionary containing the path to the pickle file.
        Returns:
            Callable that takes instance_classes and container_classes and returns instructions.

        config arg must contain:
            - pickle_path: Path to the pickle file containing the solution.
        """
        pickle_path = Path(config["pickle_path"])
        queue_size = config.get("queue_size", 1)

        def get_allocations(
            instance_classes: dict[str, InstanceClass],
            container_classes: dict[str, ContainerClass],
        ) -> Iterable[list[dict]]:
            self._load_pickle(pickle_path)
            solution = self._cache["_solution"]

            instructions: list[dict[str, dict]] = []

            # Process VM assignments
            for vm, is_active in solution.alloc.vms.items():
                if not is_active:
                    continue

                action = "start_vm"
                instance_class_obj = instance_classes.get(vm.ic.name)

                if not instance_class_obj:
                    raise ValueError(f"Instance class {vm.ic.name} not found.")

                instructions.append(
                    {
                        "action": action,
                        "data": {
                            "vm_id": vm.name(),
                            "instance_class": instance_class_obj,
                        },
                    }
                )

            for container, replicas in solution.alloc.containers.items():
                if replicas <= 0:
                    continue

                cc_name = container.cc.name
                if cc_name not in container_classes:
                    raise ValueError(f"Container class '{cc_name}' not found.")

                container_class_obj = container_classes[cc_name]
                base_container_id = container.name()  # ej. "frontend" o "db"

                # The target VM must come from container_obj.vm.name()
                target_vm_id = container.vm.name()

                # For each replica, generate an instruction with suffix "-i"
                for i in range(int(replicas)):
                    if replicas == 1:
                        cid = base_container_id
                    else:
                        cid = f"{base_container_id}-{i}"

                    instructions.append(
                        {
                            "action": "create_container",
                            "data": {
                                "container_id": cid,
                                "container_class": container_class_obj,
                                "vm_id": target_vm_id,
                                "image_name": (
                                    container.image
                                    if hasattr(container, "image")
                                    else "default_image"
                                ),
                                "queue_size": queue_size,
                            },
                        }
                    )
            self.logger.debug(f"Generated {len(instructions)} instructions")
            # Send the allocations as a list of instructions
            return [instructions]

        return get_allocations

    @hookimpl
    def get_distribution_params_for_app_factory(
        self, config: dict[str, Any]
    ) -> Callable[[str], dict[str, int]]:
        """
        Return factory for distribution params {"num_reqs": N, "time_slot_size": S} for a given app,
        reading from the pickle.
        """
        pickle_path = Path(config["pickle_path"])

        def get_distribution_params_for_app(app_name: str) -> dict[str, int]:
            self._load_pickle(pickle_path)

            # Search for the app by name
            solution = self._cache["_solution"]

            if not hasattr(solution, "problem") or not hasattr(
                solution.problem, "workloads"
            ):
                raise ValueError(
                    "Invalid pickle format: missing 'problem.workloads' attribute."
                )

            for app_obj, raw_workload in solution.problem.workloads.items():
                if app_obj.name == app_name:
                    return {
                        "num_reqs": int(raw_workload.num_reqs.to("req").magnitude),
                        "time_slot_size": int(
                            raw_workload.time_slot_size.to("seconds").magnitude
                        ),
                    }

            raise ValueError(
                f"No workload data for app '{app_name}'. "
                f"Available: {[a.name for a in solution.problem.workloads]}"
            )

        return get_distribution_params_for_app

    def __repr__(self):
        return "ConllooviaDataProvider (Conlloovia Pickle-based Data Provider)"


def strip_units(obj: object, target_unit: None | str = None) -> object | float:
    """
    Strip units from a given object.
    If the object has a 'magnitude' attribute, return its float value.
    Otherwise, return the object itself.

    Args:
        obj (object): The object to process.
        target_unit (str, optional): The unit to convert to, if applicable.

    Returns:
        object | float: The stripped object or its float value.
    """
    if hasattr(obj, "magnitude"):
        if target_unit is not None and hasattr(obj, "to"):
            return float(obj.to(target_unit).magnitude)
        else:
            return float(obj.magnitude)
    return obj
