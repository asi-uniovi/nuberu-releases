# Custom Monitor Plugin for Nuberu

A lightweight monitoring plugin that exports raw simulation events to JSONL format for post-hoc analysis. This plugin uses **O(1) memory** during simulation by writing events directly to disk.

## Features

- **Memory efficient**: O(1) memory usage (writes to disk, no accumulation)
- **Complete event capture**: Exports full timeline for each request
- **Post-hoc analysis**: Includes analysis script to compute all metrics
- **Flexible**: Can be analyzed multiple times without re-running simulation

## Use Case

**Replacement for legacy Monitor component** - This plugin + post-hoc analysis provides all Monitor metrics without O(n) memory overhead:

| Metric | Monitor (Legacy) | CustomMonitor + Analysis |
|--------|------------------|--------------------------|
| Memory usage | O(n) | O(1) |
| Percentiles (p50, p95, p99) | Yes | Yes (post-hoc) |
| Queue time breakdown | Yes | Yes (post-hoc) |
| Service time breakdown | Yes | Yes (post-hoc) |
| Network delays | Yes | Yes (post-hoc) |
| Per-app statistics | Yes | Yes (post-hoc) |
## Configuration

In your YAML configuration:

```yaml
custom_plugins:
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/events.jsonl
```

## Post-Hoc Analysis

After simulation, analyze the JSONL file to compute all metrics:

```bash
# Console output with all statistics
python -m nuberu_plugin_custom_monitor.analyze_metrics ./metrics/events.jsonl

# Save to JSON file
python -m nuberu_plugin_custom_monitor.analyze_metrics ./metrics/events.jsonl -o report.json -f json
```

### Metrics Computed

The analysis script computes:

1. **Summary statistics**: requests generated/completed/rejected/lost, completion rate
2. **Latency statistics**: mean, median, p50, p95, p99, min, max, stdev
3. **Queue time statistics**: time spent in container queue
4. **Service time statistics**: time spent processing
5. **Network delays**: forward (Client->Container) and backward (Container->Client)
6. **Per-app statistics**: all above metrics separated by application
7. **Cost information**: total cost from cost models

### Example Output

```
======================================================================
 NUBERU SIMULATION ANALYSIS (Post-hoc from JSONL)
======================================================================

Summary:
  Total cost: $0.0900
  Requests generated: 4127
  Requests completed: 3779
  Requests rejected: 348
  Requests lost: 0
  Completion rate: 91.57%

Latency statistics (seconds):
  Count: 3779
  Mean: 0.8113
  Median (p50): 0.7856
  P95: 1.2345
  P99: 1.8976
  Min: 0.2123
  Max: 2.0000
  Stdev: 0.3388

Queue time statistics (seconds):
  Count: 3779
  Mean: 0.0234
  Median (p50): 0.0210
  P95: 0.0567
  P99: 0.0890

Per-app statistics:
  App: app0
    Generated: 1050
    Completed: 989
    Latency (mean): 0.2145s
    Latency (p95): 0.2890s
    Latency (p99): 0.3125s
  
  App: app1
    Generated: 3077
    Completed: 2790
    Latency (mean): 0.9834s
    Latency (p95): 1.4567s
    Latency (p99): 1.9876s
======================================================================
```

## Recommended Workflow

For production experiments, combine with `report_generator` plugin:

```yaml
custom_plugins:
  # Raw events for detailed post-hoc analysis
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/{{scenario}}.jsonl
  
  # Immediate summary report (O(1) memory)
  - plugin_name: report_generator
    plugin_config:
      output_format: "json"
      output_path: "./reports/{{scenario}}_report"
```

This gives you:
- Immediate summary at simulation end (report_generator)
- Detailed analysis when needed (analyze_metrics.py)
- No memory overhead during simulation
