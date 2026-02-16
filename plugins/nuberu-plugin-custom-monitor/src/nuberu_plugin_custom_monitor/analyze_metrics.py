"""Post-hoc analysis script for CustomSimpleMonitor JSONL output.

This script reads the raw events from CustomSimpleMonitor and computes
all metrics that were previously provided by the legacy Monitor component:
- Percentiles (p50, p95, p99)
- Queue time, service time, network delays breakdowns
- Per-app statistics

Usage:
    python -m nuberu_plugin_custom_monitor.analyze_metrics <jsonl_file> [--output report.json]
"""

import json
import sys
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
import statistics


@dataclass
class MetricStats:
    """Statistics for a single metric."""

    count: int = 0
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        """Add a value to the metric."""
        if value is not None:
            self.count += 1
            self.values.append(value)

    def compute(self) -> dict[str, float]:
        """Compute statistics (mean, median, p95, p99)."""
        if not self.values:
            return {}

        sorted_values = sorted(self.values)
        n = len(sorted_values)

        return {
            "count": n,
            "mean": statistics.mean(sorted_values),
            "median": statistics.median(sorted_values),
            "min": min(sorted_values),
            "max": max(sorted_values),
            "stdev": statistics.stdev(sorted_values) if n > 1 else 0.0,
            "p95": sorted_values[int(n * 0.95)] if n > 0 else 0.0,
            "p99": sorted_values[int(n * 0.99)] if n > 0 else 0.0,
        }


@dataclass
class RequestMetrics:
    """Metrics extracted from a single request."""

    request_id: str
    app_id: str
    status: str
    arrival_time: float
    completion_time: float | None = None
    queue_time: float | None = None
    service_time: float | None = None
    network_delay_forward: float | None = None
    network_delay_backward: float | None = None
    total_latency: float | None = None


def extract_metrics_from_timeline(
    timeline: list[dict[str, Any]],
) -> dict[str, float | None]:
    """Extract performance metrics from a request's timeline.

    Args:
        timeline: List of timeline entries with 'component_id' and 'time' keys

    Returns:
        dict with queue_time, service_time, network_delay_forward/backward, total_latency
    """
    if not timeline:
        return {}

    # Build lookup dict (keep first occurrence for each component_id)
    events = {}
    for entry in timeline:
        component_id = entry["component_id"]
        if component_id not in events:
            events[component_id] = entry["time"]

    # Extract timestamps
    t_generated = events.get("Client_generated")
    t_send_to_lb = events.get("Client_send_to_lb")

    # Find container accept time - look for first Container_ component
    t_container_accept = None
    for entry in timeline:
        comp_id = entry["component_id"]
        if comp_id.startswith("Container_") and entry.get("event") in [
            "receive_from_lb",
            "accepted_and_sent_to_runtime",
        ]:
            t_container_accept = entry["time"]
            break

    # Find processing times (pattern: Runtime_{id}_start_service, Runtime_{id}_end_service)
    t_start_processing = next(
        (
            events[k]
            for k in events
            if k.startswith("Runtime_") and "_start_service" in k
        ),
        None,
    )
    t_finish_processing = next(
        (events[k] for k in events if k.startswith("Runtime_") and "_end_service" in k),
        None,
    )

    t_client_recv = events.get("Client_receive_response")

    # Compute metrics
    metrics = {}

    if t_container_accept and t_start_processing:
        metrics["queue_time"] = t_start_processing - t_container_accept

    if t_start_processing and t_finish_processing:
        metrics["service_time"] = t_finish_processing - t_start_processing

    if t_send_to_lb and t_container_accept:
        metrics["network_delay_forward"] = t_container_accept - t_send_to_lb

    if t_finish_processing and t_client_recv:
        metrics["network_delay_backward"] = t_client_recv - t_finish_processing

    if t_generated and t_client_recv:
        metrics["total_latency"] = t_client_recv - t_generated

    metrics["arrival_time"] = t_generated
    metrics["completion_time"] = t_client_recv

    return metrics


def analyze_jsonl(jsonl_path: str) -> dict[str, Any]:
    """Analyze CustomSimpleMonitor JSONL output.

    Args:
        jsonl_path: Path to JSONL file

    Returns:
        Dictionary with comprehensive statistics
    """
    # Global metrics
    total_cost = 0.0
    requests_generated = 0
    requests_completed = 0
    requests_rejected = 0
    requests_lost = 0

    # Metric collectors
    latency = MetricStats()
    queue_time = MetricStats()
    service_time = MetricStats()
    network_delay_forward = MetricStats()
    network_delay_backward = MetricStats()

    # Per-app metrics
    per_app_metrics: dict[str, dict[str, Any]] = {}

    # Read JSONL
    with open(jsonl_path, "r") as f:
        for line in f:
            event = json.loads(line.strip())

            # Cost event
            if "total_cost" in event and "request_id" not in event:
                total_cost = event["total_cost"]
                continue

            # Request events
            status = event.get("status")
            if not status:
                continue

            app_id = event.get("app_id", "unknown")

            # Initialize per-app stats
            if app_id not in per_app_metrics:
                per_app_metrics[app_id] = {
                    "generated": 0,
                    "completed": 0,
                    "rejected": 0,
                    "lost": 0,
                    "latency": MetricStats(),
                }

            # Count by status
            if status == "completed":
                requests_completed += 1
                per_app_metrics[app_id]["completed"] += 1

                # Extract detailed metrics from timeline
                timeline = event.get("timeline", [])
                metrics = extract_metrics_from_timeline(timeline)

                # Use arrival_time and finish_time for latency (more reliable than timeline)
                arrival = event.get("arrival_time")
                finish = event.get("finish_time")
                if arrival is not None and finish is not None:
                    total_latency = finish - arrival
                    latency.add(total_latency)
                    per_app_metrics[app_id]["latency"].add(total_latency)

                if metrics.get("queue_time") is not None:
                    queue_time.add(metrics["queue_time"])

                if metrics.get("service_time") is not None:
                    service_time.add(metrics["service_time"])

                if metrics.get("network_delay_forward") is not None:
                    network_delay_forward.add(metrics["network_delay_forward"])

                if metrics.get("network_delay_backward") is not None:
                    network_delay_backward.add(metrics["network_delay_backward"])

            elif status == "rejected":
                requests_rejected += 1
                per_app_metrics[app_id]["rejected"] += 1

            elif status == "dropped" or status == "lost":
                requests_lost += 1
                per_app_metrics[app_id]["lost"] += 1

    # Compute generated (assuming all events are present)
    requests_generated = requests_completed + requests_rejected + requests_lost
    for app_id in per_app_metrics:
        per_app_metrics[app_id]["generated"] = (
            per_app_metrics[app_id]["completed"]
            + per_app_metrics[app_id]["rejected"]
            + per_app_metrics[app_id]["lost"]
        )

    # Build report
    report = {
        "summary": {
            "total_cost": total_cost,
            "requests_generated": requests_generated,
            "requests_completed": requests_completed,
            "requests_rejected": requests_rejected,
            "requests_lost": requests_lost,
            "completion_rate": (
                requests_completed / requests_generated if requests_generated > 0 else 0
            ),
        },
        "latency_statistics": latency.compute(),
        "queue_time_statistics": queue_time.compute(),
        "service_time_statistics": service_time.compute(),
        "network_delay_forward_statistics": network_delay_forward.compute(),
        "network_delay_backward_statistics": network_delay_backward.compute(),
        "per_app_statistics": {},
    }

    # Add per-app statistics
    for app_id, app_stats in per_app_metrics.items():
        report["per_app_statistics"][app_id] = {
            "generated": app_stats["generated"],
            "completed": app_stats["completed"],
            "rejected": app_stats["rejected"],
            "lost": app_stats["lost"],
            "completion_rate": (
                app_stats["completed"] / app_stats["generated"]
                if app_stats["generated"] > 0
                else 0
            ),
            "latency_statistics": app_stats["latency"].compute(),
        }

    return report


def format_report_console(report: dict[str, Any]) -> str:
    """Format report for console output."""
    lines = []
    lines.append("=" * 70)
    lines.append(" NUBERU SIMULATION ANALYSIS (Post-hoc from JSONL)")
    lines.append("=" * 70)

    # Summary
    summary = report["summary"]
    lines.append("\nSummary:")
    lines.append(f"  Total cost: ${summary['total_cost']:.4f}")
    lines.append(f"  Requests generated: {summary['requests_generated']}")
    lines.append(f"  Requests completed: {summary['requests_completed']}")
    lines.append(f"  Requests rejected: {summary['requests_rejected']}")
    lines.append(f"  Requests lost: {summary['requests_lost']}")
    lines.append(f"  Completion rate: {summary['completion_rate']:.2%}")

    # Latency statistics
    if report.get("latency_statistics"):
        lat = report["latency_statistics"]
        lines.append("\nLatency statistics (seconds):")
        lines.append(f"  Count: {lat['count']}")
        lines.append(f"  Mean: {lat['mean']:.4f}")
        lines.append(f"  Median (p50): {lat['median']:.4f}")
        lines.append(f"  P95: {lat['p95']:.4f}")
        lines.append(f"  P99: {lat['p99']:.4f}")
        lines.append(f"  Min: {lat['min']:.4f}")
        lines.append(f"  Max: {lat['max']:.4f}")
        lines.append(f"  Stdev: {lat['stdev']:.4f}")

    # Queue time statistics
    if report.get("queue_time_statistics"):
        qt = report["queue_time_statistics"]
        lines.append("\nQueue time statistics (seconds):")
        lines.append(f"  Count: {qt['count']}")
        lines.append(f"  Mean: {qt['mean']:.4f}")
        lines.append(f"  Median (p50): {qt['median']:.4f}")
        lines.append(f"  P95: {qt['p95']:.4f}")
        lines.append(f"  P99: {qt['p99']:.4f}")

    # Service time statistics
    if report.get("service_time_statistics"):
        st = report["service_time_statistics"]
        lines.append("\nService time statistics (seconds):")
        lines.append(f"  Count: {st['count']}")
        lines.append(f"  Mean: {st['mean']:.4f}")
        lines.append(f"  Median (p50): {st['median']:.4f}")
        lines.append(f"  P95: {st['p95']:.4f}")
        lines.append(f"  P99: {st['p99']:.4f}")

    # Network delays
    if report.get("network_delay_forward_statistics"):
        ndf = report["network_delay_forward_statistics"]
        lines.append("\nNetwork delay forward (Client->Container, seconds):")
        lines.append(f"  Count: {ndf['count']}")
        lines.append(f"  Mean: {ndf['mean']:.4f}")
        lines.append(f"  Median: {ndf['median']:.4f}")
        lines.append(f"  P95: {ndf['p95']:.4f}")

    if report.get("network_delay_backward_statistics"):
        ndb = report["network_delay_backward_statistics"]
        lines.append("\nNetwork delay backward (Container->Client, seconds):")
        lines.append(f"  Count: {ndb['count']}")
        lines.append(f"  Mean: {ndb['mean']:.4f}")
        lines.append(f"  Median: {ndb['median']:.4f}")
        lines.append(f"  P95: {ndb['p95']:.4f}")

    # Per-app statistics
    if report.get("per_app_statistics"):
        lines.append("\nPer-app statistics:")
        for app_id, app_stats in report["per_app_statistics"].items():
            lines.append(f"\n  App: {app_id}")
            lines.append(f"    Generated: {app_stats['generated']}")
            lines.append(f"    Completed: {app_stats['completed']}")
            lines.append(f"    Rejected: {app_stats['rejected']}")
            lines.append(f"    Lost: {app_stats['lost']}")
            lines.append(f"    Completion rate: {app_stats['completion_rate']:.2%}")
            if app_stats.get("latency_statistics"):
                lat = app_stats["latency_statistics"]
                lines.append(f"    Latency (mean): {lat.get('mean', 0):.4f}s")
                lines.append(f"    Latency (p95): {lat.get('p95', 0):.4f}s")
                lines.append(f"    Latency (p99): {lat.get('p99', 0):.4f}s")

    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    """Main entry point for CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze CustomSimpleMonitor JSONL output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "jsonl_file", help="Path to JSONL file from CustomSimpleMonitor"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file for JSON report (default: print to console)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "console"],
        default="console",
        help="Output format (default: console)",
    )

    args = parser.parse_args()

    # Check file exists
    if not Path(args.jsonl_file).exists():
        print(f"Error: File not found: {args.jsonl_file}", file=sys.stderr)
        sys.exit(1)

    # Analyze
    print(f"Analyzing {args.jsonl_file}...", file=sys.stderr)
    report = analyze_jsonl(args.jsonl_file)

    # Output
    if args.format == "json":
        output_str = json.dumps(report, indent=2)
    else:
        output_str = format_report_console(report)

    if args.output:
        # Create directory if needed
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(args.output, "w") as f:
            f.write(output_str)
        print(f"Report saved to {args.output}", file=sys.stderr)
    else:
        print(output_str)


if __name__ == "__main__":
    main()
