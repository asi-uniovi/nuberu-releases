# Nuberu Core

Nuberu is an event-driven cloud simulation engine powered by **aSimPy**, a modified version of SimPy. It models cloud infrastructure components including virtual machines (VMs), containers, load balancers, and performance monitoring to enable realistic cloud environment simulations.

## Features

- **Event-driven simulation** - Discrete event simulation of cloud workloads
- **Resource management** - CPU and memory modeling for VMs and containers
- **Flexible load balancing** - Support for multiple load balancing strategies
- **Plugin architecture** - Extensible design for custom components
- **Comprehensive monitoring** - Detailed metrics collection and export
- **Configuration-driven** - YAML-based configuration for easy experimentation

---

## Installation

From the monorepo root:

```bash
# Install uv if you don't have it
# See https://docs.astral.sh/uv/#getting-started

# Install dependencies
uv sync
```

To run Python scripts, use either:
```bash
# Option 1: Run directly with uv
uv run python script.py

# Option 2: Activate the virtual environment
source .venv/bin/activate
python script.py
```

---

## Project Structure
```
./
├── README.md
├── pyproject.toml
├── uv.lock
├── src/nuberu/
│   ├── __init__.py
│   ├── channels/
│   │   ├── channel.py
│   │   ├── duplex_channel.py
│   │   └── multi_channel_receiver.py
│   ├── cli/
│   │   └── main.py
│   ├── components/
│   │   ├── allocator.py
│   │   ├── container.py
│   │   ├── infrastructure_manager.py
│   │   ├── registry.py
│   │   └── vm.py
│   ├── core/
│   │   ├── events.py
│   │   ├── infrastructure.py
│   │   ├── network_delays.py
│   │   ├── setup_logging.py
│   │   ├── simulation.py
│   │   ├── simulation_builder.py
│   │   ├── simulation_config.py
│   │   ├── states.py
│   │   └── yaml_providers.py
│   ├── interfaces/
│   │   └── protocols.py
│   ├── plugins/
│   │   ├── base.py
│   │   ├── hookspecs.py
│   │   └── plugin_manager.py
│   ├── utils/
│   │   └── helpers.py
│   └── workload/
│       ├── request.py
│       ├── timeline.py
│       └── workload_injector.py
└── tests/
    └── ...
```

---

## Quick Example

Here's a minimal configuration to get started. Create a file named `config.yaml`:

```yaml
config_version: '3.2'

simulation:
  seed: 12345              # Random seed for reproducibility
  stop_time: 60            # Simulation time in seconds
  eager_start: true        # Start infrastructure immediately
  drain_pending_requests: true

logging:
  log_to_file: true
  level: INFO              # DEBUG, INFO, WARNING, ERROR
  output_path: ./logs/
  log_file_name: simulation.log

custom_plugins:
  - plugin_name: monitor_simple
    plugin_config:
      output_path: ./metrics/events.jsonl
  - plugin_name: report_generator
    plugin_config:
      output_path: ./metrics/summary.json

infrastructure:
  yaml_path: ./infrastructure.yaml

runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 0          # 0 for no queue, >0 to buffer requests

performance_data:
  yaml_path: ./performance_data.yaml

allocation:
  yaml_path: ./allocations.yaml

load_balancer:
  plugin_name: simple      # Round-robin load balancing

workloads:
  - app: app_0
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100      # Total requests
        time_slot_size: 60 # Distributed over 60 seconds

cost_models:
  - plugin_name: spot
    plugin_config:
      price_per_hour: 0.05
```

You can run simulations in two ways:

**Option 1: Using Python directly with a script**
```python
# main.py
from pathlib import Path
from nuberu import SimulationBuilder

builder = SimulationBuilder(Path("config.yaml"))
sim = builder.build()
sim.run()
```

```bash
uv run python main.py
```

**Option 2: Using the Nuberu CLI module**
```bash
# From the monorepo root or with nuberu installed
uv run python -m nuberu.cli.main run config.yaml
```

For complete working examples with all necessary data files (infrastructure.yaml, performance_data.yaml, allocations.yaml), see the [examples directory](../examples/).

---

## How It Works

The simulation follows these steps:

1. **Configuration Loading** - Reads YAML configuration files that define infrastructure, workloads, and simulation parameters
2. **Infrastructure Setup** - Creates VMs, containers, and resource allocations based on the configuration
3. **Workload Injection** - Generates requests according to specified distributions (Poisson, uniform, etc.)
4. **Load Balancing** - Routes incoming requests to available containers using the configured strategy
5. **Request Processing** - Simulates request execution using performance models and resource consumption
6. **Monitoring & Logging** - Records detailed metrics and events throughout the simulation

### Key Components

- **Infrastructure Manager** - Manages VMs and container lifecycle
- **Allocator** - Handles resource allocation and scaling decisions
- **Load Balancer** - Distributes requests across containers (supports simple, weighted, smoothWRR strategies)
- **Runtime Model** - Simulates request execution and resource usage

---

## Network Delays

Nuberu supports configurable network delays to model realistic latency between components:

```yaml
# Optional network delays (v3.2+)
network_delays:
  wi_to_lb: 10.0              # ms, WorkloadInjector -> LoadBalancer
  wi_to_lb_backward: 15.0     # ms, LoadBalancer -> WorkloadInjector (optional)
  lb_to_vm_default: 5.0       # ms, LoadBalancer -> VM
  lb_to_vm_default_backward: 8.0  # ms, VM -> LoadBalancer (optional)
  vm_container_overhead: 2.0  # ms, Container startup overhead

# Per-VM overrides (optional)
vm_network_overrides:
  - name: "remote-vm"
    network_delay: 50.0
    network_delay_backward: 60.0

# Per-workload overrides (optional)
workload_network_overrides:
  - app: "app_remote"
    network_delay: 100.0
```

**Features:**
- **Asymmetric delays**: Forward and backward delays can differ
- **Per-VM/workload overrides**: Model heterogeneous network conditions
- **Fallback logic**: Backward delays default to forward if not specified

For detailed documentation, see [Channels and Latency](../docs/doc/concepts/channels-and-latency.md).

---

## Output

After running a simulation, you'll find:

- **Logs** (`./logs/`) - Detailed event logs showing simulation progression
- **Metrics** (`./metrics/`) - CSV or JSON files containing:
  - Request latencies and throughput
  - Resource utilization (CPU, memory)
  - Container and VM statistics
  - Cost metrics

Use these outputs to analyze cloud infrastructure performance and optimize resource allocation strategies.

---

## Running Tests

```bash
cd core
uv run pytest
```

---

## Documentation

For comprehensive documentation, see the [Nuberu Documentation](../docs/doc/README.md).

---

## License

This project is licensed under the MIT License. See the LICENSE file for details.
