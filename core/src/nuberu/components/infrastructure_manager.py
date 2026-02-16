from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asimpy

from nuberu.core.infrastructure import ContainerClass
from nuberu.core.network_delays import VMNetworkConfig

from ..core.events import EventBus, EventTopic
from ..core.states import VMState
from .vm import VM

if TYPE_CHECKING:
    import asimpy

    from ..channels.channel import Channel
    from ..core.infrastructure import InstanceClass

logger = logging.getLogger(__name__)


class InfrastructureManager:
    """
    InfrastructureManager is responsible for managing the lifecycle of VMs.

    Responsibilities:
        - Execute VM and container operations based on Allocator instructions.
        - Ensure VM limits per instance class are respected.

    Args:
        env (asimpy.Environment): aSimPy environment for simulation.
        allocator_channel (Channel): Channel to receive Allocator instructions.
        event_bus (EventBus): Central bus for publishing system-wide events.
        runtime_model_factories (dict[str, callable]): Dictionary mapping app names to runtime model factory functions.
        eager_start (bool): If True, starts the InfrastructureManager immediately upon initialization.
        get_rps_cb (callable): Callback to obtain requests per second (RPS) for performance modeling.
    """

    env: asimpy.Environment
    vms: dict[str, VM]
    vm_count_by_ic: dict[InstanceClass, int]
    allocator_channel: Channel
    event_bus: EventBus
    runtime_model_factories: dict[str, callable]
    eager_start: bool = False
    vm_container_overhead: float = 0.0
    lb_to_vm_delay: float = 0.0
    lb_to_vm_delay_backward: float = 0.0
    vm_network_overrides: list[VMNetworkConfig]
    drain_pending_requests: bool = True
    drain_grace_period: float = 0.5

    def __init__(
        self,
        env: asimpy.Environment,
        allocator_channel: Channel,
        event_bus: EventBus,
        runtime_model_factories: dict[str, callable],
        get_rps_cb: callable,
        eager_start: bool = False,
        vm_container_overhead: float = 0.0,
        lb_to_vm_delay: float = 0.0,
        lb_to_vm_delay_backward: float = 0.0,
        vm_network_overrides: list[VMNetworkConfig] | None = None,
        drain_pending_requests: bool = True,
        drain_grace_period: float = 0.5,
    ) -> None:
        self.env = env
        self.allocator_channel = allocator_channel
        self.event_bus = event_bus
        self.vms: dict[str, VM] = {}
        self.vm_count_by_ic: dict[InstanceClass, int] = {}
        self.runtime_model_factories = runtime_model_factories
        self.get_rps_cb = get_rps_cb
        self.eager_start = eager_start
        self.vm_container_overhead = vm_container_overhead
        self.lb_to_vm_delay = lb_to_vm_delay
        self.lb_to_vm_delay_backward = lb_to_vm_delay_backward
        self.vm_network_overrides = vm_network_overrides or []
        self.drain_pending_requests = drain_pending_requests
        self.drain_grace_period = drain_grace_period

        # Build lookup dict for O(1) access to VM network overrides
        self._vm_delay_overrides: dict[str, VMNetworkConfig] = {
            override.name: override for override in self.vm_network_overrides
        }

        # This process is not started here, but in the Simulation component.
        # env.process(self._listen_allocator_instructions())

    def _get_lb_to_vm_delays(self, vm_id: str) -> tuple[float, float]:
        """Get forward and backward network delays for a specific VM.

        Args:
            vm_id: VM identifier to lookup.

        Returns:
            Tuple (forward_delay, backward_delay) in seconds.
        """
        # 1. Start with global defaults (already in seconds)
        fwd_s = self.lb_to_vm_delay
        bwd_s = (
            self.lb_to_vm_delay_backward if self.lb_to_vm_delay_backward > 0 else fwd_s
        )

        # 2. Check overrides
        if vm_id in self._vm_delay_overrides:
            override = self._vm_delay_overrides[vm_id]

            # Forward Override
            if override.network_delay is not None:
                fwd_s = override.network_delay / 1000.0
                # Implicit Symmetric: If forward is overridden, backward defaults to it
                # UNLESS explicitly overridden below.
                bwd_s = fwd_s

            # Backward Override
            if override.network_delay_backward is not None:
                bwd_s = override.network_delay_backward / 1000.0

            # Logging for overrides
            if (
                override.network_delay is not None
                or override.network_delay_backward is not None
            ):
                logger.info(
                    f"Using LB->VM delay OVERRIDE for VM '{vm_id}': "
                    f"FWD={fwd_s * 1000:.2f}ms, BWD={bwd_s * 1000:.2f}ms"
                )
                return fwd_s, bwd_s

        # Logging for global (only if non-zero)
        if fwd_s > 0 or bwd_s > 0:
            logger.info(
                f"Using global LB->VM delay for VM '{vm_id}': "
                f"FWD={fwd_s * 1000:.2f}ms, BWD={bwd_s * 1000:.2f}ms"
            )

        return fwd_s, bwd_s

    def start_vm(
        self,
        vm_id: str,
        instance_class: InstanceClass,
        container_creation_delay: int = 0,
    ) -> VM | None:
        """
        Starts a VM identified by vm_id. If the VM already exists and is stopped, restarts it.
        If the VM does not exist, creates a new VM and starts it.

        Args:
            vm_id (str): Identifier of the VM.
            instance_class (InstanceClass): The instance class type of the VM.


        Returns:
            VM | None: The created or restarted VM instance, or None if the limit is reached.
        """
        if vm_id in self.vms:
            vm = self.vms[vm_id]
            if vm.state not in {VMState.STOPPED, VMState.STOPPING}:
                vm.start()
                logger.info(f"Restarted existing VM {vm_id}.")
                return vm
            else:
                logger.warning(f"VM {vm_id} is already running or pending.")
                return None

        # If the VM does not exist, check limit before creating a new one.
        if self.vm_count_by_ic.get(instance_class, 0) >= instance_class.limit:
            logger.error(f"VM limit reached for instance class {instance_class.name}.")
            return None

        vm = VM(
            env=self.env,
            vm_id=vm_id,
            instance_class=instance_class,
            event_bus=self.event_bus,
            container_creation_delay=container_creation_delay,
        )
        self.vms[vm_id] = vm
        self.vm_count_by_ic[instance_class] = (
            self.vm_count_by_ic.get(instance_class, 0) + 1
        )
        vm.start()
        return vm

    async def stop_vm(self, vm_id: str) -> bool:
        """
        Stops the VM identified by vm_id, if it exists and is running.

        Args:
            vm_id (str): Identifier of the VM to stop.

        Returns:
            bool: True if the VM was stopped successfully, False otherwise.

        Note: This method is async to properly await VM shutdown coordination.
        """
        if vm_id in self.vms:
            vm = self.vms[vm_id]
            if vm.state not in {VMState.STOPPING, VMState.STOPPED}:
                await vm.shutdown()
                logger.info(f"VM {vm_id} stopped.")
                return True
            else:
                logger.warning(f"VM {vm_id} is not running.")
                return False
        else:
            logger.error(f"VM {vm_id} not found.")
            return False

    async def listen_allocator_instructions(self) -> None:
        """
        Coroutine that listens indefinitely for allocator instructions through the channel.
        """
        if self.eager_start:
            # --- Initial block at time 0 ---
            instructions = await self.allocator_channel.receive()
            self._publish_instruction_event(len(instructions))
            await self._process_instructions(instructions)

            # All VMs and containers for t=0 are now up:
            self.event_bus.publish(EventTopic.INFRASTRUCTURE_READY, payload={})
            logger.info("Published 'infrastructure_ready' event")

        # Continue processing further allocation blocks
        while True:
            instructions = await self.allocator_channel.receive()
            self._publish_instruction_event(len(instructions))
            await self._process_instructions(instructions)

    def _publish_instruction_event(self, num_instructions: int) -> None:
        """
        Log instructions received.

        Args:
            num_instructions (int): Number of instructions received.
        """
        logger.debug(f"Received instructions: {num_instructions}")

    async def _process_instructions(self, instructions: list[dict[str, dict]]) -> None:
        """
        Processes a list of allocator instructions.

        Args:
            instructions (list[dict[str, dict]]): List of instructions to process.
        """
        for instruction in instructions:
            action = instruction.get("action", "")
            data = instruction.get("data", {})

            logger.info(
                f"InfrastructureManager received instruction: {action} with data: {len(data)}",
            )

            if action == "start_vm":
                self.start_vm(
                    vm_id=data["vm_id"],
                    instance_class=data["instance_class"],
                    container_creation_delay=0,  # Default to no delay
                )
            elif action == "stop_vm":
                self.stop_vm(vm_id=data["vm_id"])
            elif action == "create_container":
                await self._create_container(data)
            elif action == "stop_container":
                self._stop_container(data)
            elif action == "remove_container":
                self._remove_container(data)
            else:
                logger.error(f"Unknown instruction received: {action}")

    async def _create_container(self, data: dict) -> None:
        """
        Handles the creation of a container.

        Args:
            data (dict): Data required to create the container.
        """
        vm = self.vms.get(data["vm_id"])
        if not vm:
            logger.error(f"VM {data['vm_id']} not found for container creation.")
            return

        cc: ContainerClass = data["container_class"]

        # Get the runtime model factory for this app
        app_name = cc.app.name
        runtime_model_factory = self.runtime_model_factories.get(app_name)
        if not runtime_model_factory:
            raise RuntimeError(
                f"No runtime model factory found for app '{app_name}'. "
                f"Available apps: {list(self.runtime_model_factories.keys())}"
            )

        await vm.create_container(
            container_id=data["container_id"],
            container_class=cc,
            image_name=data["image_name"],
            runtime_model_factory=runtime_model_factory,
            rps=self.get_rps_cb(cc.app, cc.cores, vm.instance_class),
            vm_container_overhead=self.vm_container_overhead,
            lb_to_vm_delays=self._get_lb_to_vm_delays(data["vm_id"]),
            drain_pending_requests=self.drain_pending_requests,
            drain_grace_period=self.drain_grace_period,
        )

    def _stop_container(self, data: dict) -> None:
        """
        Handles stopping a container.

        Args:
            data (dict): Data required to stop the container.
        """
        vm = self.vms.get(data["vm_id"])
        if not vm:
            logger.error(f"VM {data['vm_id']} not found for container stop.")
            return

        vm.stop_container(container_id=data["container_id"])

    def _remove_container(self, data: dict) -> None:
        """
        Handles removing a container.

        Args:
            data (dict): Data required to remove the container.
        """
        vm = self.vms.get(data["vm_id"])
        if not vm:
            logger.error(f"VM {data['vm_id']} not found for container removal.")
            return

        vm.remove_container(container_id=data["container_id"])

    def list_active_vms(self) -> list[VM]:
        """
        List all active VMs in the infrastructure manager.
        Returns:
            list[VM]: List of active VMs.
        """
        active_states = {
            VMState.PENDING,
            VMState.RUNNING,
        }
        return [vm for vm in self.vms.values() if vm.state in active_states]

    async def shutdown_all_vms(self) -> None:
        """
        Stops all active VMs in the infrastructure manager.
        Publishes an event for each VM stopped.

        Note: This method is async to properly await VM and container shutdown coordination.
        """
        active_vms = self.list_active_vms()
        if not active_vms:
            logger.info("No active VMs to stop.")
            return

        logger.info(f"IM -> stopping {len(active_vms)} VM(s) in parallel")
        procs = [self.env.process(vm.shutdown()) for vm in active_vms]
        try:
            await asimpy.AllOf(self.env, procs)
        except Exception as e:
            logger.warning(
                f"Exception while shutting down VMs ({type(e).__name__}): {e}"
            )

        logger.info("All active VMs have been stopped.")
