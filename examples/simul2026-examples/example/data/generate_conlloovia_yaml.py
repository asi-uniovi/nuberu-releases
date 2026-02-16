#!/usr/bin/env python3
"""
generate_conlloovia_yaml.py

Read a Solution object from a pickle, print details with Rich,
and optionally export the infrastructure to a YAML file.
"""

import sys
import pickle
import yaml
import numpy as np
import pandas as pd

# Monkey-patch NumPy to provide cumproduct for Pint’s numpy facet
if not hasattr(np, "cumproduct"):
    np.cumproduct = np.cumprod

from cloudmodel.unified.units import ureg
from conlloovia import Allocation, Solution, System
from pint import set_application_registry, Quantity
from rich.console import Console
from rich.table import Table
from rich.text import Text

# register pint's unit registry
set_application_registry(ureg)
console = Console(record=True)


def print_summary_table(solution: Solution) -> None:
    """Prints a summary table with VM, container, app, and instance class counts."""
    total_vms = len(solution.alloc.vms) if hasattr(solution.alloc, "vms") else 0
    active_vms = sum(1 for allocated in solution.alloc.vms.values() if allocated)
    total_containers = (
        len(solution.alloc.containers) if hasattr(solution.alloc, "containers") else 0
    )
    active_containers = sum(
        count for count in solution.alloc.containers.values() if count > 0
    )
    apps_count = (
        len(solution.problem.system.apps)
        if hasattr(solution.problem.system, "apps")
        else 0
    )
    instance_classes_count = (
        len(solution.problem.system.ics)
        if hasattr(solution.problem.system, "ics")
        else 0
    )
    container_classes_count = (
        len(solution.problem.system.ccs)
        if hasattr(solution.problem.system, "ccs")
        else 0
    )

    table = Table(title="Summary Table", show_header=True, header_style="bold magenta")
    table.add_column("Resource", justify="left", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="bold yellow")

    table.add_row("Virtual Machines", f"{active_vms}/{total_vms} active")
    table.add_row("Containers", f"{active_containers}/{total_containers} active")
    table.add_row("Applications", str(apps_count))
    table.add_row("Instance Classes", str(instance_classes_count))
    table.add_row("Container Classes", str(container_classes_count))

    console.print(table)


def print_problem(problem: System) -> None:
    """Prints details of the Problem object."""
    console.print(Text("\nProblem details:", style="bold green"))
    console.print(f"  [bold]Scheduling Time Size:[/bold] {problem.sched_time_size}")
    console.print("  Applications:")
    for app in problem.system.apps:
        console.print(f"    - {app.name}", style="cyan")
    console.print("  Instance Classes:")
    for ic in problem.system.ics:
        console.print(
            f"    - {ic.name}: {ic.cores} cores, {ic.mem} memory, Price: {ic.price}",
            style="yellow",
        )
    console.print("  Container Classes:")
    for cc in problem.system.ccs:
        console.print(
            f"    - {cc.name}: {cc.cores} cores, {cc.mem} memory, App: {cc.app.name}",
            style="yellow",
        )
    console.print("  Workloads:")
    for app, workload in problem.workloads.items():
        console.print(
            f"    - {app.name}: {workload.num_reqs} requests in {workload.time_slot_size}",
            style="blue",
        )
    console.print(f"  [bold]Number of x variables:[/bold] {problem.num_vars_x()}")
    console.print(f"  [bold]Number of z variables:[/bold] {problem.num_vars_z()}")


def print_system_performance(system: System) -> None:
    """Prints the performance values for each InstanceClass-ContainerClass pair."""
    console.print(Text("\nSystem Performance:", style="bold green"))
    for (ic, cc), perf in system.perfs.items():
        console.print(
            f"  - {ic.name} + {cc.name}: {perf} requests per time unit", style="cyan"
        )


def print_allocation(allocation: Allocation) -> None:
    """Prints details of the Allocation object, separating active and inactive VMs and containers."""
    console.print(Text("\nAllocation details:", style="bold green"))
    console.print("  [bold]Virtual Machines:[/bold]")
    active_vms = [vm for vm, allocated in allocation.vms.items() if allocated]
    inactive_vms = [vm for vm, allocated in allocation.vms.items() if not allocated]
    for vm in active_vms:
        console.print(
            f"    - {vm.name()}: [bold green]Active[/bold green] ({vm.ic.cores} cores, {vm.ic.mem} memory)"
        )
    for vm in inactive_vms:
        console.print(f"    - {vm.name()}: [bold red]Inactive[/bold red]")

    console.print("  [bold]Containers:[/bold]")
    active_containers = [
        (container, count)
        for container, count in allocation.containers.items()
        if count > 0
    ]
    inactive_containers = [
        (container, count)
        for container, count in allocation.containers.items()
        if count == 0
    ]
    for container, count in active_containers:
        console.print(
            f"    - {container.name()}: {count} replicas on VM {container.vm.name()} "
            f"({container.cc.cores} cores, {container.cc.mem} memory)",
            style="green",
        )
    for container, count in inactive_containers:
        console.print(
            f"    - {container.name()}: {count} replicas (inactive)", style="red"
        )


def print_solving_stats(stats) -> None:
    """Prints details of the SolvingStats object."""
    console.print(Text("\nSolving Statistics:", style="bold green"))
    console.print(f"  [bold]Fractional Gap:[/bold] {stats.frac_gap}")
    console.print(f"  [bold]Max Seconds:[/bold] {stats.max_seconds}")
    console.print(f"  [bold]Lower Bound:[/bold] {stats.lower_bound}")
    console.print(f"  [bold]Creation Time:[/bold] {stats.creation_time}")
    console.print(f"  [bold]Solving Time:[/bold] {stats.solving_time}")
    console.print(f"  [bold]Status:[/bold] {stats.status.name}", style="bold magenta")


def validate_solution(solution: Solution) -> None:
    """Performs consistency checks on the Solution object."""
    console.print(Text("\nValidating Solution Integrity:", style="bold magenta"))
    for container in solution.alloc.containers.keys():
        if container.vm not in solution.alloc.vms:
            console.print(
                f"  [bold red]ERROR:[/bold red] Container {container.name()} "
                "is not assigned to a valid VM!",
                style="bold red",
            )
    console.print("[bold green]Validation complete![/bold green]")


def print_solution(solution: Solution) -> None:
    """Prints the main attributes of the Solution object."""
    console.print(Text("\nSolution object:", style="bold blue"))
    print_summary_table(solution)
    # print_problem(solution.problem)
    # print_system_performance(solution.problem.system)
    # print_allocation(solution.alloc)
    console.print(
        f"\n[bold]Total Cost:[/bold] {solution.cost.to('usd')}", style="bold yellow"
    )
    print_solving_stats(solution.solving_stats)
    validate_solution(solution)


def export_to_yaml(solution: Solution, output_path: str) -> None:
    """
    Extract from the Solution object and write the infrastructure
    into a YAML that the framework consumes, converting all Quantity fields.
    """
    system: System = solution.problem.system
    alloc: Allocation = solution.alloc

    yaml_dict = {
        "infrastructure": {
            "instance_classes": [],
            "container_classes": [],
            "vms": [],
            "containers": [],
            "performance_data": [],
        }
    }

    def to_number(x):
        return x.magnitude if isinstance(x, Quantity) else x

    # instance classes
    for ic in system.ics:
        yaml_dict["infrastructure"]["instance_classes"].append(
            {
                "name": ic.name,
                "cores": to_number(ic.cores),
                "mem": to_number(ic.mem),
                "price": to_number(ic.price),
                "limit": to_number(getattr(ic, "limit", None)),
            }
        )

    # container classes
    for cc in system.ccs:
        yaml_dict["infrastructure"]["container_classes"].append(
            {
                "name": cc.name,
                "cores": to_number(cc.cores),
                "mem": to_number(cc.mem),
                "app": cc.app.name,
            }
        )

    # vms: only the active VMs (allocated == True)
    for vm_obj, allocated in alloc.vms.items():
        if not allocated:
            continue
        yaml_dict["infrastructure"]["vms"].append(
            {"id": vm_obj.name(), "instance_class": vm_obj.ic.name}
        )

    # containers: only containers with replicas > 0
    for cont_obj, replicas in alloc.containers.items():
        if replicas <= 0:
            continue
        yaml_dict["infrastructure"]["containers"].append(
            {
                "id": cont_obj.name(),
                "vm": cont_obj.vm.name(),
                "class": cont_obj.cc.name,
                "image": getattr(cont_obj, "image", "unknown"),
                "replicas": int(replicas),  # forzamos a entero
            }
        )

    # performance data (requests/hour -> divide by 3600)
    for (ic_obj, cc_obj), perf in system.perfs.items():
        raw = to_number(perf)
        yaml_dict["infrastructure"]["performance_data"].append(
            {"instance": ic_obj.name, "container": cc_obj.name, "rps": raw / 3600.0}
        )

    # write YAML
    with open(output_path, "w") as f:
        yaml.safe_dump(
            yaml_dict, f, default_flow_style=False, sort_keys=False, indent=4
        )


def validate_yaml(path: str) -> tuple[pd.DataFrame, list]:
    """
    Load a YAML file at `path` and validate its structure against the expected schema.
    Returns a tuple (summary_df, errors) where:
      - summary_df is a DataFrame with the count of items in each section
      - errors is a list of validation error messages
    """
    errors = []

    # Load YAML
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    # Check root key
    infra = data.get("infrastructure")
    if infra is None:
        errors.append("Missing 'infrastructure' root key")
        summary_df = pd.DataFrame({"section": ["infrastructure"], "count": [0]})
        return summary_df, errors

    # Expected sections
    sections = [
        "instance_classes",
        "container_classes",
        "vms",
        "containers",
        "performance_data",
    ]
    summary = {}

    # Validate each section exists and is a list
    for sec in sections:
        val = infra.get(sec)
        if val is None:
            errors.append(f"Missing section '{sec}'")
            summary[sec] = 0
        elif not isinstance(val, list):
            errors.append(f"Section '{sec}' is not a list")
            summary[sec] = None
        else:
            summary[sec] = len(val)

    # Required fields per section
    required_fields = {
        "instance_classes": ["name", "cores", "mem", "price", "limit"],
        "container_classes": ["name", "cores", "mem", "app"],
        "vms": ["id", "instance_class"],
        "containers": ["id", "vm", "class", "image", "replicas"],
        "performance_data": ["instance", "container", "rps"],
    }

    # Validate each item has required keys
    for sec, fields in required_fields.items():
        items = infra.get(sec, [])
        if isinstance(items, list):
            for idx, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    errors.append(f"Item {idx} in '{sec}' is not a dict")
                    continue
                for field in fields:
                    if field not in item:
                        errors.append(
                            f"Missing field '{field}' in item {idx} of '{sec}'"
                        )

    # Compute vms_used & containers_used
    containers = infra.get("containers", [])
    df_cont = pd.DataFrame(containers)
    n_containers = len(df_cont)
    containers_used = int(df_cont["replicas"].sum())
    vms_used = len(
        {
            c.get("vm")
            for c in containers
            if isinstance(c, dict) and c.get("replicas", 0) > 0
        }
    )

    # Compute apps count
    container_classes = infra.get("container_classes", [])
    apps_count = len(
        {
            cc.get("app")
            for cc in container_classes
            if isinstance(cc, dict) and "app" in cc
        }
    )

    # Build ordered summary rows
    rows = [
        {"section": "instance_classes", "count": summary["instance_classes"]},
        {"section": "container_classes", "count": summary["container_classes"]},
        {"section": "apps", "count": apps_count},
        {"section": "vms", "count": summary["vms"]},
        {"section": "vms_used", "count": vms_used},
        {"section": "containers", "count": n_containers},
        {"section": "containers_used (with repl)", "count": containers_used},
        {"section": "performance_data", "count": summary["performance_data"]},
    ]

    summary_df = pd.DataFrame(rows)
    return summary_df, errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_conlloovia_yaml.py <input_pickle> [output_yaml]")
        sys.exit(1)

    pickle_path = sys.argv[1]
    output_yaml = sys.argv[2] if len(sys.argv) >= 3 else None

    with open(pickle_path, "rb") as file:
        solution = pickle.load(file)

    if not isinstance(solution, Solution):
        print("The loaded object is not of type 'Solution'.")
        sys.exit(1)

    print_solution(solution)

    # output_yaml = ".\example\example32.yaml"
    if output_yaml:
        console.print("\n[bold blue] Generating YAML for nuberu... [/bold blue]")
        export_to_yaml(solution, output_yaml)
        console.print(f"[bold green]YAML file generated at: {output_yaml}[/bold green]")

        console.print("\n[bold blue] Validating YAML structure... [/bold blue]")
        summary_df, errors = validate_yaml(output_yaml)

        if errors:
            for err in errors:
                console.print(f"[bold red]Error: {err}[/bold red]")
        console.print(
            f"[bold green]YAML validation complete![/bold green] "
            f"\nSummary:\n{summary_df.to_string(index=False)}"
        )


if __name__ == "__main__":
    main()
