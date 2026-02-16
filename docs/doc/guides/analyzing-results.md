# Analyzing Simulation Results

> How to extract, analyze, and interpret Nuberu simulation output.

## Prerequisites

Before analyzing results, ensure your simulation YAML includes monitoring plugins. See [Monitoring and Metrics](../concepts/monitoring-and-metrics.md) for setup.

```yaml
custom_plugins:
  - plugin_name: monitor_simple
    plugin_config:
      dump_file: ./metrics/events.jsonl
  - plugin_name: report_generator
    plugin_config:
      output_format: "json"
      output_path: "./reports/summary"
```

---

## Quick Summary: ReportGenerator Output

After a simulation, `report_generator` produces immediate summary statistics:

```
SIMULATION REPORT (ReportGenerator Plugin)
==================================================
Simulation end time: 3600.00s
Total cost: $45.2345

Request statistics:
  Generated: 1234567
  Completed: 1200000
  Rejected: 34567
  Lost: 0
  Completion rate: 97.20%

Latency statistics (seconds):
  Count: 1200000
  Mean: 0.8234
  Min: 0.1234
  Max: 2.5678
  Stdev: 0.3456
==================================================
```

This gives you a fast overview. For deeper analysis, use `analyze_metrics.py`.

---

## Detailed Analysis with `analyze_metrics.py`

### Basic Usage

```bash
# Console output
python -m nuberu_plugin_custom_monitor.analyze_metrics ./metrics/events.jsonl
```

### Export to JSON

```bash
python -m nuberu_plugin_custom_monitor.analyze_metrics \
  ./metrics/events.jsonl \
  -o ./reports/detailed_analysis.json \
  -f json
```

### What You Get

| Category | Metrics |
|----------|---------|
| **Summary** | Total cost, completion rate, request counts |
| **Latency** | Mean, p50, p95, p99, min, max, stdev |
| **Queue time** | Mean, p50, p95, p99 (time spent waiting in queue) |
| **Service time** | Mean, p50, p95, p99 (actual processing time) |
| **Network delay** | Forward and backward delays separately |
| **Per-app** | All of the above broken down by application |

---

## Batch Analysis

Analyze multiple experiment results at once:

```bash
for file in metrics/*.jsonl; do
  python -m nuberu_plugin_custom_monitor.analyze_metrics "$file" \
    -o "reports/$(basename $file .jsonl)_analysis.json" -f json
done
```

---

## Custom Analysis Scripts

The JSONL format is line-oriented JSON, easy to parse with standard Python:

### Finding Slow Requests

```python
import json

with open("metrics/events.jsonl") as f:
    slow_requests = []
    for line in f:
        event = json.loads(line)
        if event.get("status") == "completed":
            latency = event["finish_time"] - event["arrival_time"]
            if latency > 1.0:
                slow_requests.append(event)

print(f"Found {len(slow_requests)} slow requests (>1s)")
```

### Analyzing Request Timelines

```python
import json

with open("metrics/events.jsonl") as f:
    for line in f:
        event = json.loads(line)
        if event.get("status") == "completed" and event.get("timeline"):
            timeline = event["timeline"]
            # Calculate per-component durations
            for i in range(1, len(timeline)):
                duration = timeline[i]["time"] - timeline[i-1]["time"]
                component = timeline[i]["component_id"]
                print(f"  {component}: {duration:.4f}s")
```

### Per-App Comparison

```python
import json
from collections import defaultdict

latencies = defaultdict(list)

with open("metrics/events.jsonl") as f:
    for line in f:
        event = json.loads(line)
        if event.get("status") == "completed":
            app = event["app_id"]
            latency = event["finish_time"] - event["arrival_time"]
            latencies[app].append(latency)

for app, values in sorted(latencies.items()):
    values.sort()
    n = len(values)
    print(f"{app}:")
    print(f"  Count: {n}")
    print(f"  Median: {values[n//2]:.4f}s")
    print(f"  P95:    {values[int(n*0.95)]:.4f}s")
    print(f"  P99:    {values[int(n*0.99)]:.4f}s")
```

---

## Understanding the Output

### Key Ratios to Check

| Check | What It Means |
|-------|---------------|
| `completion_rate < 95%` | Containers may be undersized or queue too small |
| `rejected > 0` | Queue saturation — increase `queue_size` or add containers |
| `lost > 0` | Requests interrupted — check if using hardstop mode |
| `p99 >> p50` | High tail latency — possible straggler containers |
| `queue_time >> service_time` | Queuing bottleneck — containers are overloaded |

### Drain Mode Impact

| Metric | Hardstop | Drain |
|--------|----------|-------|
| Lost requests | Usually > 0 | 0 |
| Completion rate | < 100% | 100% (if no rejections) |
| Latency coverage | Partial | Full |

---

## Further Reading

- [Monitoring and Metrics](../concepts/monitoring-and-metrics.md) — Architecture of the monitoring system
- [Drain Mode](../concepts/drain-mode.md) — How termination mode affects results
- [Configuration Reference](../configuration-reference.md) — Monitoring plugin options
