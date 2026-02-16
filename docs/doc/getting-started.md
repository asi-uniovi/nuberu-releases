# Getting Started

> Run your first Nuberu simulation in under 10 minutes.

## Prerequisites

- **Python 3.11** or higher
- **[uv](https://docs.astral.sh/uv/)** package manager

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/jldiaz-uniovi/nuberu-monorepo.git
   cd nuberu-monorepo
   ```

2. Install all dependencies:

   ```bash
   uv sync
   ```

   This creates a virtual environment with the Nuberu core and all official plugins installed.

---

## Your First Simulation

### 1. Create a Configuration File

Create a file called `my_first_sim.yaml`:

```yaml
config_version: "3.2"

simulation:
  seed: 42
  stop_time: 60                      # 60 seconds of simulated time
  eager_start: true
  drain_pending_requests: true       # Wait for pending requests to finish

logging:
  log_to_file: false
  log_to_console: true
  level: critical
  component_levels:
    plugins.report_generator: info   # Show the report summary

infrastructure:
  yaml_path: ./examples/simul2026-examples/example/data/infrastructure32.yaml

allocation:
  yaml_path: ./examples/simul2026-examples/example/data/allocations32.yaml

performance_data:
  yaml_path: ./examples/simul2026-examples/example/data/performance_conlloovia_32.yaml

runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 100

load_balancer:
  plugin_name: simple
  plugin_config: {}

workloads:
  - app: app_0
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 1800               # 30 requests/second
        time_slot_size: 60

custom_plugins:
  - plugin_name: report_generator
    plugin_config:
      output_format: "console"
```

> **Note**: Check the `examples/` directory for ready-made configurations with all necessary data files.

### 2. Run the Simulation

```bash
uv run python -m nuberu.cli.main run my_first_sim.yaml
```

### 3. Read the Output

The `report_generator` plugin prints a summary at the end:

```
SIMULATION REPORT (ReportGenerator Plugin)
==================================================
Simulation end time: 60.00s

Request statistics:
  Generated: 1800
  Completed: 1800
  Rejected: 0
  Lost: 0
  Completion rate: 100.00%

Latency statistics (seconds):
  Mean: 0.0234
  Min: 0.0100
  Max: 0.0890
==================================================
```

---

## Adding Metrics Export

To capture detailed metrics for post-hoc analysis, add the `monitor_simple` plugin:

```yaml
custom_plugins:
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/events.jsonl
  
  - plugin_name: report_generator
    plugin_config:
      output_format: "console"
```

Then analyze the results:

```bash
python -m nuberu_plugin_custom_monitor.analyze_metrics ./metrics/events.jsonl
```

This produces detailed statistics including percentiles (p50, p95, p99), per-app breakdowns, and latency decomposition.

---

## Adding Network Latency

Make the simulation more realistic by adding network delays:

```yaml
network_delays:
  wi_to_lb: 10.0                    # 10ms client-to-balancer
  lb_to_vm_default: 5.0             # 5ms balancer-to-VM
  vm_container_overhead: 2.0        # 2ms container startup
```

---

## Using a Different Load Balancer

Switch from simple round-robin to Smooth Weighted Round Robin:

```yaml
load_balancer:
  plugin_name: smoothWRR
  plugin_config: {}
```

This distributes requests proportionally to each container's processing capacity, reducing queue imbalances.

---

## CLI Reference

```bash
# Run a simulation
uv run python -m nuberu.cli.main run config.yaml

# Show help
uv run python -m nuberu.cli.main --help
```

---

## Next Steps

| What You Want | Where to Go |
|---------------|-------------|
| Understand the architecture | [Architecture Overview](./concepts/architecture-overview.md) |
| Learn about request flow | [Request Lifecycle](./concepts/request-lifecycle.md) |
| Configure network latency | [Channels and Latency](./concepts/channels-and-latency.md) |
| Full YAML reference | [Configuration Reference](./configuration-reference.md) |
| Create your own plugin | [Writing Plugins](./guides/writing-plugins.md) |
| Analyze simulation output | [Analyzing Results](./guides/analyzing-results.md) |
| Contribute to the project | [Contributing](./contributing.md) |
