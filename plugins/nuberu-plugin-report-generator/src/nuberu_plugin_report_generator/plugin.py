"""Nuberu Report Generator Plugin.

This plugin generates simulation reports by subscribing to SIMULATION_FINISHED
and collecting metrics from various events.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import asimpy
import pluggy
from nuberu.core.events import EventBus, EventTopic
from nuberu.interfaces.protocols import CustomPluginProtocol
from nuberu.plugins import PluginBase

hookimpl = pluggy.HookimplMarker("nuberu")


@dataclass
class ReportData:
    """Data collected for the report.

    Uses O(1) running statistics for latency instead of storing all values.
    This allows handling millions of requests without memory issues.
    """

    total_cost: float = 0.0
    cost_breakdown: dict[str, float] = field(default_factory=dict)

    requests_generated: int = 0
    requests_completed: int = 0
    requests_rejected: int = 0
    requests_lost: int = 0

    # Latency running statistics (O(1) memory - Welford's algorithm)
    _latency_count: int = 0
    _latency_sum: float = 0.0
    _latency_sum_sq: float = 0.0  # For variance calculation
    _latency_min: float = float("inf")
    _latency_max: float = float("-inf")

    # VM data
    vm_active_times: dict[str, float] = field(default_factory=dict)

    # Simulation metadata
    simulation_end_time: float = 0.0

    def add_latency(self, rt: float) -> None:
        """Add a response time using running statistics (O(1) memory)."""
        self._latency_count += 1
        self._latency_sum += rt
        self._latency_sum_sq += rt * rt
        if rt < self._latency_min:
            self._latency_min = rt
        if rt > self._latency_max:
            self._latency_max = rt

    def get_latency_stats(self) -> dict[str, float] | None:
        """Calculate latency statistics from running totals.

        Returns None if no latency data collected.
        Note: median and percentiles cannot be computed without storing all values.
        """
        if self._latency_count == 0:
            return None

        mean = self._latency_sum / self._latency_count
        variance = (self._latency_sum_sq / self._latency_count) - (mean * mean)
        stdev = variance**0.5 if variance > 0 else 0.0

        return {
            "count": self._latency_count,
            "mean": mean,
            "min": self._latency_min,
            "max": self._latency_max,
            "stdev": stdev,
        }


class ReportGeneratorPluginImplementation:
    """A plugin that generates simulation reports."""

    def __init__(
        self,
        env: asimpy.Environment,
        event_bus: EventBus,
        output_format: str = "console",
        output_path: str | None = None,
        logger: logging.Logger | None = None,
    ):
        self.env = env
        self.event_bus = event_bus
        self.output_format = output_format.lower()
        self.output_path = output_path
        self.logger = logger or logging.getLogger(__name__)
        self.class_name = self.__class__.__name__

        self.report_data = ReportData()

        self._simulation_finished = False

        # Topics to subscribe
        self.topics = [
            EventTopic.END_SIMULATION,  # To exit loop cleanly
            EventTopic.SIMULATION_FINISHED,  # To know all shutdown complete
            EventTopic.COST_FINAL,
            EventTopic.REQUEST_GENERATED,
            EventTopic.REQUEST_COMPLETED,
            EventTopic.REQUEST_REJECTED,
            EventTopic.REQUEST_LOST,
            EventTopic.VM_STARTED,
            EventTopic.VM_STOPPED,
        ]

        # Track VM start times for duration calculation
        self._vm_start_times: dict[str, float] = {}

    def prepare(self) -> None:
        """Subscribe to events before simulation starts."""
        self.queue = asimpy.Store(self.env)
        for topic in self.topics:
            self.event_bus.subscribe(topic, self.queue)
            self.logger.debug(
                f"{self.class_name}: subscribed to {topic.value} at t={self.env.now}"
            )

    def run(self) -> None:
        """Start the event processing loop."""
        self.logger.info(f"{self.class_name}: Running...")
        self._main_proc = self.env.process(self._loop())

    async def _loop(self) -> None:
        """Main loop. Collects events for the report.

        This loop runs during the entire simulation, collecting metrics.
        It does NOT need to exit cleanly - when Simulation calls finish(),
        this process will be "abandoned" but that's fine (the report data
        has already been collected).

        Event order during finalization:
        1. SIMULATION_FINISHED is published by Simulation
        2. CostModel receives SIMULATION_FINISHED -> publishes COST_FINAL
        3. This plugin receives both events
        4. Simulation calls finish() on all plugins
        5. finish() generates the report with collected data
        """
        self.logger.info(f"{self.class_name}: Starting report data collection loop.")

        try:
            while True:
                event = await self.queue.get()

                if event.topic == EventTopic.END_SIMULATION:
                    self.logger.debug(
                        f"{self.class_name}: END_SIMULATION received at t={self.env.now}"
                    )
                    continue

                elif event.topic == EventTopic.SIMULATION_FINISHED:
                    self._simulation_finished = True
                    self.report_data.simulation_end_time = event.payload.get(
                        "time", self.env.now
                    )
                    self.logger.debug(
                        f"{self.class_name}: SIMULATION_FINISHED received at t={self.env.now}"
                    )
                    # Don't break - continue collecting events (COST_FINAL may come next)
                    continue

                elif event.topic == EventTopic.COST_FINAL:
                    self.report_data.total_cost = event.payload.get("total_cost", 0.0)
                    self.report_data.cost_breakdown = event.payload.get("breakdown", {})
                    self.logger.info(
                        f"{self.class_name}: COST_FINAL received: total_cost={self.report_data.total_cost}"
                    )
                    # Don't break - the loop will be abandoned when finish() is called
                    continue

                elif event.topic == EventTopic.REQUEST_GENERATED:
                    self.report_data.requests_generated += 1
                    continue

                elif event.topic == EventTopic.REQUEST_COMPLETED:
                    self.report_data.requests_completed += 1
                    # Extract response time if available (O(1) running stats)
                    arrival = event.payload.get("arrival_time")
                    finish = event.payload.get("finish_time", self.env.now)
                    if arrival is not None:
                        rt = finish - arrival
                        self.report_data.add_latency(rt)
                    continue

                elif event.topic == EventTopic.REQUEST_REJECTED:
                    self.report_data.requests_rejected += 1
                    continue

                elif event.topic == EventTopic.REQUEST_LOST:
                    self.report_data.requests_lost += 1
                    continue

                elif event.topic == EventTopic.VM_STARTED:
                    vm_id = event.payload.get("vm_id", "")
                    start_time = event.payload.get("time", self.env.now)
                    self._vm_start_times[vm_id] = start_time
                    continue

                elif event.topic == EventTopic.VM_STOPPED:
                    vm_id = event.payload.get("vm_id", "")
                    stop_time = event.payload.get("time", self.env.now)
                    start_time = self._vm_start_times.get(vm_id)
                    if start_time is not None:
                        duration = stop_time - start_time
                        self.report_data.vm_active_times[vm_id] = duration
                    continue

        except Exception as e:
            self.logger.error(f"{self.class_name} loop CRASHED: {e}", exc_info=True)
            raise

    def finish(self) -> None:
        """Generate the final report after simulation ends."""
        self.logger.info(f"{self.class_name}: Generating report...")

        # Build report dictionary
        report = self._build_report()

        # Output based on format
        if self.output_format == "console":
            self._output_console(report)
        elif self.output_format == "json":
            self._output_json(report)
        elif self.output_format == "csv":
            self._output_csv(report)
        elif self.output_format == "jsonl":
            self._output_jsonl(report)
        else:
            self.logger.warning(
                f"Unknown output format '{self.output_format}', using console"
            )
            self._output_console(report)

        self.logger.info(f"{self.class_name}: Report generation finished.")

    def _build_report(self) -> dict[str, Any]:
        """Build the report dictionary from collected data."""
        data = self.report_data

        report: dict[str, Any] = {
            "simulation_end_time": data.simulation_end_time,
            "total_cost": data.total_cost,
            "cost_breakdown": data.cost_breakdown,
        }

        # Request statistics (always included)
        sum_terminal = (
            data.requests_completed + data.requests_rejected + data.requests_lost
        )
        consistency_ok = sum_terminal == data.requests_generated

        report["request_statistics"] = {
            "generated": data.requests_generated,
            "sum_terminal": sum_terminal,
            "consistency_check": consistency_ok,
            "completed": data.requests_completed,
            "rejected": data.requests_rejected,
            "lost": data.requests_lost,
            "completion_rate": (
                data.requests_completed / data.requests_generated
                if data.requests_generated > 0
                else 0
            ),
        }

        # Latency statistics (from O(1) running stats)
        latency_stats = data.get_latency_stats()
        if latency_stats:
            report["latency_statistics"] = latency_stats

        # VM active times
        if data.vm_active_times:
            report["vm_active_times"] = data.vm_active_times
            report["total_vm_time"] = sum(data.vm_active_times.values())

        return report

    def _output_console(self, report: dict[str, Any]) -> None:
        """Output report to console/logger."""
        self.logger.info("=" * 50)
        self.logger.info(" SIMULATION REPORT (ReportGenerator Plugin)")
        self.logger.info("=" * 50)
        self.logger.info(f"Simulation end time: {report['simulation_end_time']:.2f}s")
        self.logger.info(f"Total cost: ${report['total_cost']:.4f}")

        if "cost_breakdown" in report and report["cost_breakdown"]:
            self.logger.info("Cost breakdown:")
            for name, cost in report["cost_breakdown"].items():
                self.logger.info(f"  {name}: ${cost:.4f}")

        if "request_statistics" in report:
            stats = report["request_statistics"]
            self.logger.info("Request statistics:")
            self.logger.info(f"  Generated: {stats['generated']}")
            self.logger.info(f"  Completed: {stats['completed']}")
            self.logger.info(f"  Rejected: {stats['rejected']}")
            self.logger.info(f"  Lost: {stats['lost']}")

            check_symbol = "=" if stats["consistency_check"] else "!="
            check_status = "OK" if stats["consistency_check"] else "MISMATCH"
            self.logger.info(
                f"  Consistency: completed + rejected + lost = {stats['sum_terminal']} "
                f"{check_symbol} generated ({stats['generated']}) {check_status}"
            )
            self.logger.info(f"  Completion rate: {stats['completion_rate']:.2%}")

        if "latency_statistics" in report:
            lat = report["latency_statistics"]
            self.logger.info("Latency statistics (seconds):")
            self.logger.info(f"  Count: {lat['count']}")
            self.logger.info(f"  Mean: {lat['mean']:.4f}")
            self.logger.info(f"  Min: {lat['min']:.4f}")
            self.logger.info(f"  Max: {lat['max']:.4f}")
            self.logger.info(f"  Stdev: {lat['stdev']:.4f}")
            # Note: median/percentiles not available (would need O(n) memory)

        if "vm_active_times" in report:
            self.logger.info(f"Total VM time: {report.get('total_vm_time', 0):.2f}s")

        self.logger.info("=" * 50)

    def _output_json(self, report: dict[str, Any]) -> None:
        """Output report to JSON file."""
        if not self.output_path:
            self.logger.warning("No output_path specified, falling back to console")
            self._output_console(report)
            return

        output_file = f"{self.output_path}.json"
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(report, f, indent=2, default=str)

        self.logger.info(f"Report saved to {output_file}")

    def _output_csv(self, report: dict[str, Any]) -> None:
        """Output report to CSV file (flattened)."""
        import csv

        if not self.output_path:
            self.logger.warning("No output_path specified, falling back to console")
            self._output_console(report)
            return

        output_file = f"{self.output_path}.csv"
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        # Flatten the report
        flat_report = self._flatten_dict(report)

        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=flat_report.keys())
            writer.writeheader()
            writer.writerow(flat_report)

        self.logger.info(f"Report saved to {output_file}")

    def _output_jsonl(self, report: dict[str, Any]) -> None:
        """Output report to JSONL file (append mode)."""
        if not self.output_path:
            self.logger.warning("No output_path specified, falling back to console")
            self._output_console(report)
            return

        output_file = f"{self.output_path}.jsonl"
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        with open(output_file, "a") as f:
            f.write(json.dumps(report, default=str) + "\n")

        self.logger.info(f"Report appended to {output_file}")

    def _flatten_dict(
        self, d: dict[str, Any], parent_key: str = "", sep: str = "_"
    ) -> dict[str, Any]:
        """Flatten a nested dictionary."""
        items: list[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)


class ReportGeneratorPlugin(PluginBase):
    """Plugin entry point for the Report Generator."""

    plugin_name = "report_generator"

    def __init__(self) -> None:
        super().__init__()

    @hookimpl
    def configure(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger.info(f"ReportGeneratorPlugin configured with: {config}")

    @hookimpl
    def get_factory(
        self, config: dict[str, Any]
    ) -> Callable[[asimpy.Environment, EventBus], CustomPluginProtocol]:
        output_format = config.get("output_format", "console")
        output_path = config.get("output_path", None)

        def factory(
            env: asimpy.Environment, event_bus: EventBus
        ) -> CustomPluginProtocol:
            return ReportGeneratorPluginImplementation(
                env,
                event_bus,
                output_format=output_format,
                output_path=output_path,
                logger=self.logger,
            )

        return factory
