# Configuration Reference

> Complete reference for Nuberu YAML configuration files.

## Configuration Versions

| Version | Status | Key Features |
|---------|--------|-------------|
| `2.1` | Legacy | No network delays |
| `3.1` | Supported | Basic network delays, monitoring, per-app runtime models |
| `3.2` | **Current** | Asymmetric delays, MultiChannelReceiver |

---

## Full Configuration Example

```yaml
config_version: "3.2"

# ─── Simulation Parameters ──────────────────────────────────────────

simulation:
  seed: 12345                        # Random seed for reproducibility
  stop_time: 3600                    # Simulation duration (seconds)
  eager_start: true                  # Apply first allocation immediately
  drain_pending_requests: true       # Drain mode on shutdown
  allocator_interval: 250           # Seconds between allocation cycles

# ─── Logging ─────────────────────────────────────────────────────────

logging:
  level: "full"                      # Global log level (default)
  log_to_console: true
  log_to_file: true
  output_path: ./logs/
  log_file_name: simulation.log
  component_levels:                  # Per-component overrides (optional)
    plugins: WARNING
    plugins.my_plugin: DEBUG

# ─── Network Delays ─────────────────────────────────────────────────

network_delays:
  wi_to_lb: 10.0                    # ms, WorkloadInjector -> LoadBalancer
  wi_to_lb_backward: 15.0           # ms, LB -> WI (optional, default = wi_to_lb)
  lb_to_vm_default: 5.0             # ms, LoadBalancer -> VM
  lb_to_vm_default_backward: 8.0    # ms, VM -> LB (optional, default = lb_to_vm_default)
  vm_container_overhead: 2.0        # ms, Container startup overhead

# Per-VM overrides (optional)
vm_network_overrides:
  - name: "vm-remote-az"
    network_delay: 50.0
    network_delay_backward: 60.0

# Per-workload overrides (optional)
workload_network_overrides:
  - app: "app_remote_region"
    network_delay: 100.0
    network_delay_backward: 120.0

# ─── Data Providers ─────────────────────────────────────────────────

infrastructure:
  plugin_name: conlloovia
  plugin_config:
    pickle_path: "./data/solution.p"
    yaml_path: "./data/infrastructure.yaml"

performance_data:
  plugin_name: conlloovia
  plugin_config:
    pickle_path: "./data/solution.p"

allocation:
  plugin_name: conlloovia
  plugin_config:
    pickle_path: "./data/solution.p"

# ─── Runtime Model ──────────────────────────────────────────────────

# Default runtime model for all apps
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 100

# Per-app overrides (optional)
runtime_models:
  app_critical:
    plugin_name: simple
    plugin_config:
      queue_size: 500

# ─── Load Balancer ───────────────────────────────────────────────────

load_balancer:
  plugin_name: smoothWRR
  plugin_config: {}

# ─── Workloads ───────────────────────────────────────────────────────

workloads:
  - app: app0
    distribution:
      plugin_name: poisson
      plugin_config:
        num_reqs: 100000
        time_slot_size: 3600
  - app: app1
    distribution:
      plugin_name: uniform
      plugin_config:
        num_reqs: 50000
        time_slot_size: 3600

# ─── Cost Models ─────────────────────────────────────────────────────

cost_models:
  - plugin_name: spot
    plugin_config:
      price_per_hour: 0.05

# ─── Custom Plugins ─────────────────────────────────────────────────

custom_plugins:
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/events.jsonl
  
  - plugin_name: report_generator
    plugin_config:
      output_format: "json"         # console, json, csv, jsonl
      output_path: "./reports/report"
```

---

## Section Reference

### `simulation`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seed` | int | `12345` | Random seed for reproducibility |
| `stop_time` | float\|null | `null` | Simulation duration in seconds (`null` = until idle) |
| `eager_start` | bool | `false` | If true, first allocation is applied immediately |
| `drain_pending_requests` | bool | `false` | If true, containers wait for pending requests before stopping |
| `allocator_interval` | int | `250` | Seconds between allocation cycles |

### `logging`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | string | `"full"` | Global log level (`none`, `debug`, `info`, `warning`, `error`, `critical`, `full`) |
| `log_to_console` | bool | `true` | Output logs to stdout |
| `log_to_file` | bool | `false` | Write logs to file |
| `output_path` | string | `null` | Directory for log files |
| `log_file_name` | string | `null` | Name of the log file |
| `component_levels` | dict | `{}` | Per-component log level overrides (extra fields allowed) |

### `network_delays`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `wi_to_lb` | float | `10.0` | Client-to-balancer latency (ms) |
| `wi_to_lb_backward` | float | `= wi_to_lb` | Balancer-to-client latency (ms) |
| `lb_to_vm_default` | float | `5.0` | Balancer-to-VM latency (ms) |
| `lb_to_vm_default_backward` | float | `= lb_to_vm_default` | VM-to-balancer latency (ms) |
| `vm_container_overhead` | float | `2.0` | Container startup overhead (ms) |
| `drain_grace_period` | float | `500.0` | Grace period (ms) for in-flight requests during container drain |

### `infrastructure` / `performance_data` / `allocation`

| Parameter | Type | Description |
|-----------|------|-------------|
| `plugin_name` | string | Name of the data provider plugin |
| `plugin_config` | dict | Plugin-specific configuration |

**YAML mode** (alternative to plugin):

```yaml
infrastructure:
  mode: yaml
  yaml_path: ./data/infrastructure.yaml
```

### `runtime_model` / `runtime_models`

| Parameter | Type | Description |
|-----------|------|-------------|
| `plugin_name` | string | Runtime model plugin name |
| `plugin_config.queue_size` | int | Maximum queue size (0 = no queue) |

`runtime_model` sets the default; `runtime_models` provides per-app overrides.

### `load_balancer`

| Parameter | Type | Description |
|-----------|------|-------------|
| `plugin_name` | string | Load balancer plugin name |
| `plugin_config` | dict | Plugin-specific configuration |

**Available plugins**: `simple` (round-robin), `smoothWRR`, `weighted`

### `workloads`

| Parameter | Type | Description |
|-----------|------|-------------|
| `app` | string | Application name (must match infrastructure) |
| `distribution.plugin_name` | string | Distribution plugin |
| `distribution.plugin_config.num_reqs` | int | Number of requests to generate |
| `distribution.plugin_config.time_slot_size` | float | Time window for generation (seconds) |

**Available distributions**: `poisson`, `poisson-dynamic`, `uniform`

### `cost_models`

| Parameter | Type | Description |
|-----------|------|-------------|
| `plugin_name` | string | Cost model plugin |
| `plugin_config` | dict | Plugin-specific configuration |

### `custom_plugins`

| Parameter | Type | Description |
|-----------|------|-------------|
| `plugin_name` | string | Custom plugin name |
| `plugin_config` | dict | Plugin-specific configuration |

---

## Further Reading

- [Getting Started](./getting-started.md) — Your first simulation config
- [Architecture Overview](./concepts/architecture-overview.md) — How configuration maps to components
- [Channels and Latency](./concepts/channels-and-latency.md) — Network delay details
- [Writing Plugins](./guides/writing-plugins.md) — Adding new plugin types
