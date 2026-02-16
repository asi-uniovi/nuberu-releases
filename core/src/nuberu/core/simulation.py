from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

import asimpy

from ..components.allocator import Allocator
from ..components.infrastructure_manager import InfrastructureManager
from ..components.registry import Registry
from ..core.events import EventBus, EventTopic
from ..interfaces.protocols import (
    CostModelProtocol,
    CustomPluginProtocol,
    LoadBalancerProtocol,
)
from ..workload.workload_injector import WorkloadInjector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Simulation:
    """
    Facade that coordinates the already-built simulation components.

    Attributes:
        env (asimpy.Environment): The simulation environment.
        allocator (Allocator): Handles resource allocation.
        infra_manager (InfrastructureManager): Manages VMs and Containers.
        registry (Registry): Discovering service that map applications to containers.
        load_balancer (LoadBalancer): Distributes workloads.
        workload_injector (WorkloadInjector): Injects workloads into the simulation.
        cost_models (list[CostModelProtocol]): Calculates costs based on resource usage.
        event_bus (EventBus): Manages events and communication between components.
        stop_time (Optional[float]): The time until which the simulation will run. If None, runs indefinitely.
    """

    # Construction - objects are injected, nothing is created here.
    def __init__(
        self,
        *,  # Force keyword arguments to avoid confusion with positional arguments
        env: asimpy.Environment,
        allocator: Allocator,
        infra_manager: InfrastructureManager,
        registry: Registry,
        load_balancer: LoadBalancerProtocol,
        workload_injector: WorkloadInjector,
        cost_models: list[CostModelProtocol],
        custom_plugins: list[CustomPluginProtocol] | None = None,
        event_bus: EventBus,
        stop_time: Optional[float],
    ):
        """
        Initialize the Simulation facade with all required components.

        Args:
            env (asimpy.Environment): The simulation environment.
            allocator (Allocator): Allocates resources dynamically.
            infra_manager (InfrastructureManager): Manages VMs and Containers.
            registry (Registry): Maps applications to containers.
            load_balancer (LoadBalancerProtocol): Handles workload distribution.
            workload_injector (WorkloadInjector): Injects workload events.
            cost_models (list[CostModelProtocol]): List of cost models for resource usage.
            custom_plugins (list[CustomPluginProtocol]): List of custom plugins.
            event_bus (EventBus): Manages events and communication between components.
            stop_time (Optional[float]): The time until which the simulation will run. If None, runs indefinitely.
        """
        self.env = env
        self.allocator = allocator
        self.infra_manager = infra_manager
        self.registry = registry
        self.load_balancer = load_balancer
        self.workload_injector = workload_injector
        self.cost_models = cost_models
        self.custom_plugins = custom_plugins or []
        self.event_bus = event_bus

        self._stop_time = stop_time

        self._started = False
        self._run_completed = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stop_time(self) -> float | None:
        """The time until which the simulation runs. None means indefinite."""
        return self._stop_time

    # ------------------------------------------------------------------
    # Legacy constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls: type[Simulation], config_source: dict[str, Any]) -> Simulation:
        """Backward-compat: build via :class:`SimulationBuilder`."""
        from nuberu.core.simulation_builder import SimulationBuilder

        return SimulationBuilder(config_source).build()

    def _start_processes(self) -> None:
        """
        Starts all the necessary processes for the simulation.

        This method is called automatically when the Simulation instance is
        created, ensuring that all components are ready to run.

        This method is idempotent: if the simulation has already started, it does nothing.
        """
        if self._started:
            return
        self._started = True
        mode = (
            "drain"
            if getattr(self.infra_manager, "drain_pending_requests", True)
            else "hard-stop"
        )
        logger.info("Starting simulation processes (shutdown mode: %s)", mode)

        self.env.process(self.infra_manager.listen_allocator_instructions())
        # The Registry listens to infrastructure updates to update their container list
        self.env.process(self.registry._listener())
        # The WorkloadInjector is started automatically in their constructor when infrastructure is ready.
        # self.workload_injector.start()  # This method starts the injection process (a env.process() call)
        self.env.process(self.load_balancer.run())

        self.env.process(self.allocator.run())

        for cm in self.cost_models:
            if hasattr(cm, "run"):
                # Note: cost_models.run() starts a process that runs in the background
                # ToDo: This is a legacy feature, consider removing it in the future.
                cm.run()

        # Prepare and run custom plugins
        for plugin in self.custom_plugins:
            plugin.prepare()
            plugin.run()

        logger.info("Simulation setup complete.")

    def get_cost_breakdown(self) -> dict[str, float]:
        """
        Return a mapping from CostModel class name to its incurred cost.
        """
        return {cm.__class__.__name__: cm.get_total_cost() for cm in self.cost_models}

    def get_total_cost(self, print_breakdown: bool = True) -> float:
        """
        Print each cost models cost and the total, then return the total.
        If print_breakdown is False, only returns the total without printing.
        """
        breakdown = self.get_cost_breakdown()
        total = sum(breakdown.values())

        if print_breakdown:
            for name, cost in breakdown.items():
                logger.info(f"{name}: {cost}")
            logger.info(f"Total cost: ${total}")
        return total

    def run(self) -> None:
        """
        Starts the simulation and runs until stop_time.

        Simplified shutdown (RFC 004 Step 4):
        1. Run simulation until stop_time
        2. Publish END_SIMULATION event
        3. Shutdown all VMs (each Container handles its own drain mode)
        4. Flush any pending requests as LOST
        5. Process remaining events
        6. Generate final report

        Raises:
            RuntimeError: If run() is called more than once.
        """
        if self._run_completed:
            raise RuntimeError("Simulation.run() can only be called once")

        logger.info("Starting simulation...")
        self._start_processes()
        self._schedule_end_simulation()
        self._run_main_loop()
        self._execute_shutdown()
        self._finalize_simulation()

        self._run_completed = True
        logger.info("Simulation finished.")

    def _schedule_end_simulation(self) -> None:
        """
        Schedule END_SIMULATION event to be published at stop_time.

        This ensures processes waiting on END_SIMULATION (e.g. custom plugins)
        receive it while the environment is still running.
        """
        if self._stop_time is None:
            return

        async def _publish_end_at(t: float) -> None:
            delay = max(0.0, t - self.env.now)
            await self.env.timeout(delay)
            self.event_bus.publish(
                topic=EventTopic.END_SIMULATION,
                payload={"time": self.env.now},
                origin="Simulation",
            )

        self.env.process(_publish_end_at(self._stop_time))

    def _run_main_loop(self) -> None:
        """Run the simulation until stop_time (or indefinitely if None)."""
        if self._stop_time is None:
            self.env.run()
        else:
            self.env.run(until=self._stop_time)
        logger.info(f"Simulation stop_time reached at t={self.env.now}")

    async def _shutdown_sequence(self) -> None:
        """
        Execute graceful shutdown: stop infrastructure and flush pending requests.

        This runs inside the simulation loop so that events published by
        flush_lost_requests() can be processed by the async Monitor.
        """
        logger.info("Shutting down infrastructure...")
        # Triggers Drain or Hardstop depending on config
        await self.infra_manager.shutdown_all_vms()
        # Flush remaining pending requests as LOST
        self.workload_injector.flush_lost_requests()

    def _execute_shutdown(self) -> None:
        """
        Execute the shutdown sequence as an async process.

        Handles EmptySchedule gracefully - this can occur if all processes
        have already terminated before shutdown completes.
        """
        shutdown_proc = self.env.process(self._shutdown_sequence())
        try:
            self.env.run(until=shutdown_proc)
        except asimpy.core.EmptySchedule:
            # Expected if all processes terminated; log at debug level
            logger.debug(
                f"EmptySchedule during shutdown at t={self.env.now}. "
                f"Shutdown process alive: {shutdown_proc.is_alive}"
            )

        # Let asimpy process any remaining events naturally
        # After shutdown, there may be events in queues (e.g., from flush_lost_requests).
        # We let the scheduler run until no more events exist.
        try:
            self.env.run()
        except asimpy.core.EmptySchedule:
            pass  # Expected when no events remain

    def _finalize_simulation(self) -> None:
        """Finalize simulation: publish events, log costs, and finish plugins.

        1. Publish SIMULATION_FINISHED event (triggers cost models to publish COST_FINAL)
        2. Process remaining events in the scheduler
        3. Log cost summary (breakdown by cost model and total)
        4. Finish custom plugins (they may generate detailed reports)
        """
        # Step 1: Signal that simulation is finished, triggering cost models
        self.event_bus.publish(
            topic=EventTopic.SIMULATION_FINISHED,
            payload={"time": self.env.now},
            origin="Simulation",
        )
        logger.debug(f"Published SIMULATION_FINISHED at t={self.env.now}")

        # Step 2: Process reporting events (COST_FINAL from cost models, etc.)
        try:
            self.env.run()
        except asimpy.core.EmptySchedule:
            pass  # Expected when no events remain

        # Step 3: Get costs (already calculated by cost models) and log summary
        breakdown = self.get_cost_breakdown()
        total_cost = sum(breakdown.values())

        logger.debug("Cost breakdown (by cost model):")
        for name, cost in breakdown.items():
            logger.debug(f"  {name}: ${cost}")
        logger.debug(f"Total simulation cost: ${total_cost}")

        # Step 4: Finish custom plugins (they handle detailed reporting)
        for plugin in self.custom_plugins:
            plugin.finish()
