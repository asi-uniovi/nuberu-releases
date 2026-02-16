"""
Script to generate YAML configuration files for Nuberu simulations using Jinja2 templates.

This script generates a set of configuration files by iterating over a defined parameter space
(workloads, load balancers, queue sizes, termination policies) and rendering a Jinja2 template.
"""

import jinja2
import os
import itertools
import argparse

# Configuration
TEMPLATE_FILE = "scripts/base_template.yaml.j2"
OUTPUT_DIR = "configs"

# Static data
app0_wl = "static"
app1_wl = "unpredictable"
start_hour = 9
pickle_path = (
    f"../example/data/sol_conlloovia_1_hour_a_2_{app0_wl}_{app1_wl}_ts_{start_hour}.p"
)
app0_csv = f"../example/data/wl_{app0_wl}_1s.csv"
app1_csv = f"../example/data/wl_{app1_wl}_1s.csv"
csv_offset = 3600 * start_hour

# Setup Jinja2
template_loader = jinja2.FileSystemLoader(searchpath="./")
template_env = jinja2.Environment(loader=template_loader)
template = template_env.get_template(TEMPLATE_FILE)


def generate_yamls(duration=None):
    """
    Generates YAML configuration files for all combinations of experiment parameters.

    Iterates through the Cartesian product of:
    - Workload configurations (trace, poisson)
    - Load balancers (simple, smoothWRR)
    - Queue sizes (0, 1000)
    - Termination policies (hard, drain)

    Args:
        duration (int, optional): Simulation duration in seconds. If provided, overrides the default
                                  stop_time in the template.
    """
    # Define parameter spaces
    workload_configs = [
        {
            "name": "trace",
            "params": {
                "workload_type": "trace",
                "app_csvs": [app0_csv, app1_csv],
                "csv_offset": csv_offset,
            },
        },
        {
            "name": "poisson",
            "params": {
                "workload_type": "poisson",
                "poisson_reqs": [124427, 362587],
            },
        },
    ]
    load_balancers = [
        {"name": "simple", "config": {}},
        {"name": "smoothWRR", "config": {}},
    ]
    queue_sizes = [0, 1000]
    terminations = [("hard", False), ("drain", True)]
    latencies = [0, 20]

    # Iterate over the Cartesian product of all parameters
    for wl_conf, lb_info, qs, (term_name, drain_bool), latency in itertools.product(
        workload_configs, load_balancers, queue_sizes, terminations, latencies
    ):
        lb_name = lb_info["name"]
        exp_name = f"{wl_conf['name']}_{term_name}_{lb_name}_q{qs}_l{latency}"

        context = {
            "drain_pending_requests": drain_bool,
            "log_file_name": f"log_{exp_name}.log",
            "scenario_name": exp_name,
            "pickle_path": pickle_path,
            "queue_size": qs,
            "load_balancer": lb_name,
            "load_balancer_config": lb_info["config"],
            "num_apps": 2,
            "lb_to_vm_delay": latency,
            "wi_to_lb_delay": latency,
            "vm_container_overhead": int(latency / 20),
            **wl_conf["params"],
        }

        if duration is not None:
            context["stop_time"] = duration

        render_and_save(exp_name, context)


def render_and_save(exp_name, context):
    """
    Renders the Jinja2 template with the given context and saves it to a YAML file.

    Args:
        exp_name (str): Name of the experiment, used for the output filename.
        context (dict): Dictionary containing the variables to be rendered in the template.
    """
    # Ensure output directories exist (metrics, logs, reports)
    for subdir in ["metrics", "logs", "reports"]:
        os.makedirs(subdir, exist_ok=True)

    output = template.render(context)
    filename = f"config_{exp_name}.yaml"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w") as f:
        f.write(output)
    print(f"Generated {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YAML configurations.")
    parser.add_argument(
        "duration", nargs="?", type=int, help="Optional simulation duration in seconds"
    )
    args = parser.parse_args()

    generate_yamls(duration=args.duration)
