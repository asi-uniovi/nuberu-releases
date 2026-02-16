import logging
import pickle
from pathlib import Path
from typing import Any, Callable, Iterable

import pint
import pluggy
from nuberu import App, ContainerClass, InstanceClass
from nuberu.plugins import PluginBase

# Suppress pint redefinition warnings before importing cloudmodel
logging.getLogger("pint.util").setLevel(logging.ERROR)

from fcma.model import Solution, SolutionSummary
from cloudmodel.unified.units import ureg
from pint import UndefinedUnitError, set_application_registry

# set pint registry for cloudmodel (only if not already set to avoid redefinition warnings)
try:
    current_registry = pint.get_application_registry()
    if current_registry is not ureg:
        set_application_registry(ureg)
except Exception:
    set_application_registry(ureg)

hookimpl = pluggy.HookimplMarker("nuberu")


def _to_rps(quantity: Any) -> float:
    """
    Convert a performance quantity to requests per second (req/s),
    with fallback from magnitude per hour if necessary.
    """
    try:
        return quantity.to("req/s").magnitude
    except Exception:
        # fallback if stored as req/hour or raw magnitude
        mag = getattr(quantity, "magnitude", quantity)
        return float(mag) / 3600.0


class DataProviderFromFcma(PluginBase):
    """
    Plugin that adapts an FCMA pickle to the Nuberu DataProvider interface.
    """

    plugin_name = "fcma_data_provider"

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, Any] = {}
        self._rps_cache: dict[str, float] = {}

    def _load_pickle(self, pickle_path: Path) -> None:
        """Load the FCMA Solution from a pickle if not already cached."""
        if "_solution" in self._cache:
            return
        if not pickle_path.exists():
            self.logger.error(f"Pickle file not found: {pickle_path}")
            raise FileNotFoundError(f"Pickle file not found: {pickle_path}")
        with open(pickle_path, "rb") as f:
            solution = pickle.load(f)
        if not isinstance(solution, Solution):
            self.logger.error(f"Expected Solution, got {type(solution).__name__}")
            raise ValueError(f"Expected Solution, got {type(solution).__name__}")
        self._cache["_solution"] = solution
        self.logger.debug(f"Loaded FCMA Solution from {pickle_path}")

    def _prepare_info(self) -> dict[str, Any]:
        """Extract and cache structured info from the FCMA solution."""
        if "info" not in self._cache:
            solution: Solution = self._cache["_solution"]  # type: ignore
            patch_pint_registry()
            set_application_registry(ureg)
            info = self.extract_structured_info(solution)
            self.logger.debug(
                f"Extracted info: "
                f"{len(info.get('instance_classes', []))} instance_classes, "
                f"{len(info.get('vms', []))} vms, "
                f"{len(info.get('containers', []))} containers"
            )
            self._cache["info"] = info
        return self._cache["info"]  # type: ignore

    def extract_structured_info(self, solution):
        """
        Build structured info for:
        - base instance classes (families)
        - container classes
        - actual VM allocations
        - container allocations

        Strategy for base classes:
        1. Each allocated VM has a type like 'm5.4xlarge'.
        2. Split into family 'm5' and size '4xlarge'.
        3. Parse multiplier = number before 'x'.
        4. Divide VM cores, memory, and cost by multiplier to get base 'm5' specs.

        Returns:
        dict {
            'instance_classes': [ {family specs}, ... ],
            'container_classes': [ {container class specs}, ... ],
            'vms': [ {alloc specs}, ... ],
            'containers': [ {container alloc}, ... ]
        }
        """
        info = {
            "instance_classes": [],
            "container_classes": [],
            "vms": [],
            "containers": [],
        }

        # Aggregate VM allocations and keep raw specs
        vm_raw = {}
        alloc = getattr(solution, "allocation", {})

        for vm_list in alloc.values():
            for vm in vm_list:
                ic = vm.ic
                name = getattr(ic, "name", None)
                # Extract numeric specs from InstanceClass
                cores_qty = getattr(ic, "cores", None) or getattr(ic, "cpu", None)
                mem_qty = getattr(ic, "mem", None) or getattr(ic, "memory", None)
                price_qty = getattr(ic, "price", None)

                cores = (
                    cores_qty.to("core").magnitude
                    if hasattr(cores_qty, "to")
                    else float(cores_qty)
                )
                memory = (
                    mem_qty.to("gibibyte").magnitude
                    if hasattr(mem_qty, "to")
                    else float(mem_qty)
                )
                cost = (
                    price_qty.to("usd/hour").magnitude
                    if hasattr(price_qty, "to")
                    else float(price_qty)
                )

                # Initialize or update counts
                entry = vm_raw.get(
                    name,
                    {
                        "vm_type": name,
                        "count": 0,
                        "cores": cores,
                        "memory_gib": memory,
                        "cost_per_hour": cost,
                    },
                )
                entry["count"] += 1
                vm_raw[name] = entry

        # Convert raw map to list
        vms = list(vm_raw.values())
        info["vms"] = vms

        # Derive base instance classes by dividing by multiplier
        family_map = {}
        for vm in vms:
            vm_type = vm["vm_type"]
            # Expect format 'family.multiplierx...' e.g. 'm5.4xlarge'
            if "." not in vm_type:
                continue
            family, size = vm_type.split(".", 1)
            try:
                multiplier = int(size.split("x", 1)[0])
            except ValueError:
                # Skip if cannot parse multiplier
                continue
            # Divide specs by multiplier
            base_cores = vm["cores"] / multiplier
            base_memory = vm["memory_gib"] / multiplier
            base_cost = vm["cost_per_hour"] / multiplier
            # Only record one entry per family
            if family not in family_map:
                family_map[family] = {
                    "family": family,
                    "cores": base_cores,
                    "memory_gib": base_memory,
                    "cost_per_hour": base_cost,
                }

        # Append derived base classes
        info["instance_classes"] = list(family_map.values())

        # Extract container allocations via SolutionSummary
        from fcma.model import SolutionSummary

        summary = SolutionSummary(solution)
        for app_summary in summary.get_all_apps_allocations().values():
            for cg in app_summary.container_groups:
                # Performance in req/s
                try:
                    perf = cg.performance.to("req/s").magnitude
                except Exception:
                    perf = cg.performance.magnitude / 3600.0
                cores = cg.cores.to("core").magnitude

                # cc_key = build_cc_key(cg.container_name, cg.cores)
                info["containers"].append(
                    {
                        "app": cg.app_name,
                        "container_class": cg.container_name,
                        "vm_name": cg.vm_name,
                        "performance_req_per_second": perf,
                        "replicas": cg.replicas,
                        "cores": cores,
                    }
                )

        # --- Container class definitions (from vm.cgs) ---
        seen = set()
        for vm_list in alloc.values():
            for vm in vm_list:
                # vm.cgs is the list of ContainerGroup from FCMA
                for cg in vm.cgs:
                    name = str(cg.cc)
                    # Now we want to save all container classes, even if there are repetitions.
                    seen.add(name)
                    cc = cg.cc  # actual instance of fcma.model.ContainerClass

                    # cores
                    cores = cc.cores.to("core").magnitude

                    # memory: cc.mem can be a tuple or a single Storage
                    mems = cc.mem if isinstance(cc.mem, (tuple, list)) else (cc.mem,)
                    # convert to GiB
                    mem_list = [m.to("gibibyte").magnitude for m in mems]
                    # if only one value, store as float instead of list
                    mem_val = mem_list[0] if len(mem_list) == 1 else mem_list

                    # nominal performance in req/s
                    perf_rph = cc.perf.to("req/hour").magnitude
                    perf_rps = perf_rph / 3600.0

                    # cc_key = build_cc_key(name, cc.cores)
                    info["container_classes"].append(
                        {
                            "container_class": name,
                            "app": cc.app.name,
                            "cores": cores,
                            "memory_gib": mem_val,
                            "performance_rps": perf_rps,
                        }
                    )
                    # self.logger.debug(f"[CC] Added to INFO container class: {name}, cores={cores}, mem={mem_val}, perf={perf}")

        return info

    def _build_infrastructure(
        self,
    ) -> tuple[list[App], list[InstanceClass], list[ContainerClass]]:
        """
        Construct App, InstanceClass, and ContainerClass objects based on cached info.
        """
        info = self._prepare_info()

        apps = {c["app"]: App(name=c["app"]) for c in info["containers"]}

        instance_classes: dict[str, InstanceClass] = {}
        for vm in info.get("vms", []):
            name = vm["vm_type"]
            instance_classes[name] = InstanceClass(
                name=name,
                cores=vm["cores"],
                mem=vm["memory_gib"],
                price=vm["cost_per_hour"],
                limit=vm.get("count", 0),
            )
            self.logger.info(f"[IC] Created InstanceClass: {instance_classes[name]}")

        container_classes: dict[str, ContainerClass] = {}
        # Nota: los containers llegan aquí con 0.0 memory, porque esa es la cantidad utilizada... debemos obtenerlo del IC?
        for c in info.get("container_classes", []):
            self.logger.info(f"[CC] Processing ContainerClass: {c}")
            cc_name = c["container_class"]  # name of the CC
            if cc_name not in container_classes:
                container_classes[cc_name] = ContainerClass(
                    name=cc_name,
                    cores=c.get("cores", 0.0),
                    mem=c.get("memory_gib", c.get("mem", 0.0)),
                    app=apps[c["app"]],
                )
            self.logger.info(
                f"[CC] Created ContainerClass: {container_classes[cc_name]}"
            )

        self.logger.debug(
            f"Built infrastructure: {len(apps)} apps, "
            f"{len(instance_classes)} instance_classes, "
            f"{len(container_classes)} container_classes"
        )
        return (
            list(apps.values()),
            list(instance_classes.values()),
            list(container_classes.values()),
        )

    @hookimpl
    def get_infrastructure_factory(
        self, config: dict[str, Any]
    ) -> Callable[[], tuple[list[App], list[InstanceClass], list[ContainerClass]]]:
        """Return factory for apps, instance classes, and container classes from FCMA pickle."""
        pickle_path = Path(config["pickle_path"])

        def get_infrastructure() -> tuple[
            list[App], list[InstanceClass], list[ContainerClass]
        ]:
            self._load_pickle(pickle_path)
            if "infra" not in self._cache:
                self._cache["infra"] = self._build_infrastructure()
            self.logger.debug(
                f"Returning cached infrastructure data: {self._cache['infra']}"
            )
            return self._cache["infra"]

        return get_infrastructure

    @hookimpl
    def get_rps_for_app_factory(
        self, config: dict[str, Any]
    ) -> Callable[[App, float, InstanceClass], float]:
        """
        Return factory for extracting RPS from FCMA pickle for given app, instance class and core allocation.
        """
        pickle_path = Path(config["pickle_path"])

        def get_rps_for_app(
            app: App,
            cores: float,
            instance_class: InstanceClass,
        ) -> float:
            key = (app.name, cores, instance_class.name)

            if key in self._rps_cache:
                return self._rps_cache[key]

            self._load_pickle(pickle_path)
            solution: Solution = self._cache["_solution"]

            # Use SolutionSummary to get container groups - same as get_allocations
            from fcma.model import SolutionSummary

            summary = SolutionSummary(solution)

            # Search through all app allocations and container groups
            candidates = []  # Store potential matches for debugging
            cores_rounded = round(cores, 5)  # Round to 5 decimal places for consistency

            for app_alloc in summary.get_all_apps_allocations().values():
                for cg in app_alloc.container_groups:  # cg is ContainerGroupSummary
                    ic_name = cg.vm_name.split("[", 1)[0]  # c5.2xlarge[0] -> c5.2xlarge
                    cg_cores = round(
                        cg.cores.to("core").magnitude, 5
                    )  # Round to 5 decimal places

                    # Store candidate for debugging
                    candidates.append((cg.app_name, ic_name, cg_cores))

                    if (
                        cg.app_name == app.name
                        and ic_name == instance_class.name
                        and cg_cores
                        == cores_rounded  # Direct comparison after rounding
                    ):
                        # Convert performance to req/s directly from ContainerGroupSummary
                        perf_rps = cg.performance.to("req/hour").magnitude / 3600.0
                        self._rps_cache[key] = perf_rps
                        self.logger.debug(
                            f"Found RPS for app={app.name}, cores={cores_rounded}, instance={instance_class.name}: {perf_rps:.5f} req/s"
                        )
                        return perf_rps

            # Log available candidates for debugging
            app_candidates = [c for c in candidates if c[0] == app.name]
            instance_candidates = [c for c in candidates if c[1] == instance_class.name]

            # No exact match found - log debug info and return 0
            self.logger.debug(
                f"No RPS found for app={app.name}, cores={cores_rounded}, instance={instance_class.name}. "
                f"Available for this app: {app_candidates[:3]}... "
                f"Available for this instance: {instance_candidates[:3]}... "
                f"Returning RPS=0"
            )

            # Cache the result and return 0
            self._rps_cache[key] = 0.0
            return 0.0

        return get_rps_for_app

    @hookimpl
    def get_allocations_factory(
        self, config: dict[str, Any]
    ) -> Callable[
        [dict[str, InstanceClass], dict[str, ContainerClass]],
        Iterable[list[dict[str, Any]]],
    ]:
        """
        Return factory for VM start and container creation instructions for the first time window.
        """
        pickle_path = Path(config["pickle_path"])
        queue_size = config.get("queue_size", 0)

        def get_allocations(
            instance_classes: dict[str, InstanceClass],
            container_classes: dict[str, ContainerClass],
        ) -> Iterable[list[dict[str, Any]]]:
            self._load_pickle(pickle_path)
            solution: Solution = self._cache["_solution"]  # type: ignore
            summary = SolutionSummary(solution)
            instructions: list[dict[str, Any]] = []

            # start VMs
            for vm_list in solution.allocation.values():
                for vm in vm_list:
                    ic_obj = instance_classes.get(vm.ic.name)
                    if not ic_obj:
                        raise ValueError(f"Instance class {vm.ic.name} not found.")
                    instructions.append(
                        {
                            "action": "start_vm",
                            # vm_id: vm.id, vm_name = str(vm)
                            # The name of the VM is "ic.name" + its ID in FCMA
                            "data": {
                                "vm_id": str(vm),
                                "instance_class": ic_obj,
                                "container_creation_delay": 0,
                            },  # container_creation_delay is not used in nuberu for now
                        }
                    )
                    # Los nombres de las vms siguen el formato: c5.24xlarge[2]
                    # Vm.id es solo lo que entre corchetes, por ejemplo "2" en c5.24xlarge[2]
                    # str(vm) es el nombre completo de la vm en FCMA: # "c5.24xlarge[2]"
                    self.logger.debug(
                        f"vm: {vm}, vm.id: {vm.id}, str(vm): {str(vm)}, ic_obj.name: {ic_obj.name}"
                    )
                    self.logger.debug(
                        f"Generated VM start instruction: {vm} ({ic_obj.name})"
                    )
            self.logger.debug(f"Generated {len(instructions)} VM start instructions")
            total_containers_with_replicas = 0
            # create containers
            for app_alloc in summary.get_all_apps_allocations().values():
                for cg in app_alloc.container_groups:
                    self.logger.debug(f"Processing container group: {cg}")
                    # Nuevo y comento la siguiente cc_obj
                    # cc_key = build_cc_key(cg.container_name, cg.cores)
                    cc_key = cg.container_name
                    cc_obj = container_classes.get(cc_key)

                    # cc_obj = container_classes.get(cg.container_name)
                    if not cc_obj:
                        raise ValueError(f"Container class {cc_key} not found.")
                    self.logger.debug(f"Found container class: {cc_obj.name}")
                    for i in range(int(cg.replicas)):
                        cid = f"{cc_key}-{i}" if cg.replicas > 1 else cc_key
                        instructions.append(
                            {
                                "action": "create_container",
                                "data": {
                                    "container_id": cid,
                                    "container_class": cc_obj,
                                    "vm_id": cg.vm_name,
                                    "queue_size": queue_size,
                                    "image_name": "default",
                                },
                            }
                        )
                    total_containers_with_replicas += cg.replicas

            self.logger.debug(f"Generated {len(instructions)} instructions")
            self.logger.info(
                f"Total containers (with replicas): {total_containers_with_replicas}"
            )
            return [instructions]

        return get_allocations

    @hookimpl
    def get_distribution_params_for_app_factory(
        self, config: dict[str, Any]
    ) -> Callable[[str], dict[str, int]]:
        """
        Return factory for distribution params {"num_reqs": N, "time_slot_size": S} for a given app from FCMA problem.
        """
        pickle_path = Path(config["pickle_path"])

        def get_distribution_params_for_app(app_name: str) -> dict[str, int]:
            self._load_pickle(pickle_path)
            solution: Solution = self._cache["_solution"]  # type: ignore
            if not hasattr(solution, "problem") or not hasattr(
                solution.problem, "workloads"
            ):
                raise ValueError("Missing workloads in FCMA problem.")
            for app_obj, workload in solution.problem.workloads.items():
                if app_obj.name == app_name:
                    num_reqs = (
                        workload.num_reqs.to("req").magnitude
                        if hasattr(workload.num_reqs, "to")
                        else workload.num_reqs
                    )  # type: ignore
                    slot = (
                        workload.time_slot_size.to("seconds").magnitude
                        if hasattr(workload.time_slot_size, "to")
                        else workload.time_slot_size
                    )  # type: ignore
                    self.logger.debug(
                        f"Distribution params for {app_name}: num_reqs={num_reqs}, slot={slot}"
                    )
                    return {"num_reqs": int(num_reqs), "time_slot_size": int(slot)}
            raise ValueError(f"No workload found for app '{app_name}'.")

        return get_distribution_params_for_app


def patch_pint_registry():
    """
    Ensure pint can parse any unit by automatically defining missing ones as dimensionless.
    """
    ureg = pint.get_application_registry()
    orig_parse = ureg.parse_units

    def parse_units_patched(input_string, *args, **kwargs):
        try:
            return orig_parse(input_string, *args, **kwargs)
        except UndefinedUnitError:
            # Check if unit already exists before defining (avoid redefinition warnings)
            try:
                ureg._units.get(input_string)  # Check if unit is registered
            except Exception:
                pass
            else:
                # Unit exists, just try to parse again
                return orig_parse(input_string, *args, **kwargs)

            # Define unknown unit only if it doesn't exist
            ureg.define(f"{input_string} = []")
            return orig_parse(input_string, *args, **kwargs)

    ureg.parse_units = parse_units_patched
    try:
        pint.application_registry.parse_units = parse_units_patched
    except Exception as e:
        logging.warning(f"Failed to patch pint.application_registry.parse_units: {e}")


def build_cc_key(container_name: str, cores_qty) -> str:
    """
    Return a unique key for a container class that includes its size in millicores.

    Example:  app_4-c5_m5_r5 + 1.104 core  ->  app_4-c5_m5_r5-1104mc
    """
    mc = int(cores_qty.to("millicore").magnitude + 0.5)  # redondeo
    return f"{container_name}-{mc}mc"
