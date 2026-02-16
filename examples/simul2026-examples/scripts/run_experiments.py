#!/usr/bin/env python3
import subprocess
from pathlib import Path
import time
import itertools
import argparse
import os
import concurrent.futures

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parent
sim_script = repo_root / "example" / "main.py"
config_dir = repo_root / "configs"
logs_root = repo_root / "logs"

# 1) Define configurations - all 16 paper experiments


def run_experiment(name):
    cfg_file = config_dir / f"config_{name}.yaml"
    cmd = ["uv", "run", "python", str(sim_script), str(cfg_file)]

    # Executed in a separate process
    p = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(repo_root),
        check=False,
    )
    return name, p.returncode, p.stderr


# 1) Parse command line arguments
parser = argparse.ArgumentParser(description="Run Nuberu experiments.")
parser.add_argument(
    "--workloads",
    nargs="+",
    default=["poisson", "trace"],
    help="Workloads to run (default: poisson trace)",
)
parser.add_argument(
    "--stops",
    nargs="+",
    default=["drain", "hard"],
    help="Stop strategies to run (default: drain hard)",
)
parser.add_argument(
    "--lbs",
    nargs="+",
    default=["simple", "smoothWRR"],
    help="Load balancers to run (default: simple smoothWRR)",
)
parser.add_argument(
    "--qs",
    nargs="+",
    default=["0", "1000"],
    help="Queue sizes to run (default: 0 1000)",
)
parser.add_argument(
    "--ls",
    nargs="+",
    default=["0", "20"],
    help="Latencies to run (default: 0 20)",
)
parser.add_argument(
    "--jobs",
    "-j",
    type=int,
    default=os.cpu_count(),
    help="Number of parallel jobs (default: CPUs)",
)

args = parser.parse_args()

workloads = args.workloads
stops = args.stops
lbs = args.lbs
qs = args.qs
ls = args.ls

experiments = [
    f"{wl}_{st}_{lb}_q{q}_l{lat}"
    for wl, st, lb, q, lat in itertools.product(workloads, stops, lbs, qs, ls)
]
#     # Poisson workload
#     "poisson_drain_simple_q0",
#     "poisson_drain_simple_q1000",
#     "poisson_drain_smoothWRR_q0",
#     "poisson_drain_smoothWRR_q1000",
#     "poisson_hard_simple_q0",
#     "poisson_hard_simple_q1000",
#     "poisson_hard_smoothWRR_q0",
#     "poisson_hard_smoothWRR_q1000",
#     # Trace workload
#     "trace_drain_simple_q0",
#     "trace_drain_simple_q1000",
#     "trace_drain_smoothWRR_q0",
#     "trace_drain_smoothWRR_q1000",
#     "trace_hard_simple_q0",
#     "trace_hard_simple_q1000",
#     "trace_hard_smoothWRR_q0",
#     "trace_hard_smoothWRR_q1000",
# ]

# 2) Executuion
start_time = time.time()
errors = []

max_workers = args.jobs
if not max_workers:
    max_workers = 1

print(f"\nRunning {len(experiments)} experiments with pool size {max_workers}...")

with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
    # Submit all experiments
    future_to_exp = {
        executor.submit(run_experiment, name): name for name in experiments
    }

    for future in concurrent.futures.as_completed(future_to_exp):
        name = future_to_exp[future]
        try:
            exp_name, retcode, stderr = future.result()
            if retcode != 0:
                print(
                    f"[ERROR] '{exp_name}' terminó con código {retcode}. Ver log en {logs_root / exp_name}"
                )
                print(stderr.decode("utf8"))
                errors.append(exp_name)
            else:
                print(f"Finished: {exp_name}")
        except Exception as exc:
            print(f"{name} generated an exception: {exc}")
            errors.append(name)
if not errors:
    end_time = time.time()
    elapsed_time = end_time - start_time
    mins, secs = divmod(int(elapsed_time), 60)
    print("\nAll simulations completed.")
    print(f"Total time for all experiments: {mins} mins {secs} seconds")
    print(f"Logs saved in: {logs_root}")
else:
    print("\nSome simulations failed.")
    print(f"Failed experiments: {errors}")
    # return exit code 1 to indicate failure
    exit(1)
