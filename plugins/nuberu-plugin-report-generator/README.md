# Nuberu Report Generator Plugin

A plugin for generating **immediate summary reports** at simulation end using O(1) memory.

## Purpose

This plugin provides **instant feedback** when simulation finishes. It complements 
`monitor_simple` plugin which captures detailed events for post-hoc analysis.

**Key distinction**: 
- Provides **mean, min, max, stdev** (O(1) memory)
- Does NOT provide **percentiles** (would require O(n) memory)
- Use `analyze_metrics.py` on monitor_simple JSONL for percentiles

## Use Case & Workflow

**Recommended setup** - Use BOTH plugins:

```yaml
custom_plugins:
  # 1. Raw event capture for detailed analysis
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/{{scenario}}.jsonl
  
  # 2. Immediate summary at simulation end
  - plugin_name: report_generator
    plugin_config:
      output_format: "json"
      output_path: "./reports/{{scenario}}_summary"
```

**Workflow:**
1. **During simulation**: Both plugins collect metrics in O(1) memory
2. **At simulation end**: `report_generator` prints immediate summary
3. **For detailed analysis** (later): Run `analyze_metrics.py` on JSONL for percentiles

## Responsibility Matrix

| Component | Purpose | Output | Percentiles | Memory |
|-----------|---------|--------|-------------|---------|
| **monitor_simple** | Raw event capture | JSONL with timelines | No | O(1) |
| **report_generator** | Immediate summary | Statistics (mean, min, max) | No | O(1) |
| **analyze_metrics.py** | Post-hoc analysis | Full statistics + percentiles | Yes | O(n) during analysis only |

## Description

This plugin subscribes to simulation events and generates summary statistics
using Welford's algorithm for streaming computation.

## Features

- Listens to simulation events to collect metrics in real-time
- Uses O(1) memory for latency statistics (Welford's algorithm)
- Supports multiple output formats (configurable):
  - Console output (default)
  - JSON file
  - CSV file (flattened)
  - JSONL streaming format (append mode)

## Metrics Collected

| Metric | Description |
|--------|-------------|
| `simulation_end_time` | Final simulation time |
| `total_cost` | Total cost from all cost models |
| `cost_breakdown` | Per-model cost breakdown |
| `requests_generated` | Total requests generated |
| `requests_completed` | Total requests completed |
| `requests_rejected` | Total requests rejected |
| `requests_lost` | Total requests lost |
| `completion_rate` | Completed / Generated ratio |
| `latency_mean` | Mean response time (Welford's algorithm) |
| `latency_min/max` | Min/Max response time |
| `latency_stdev` | Response time standard deviation |
| `vm_active_times` | Per-VM active duration |
| `total_vm_time` | Sum of all VM active times |

**Note**: This plugin does NOT compute percentiles (p50, p95, p99) to maintain O(1) memory.
For percentiles, use `analyze_metrics.py` on the `monitor_simple` JSONL output.

## Configuration

In your YAML configuration file:

```yaml
custom_plugins:
  - plugin_name: report_generator
    plugin_config:
      output_format: "console"  # Options: "console", "json", "csv", "jsonl"
      output_path: "reports/simulation_report"  # Base path for file output (optional)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_format` | string | `"console"` | Output format: `console`, `json`, `csv`, `jsonl` |
| `output_path` | string | `null` | Base path for file output (required for non-console formats) |

## Architecture

The plugin implements the `CustomPluginProtocol`:
- `prepare()`: Subscribes to events (`REQUEST_*`, `VM_*`, `COST_FINAL`, `SIMULATION_FINISHED`)
- `run()`: Starts the event processing loop
- `finish()`: Generates the final report

## Events Subscribed

| Event | Purpose |
|-------|---------|
| `END_SIMULATION` | Detect simulation ending |
| `SIMULATION_FINISHED` | Final cleanup complete |
| `COST_FINAL` | Collect cost information |
| `REQUEST_GENERATED` | Count generated requests |
| `REQUEST_COMPLETED` | Count completed, track latency |
| `REQUEST_REJECTED` | Count rejected requests |
| `REQUEST_LOST` | Count lost requests |
| `VM_STARTED` | Track VM start times |
| `VM_STOPPED` | Calculate VM active durations |
