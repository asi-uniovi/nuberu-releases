from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import asimpy

from ..channels.duplex_channel import DuplexChannel
from ..core.events import Event, EventTopic
from ..core.states import ContainerState, VMState
from ..utils.helpers import notify_event
from .container import Container

if TYPE_CHECKING:
    import asimpy

    from ..core.events import EventBus
    from ..core.infrastructure import ContainerClass, InstanceClass
    from ..interfaces.protocols import RuntimeModelProtocol

logger = logging.getLogger(__name__)


class VM:
    """
    VM represents a Virtual Machine (VM) that can manage multiple containers.

    Args:
        env (asimpy.Environment): aSimPy environment for simulation.
        vm_id (str): Unique identifier for the virtual machine.
        instance_class (InstanceClass): The instance type of the VM.
    """

    env: asimpy.Environment
    vm_id: str
    instance_class: InstanceClass
    images: set[str]
    state: VMState
    containers: dict[str, Container]
    event_bus: EventBus

    def __init__(
        self,
        env: asimpy.Environment,
        vm_id: str,
        instance_class: InstanceClass,
        event_bus: EventBus,
        container_creation_delay: int = 1,
    ):
        self.env = env
        self.vm_id = vm_id
        self.instance_class = instance_class
        self.event_bus = event_bus
        self.images: set[str] = set()  # Set of images that the VM has
        self.state: VMState = VMState.PENDING
        self.containers: dict[
            str, Container
        ] = {}  # dict of containers running on the VM

        self.CONTAINER_CREATION_DELAY = container_creation_delay

        # Event queue for listening to container lifecycle events
        self._event_queue: asimpy.Store = asimpy.Store(env)
        self.event_bus.subscribe(EventTopic.CONTAINER_STOPPED, self._event_queue)

    @property
    def cpu(self) -> float:
        """Returns the CPU capacity of the VM based on its InstanceClass."""
        return self.instance_class.cores

    @property
    def memory(self) -> float:
        """Returns the memory capacity of the VM based on its InstanceClass."""
        return self.instance_class.mem

    @property
    def available_cpu(self) -> float:
        """Returns the available CPU in the VM, considering the assigned containers."""
        used_cpu = sum(container.cpu for container in self.containers.values())
        return self.cpu - used_cpu

    @property
    def available_memory(self) -> float:
        """Returns the available memory in the VM, considering the assigned containers."""
        used_memory = sum(container.memory for container in self.containers.values())
        return self.memory - used_memory

    def start(self) -> None:
        """
        Start the VM.
        """
        self.state = VMState.RUNNING
        logger.info(f"[VM {self.vm_id}] VM started.")
        # Start listener for container lifecycle events
        self.env.process(self._container_lifecycle_listener())
        self.event_bus.publish(
            topic=EventTopic.VM_STARTED,
            payload={
                "vm": self,
                "vm_id": self.vm_id,
                "time": self.env.now,
            },
            origin=self.vm_id,
        )

    async def _container_lifecycle_listener(self) -> None:
        """
        Listen for container lifecycle events and manage the containers dict.

        This makes VM responsible for its own container list, rather than
        having containers modify the VM's internal state directly.
        """
        while True:
            event: Event = await self._event_queue.get()
            # Only process events for containers belonging to this VM
            if event.payload.get("vm_id") != self.vm_id:
                continue

            container = event.payload.get("container")
            if container is None:
                continue

            if event.topic == EventTopic.CONTAINER_STOPPED:
                self.deregister_container(container)

    def register_container(self, container: Container) -> None:
        """
        Register a new container on the VM and start it.
        Assign the container to the VM.

        This method checks if the container is already registered, and if not, it registers it.

        Args:
            container (Container): Container to register.
        """
        if container in self.containers:
            logger.warning(
                f"[VM {self.vm_id}] Container {container.container_id} already registered."
            )
            return

        self.containers[container.container_id] = container
        container.assign_vm(self)
        logger.debug(
            f"[VM {self.vm_id}] Container {container.container_id} registered."
        )

        logger.info(
            f"[VM {self.vm_id}] Registered container {container.container_id}. Starting container..."
        )
        container.start()

    def deregister_container(self, container: Container) -> None:
        """
        Deregister a container from the VM.

        Args:
            container (Container): Container to deregister.
        """
        if container.container_id in self.containers.keys():
            self.containers.pop(container.container_id)

            logger.info(
                f"[VM {self.vm_id}] Deregistered container {container.container_id}."
            )
            # TBD: Stop container (?)
        else:
            logger.warning(
                f"[VM {self.vm_id}] Container {container.container_id} not found."
            )

    async def create_container(
        self,
        container_id: str,
        container_class: ContainerClass,
        rps: float,
        image_name: str,
        runtime_model_factory: Callable[
            [
                asimpy.Environment,
                Container,
                float,
                EventBus,
                DuplexChannel,
                asimpy.Store,
                asimpy.Store,
            ],
            RuntimeModelProtocol,
        ],
        vm_container_overhead: float = 0.0,
        lb_to_vm_delays: tuple[float, float] = (0.0, 0.0),
        drain_pending_requests: bool = True,
        drain_grace_period: float = 0.5,
    ) -> None:
        """
        Create a new container on the VM.

        This method checks if the VM has enough resources to create the container and if the container already exists.
        If the container is created successfully, it registers the container.

        Args:
            container_id (str): Unique identifier for the container.
            container_class (ContainerClass): Class of the container to be created.
            rps (float): Requests per second for the container.
            image_name (str): Name of the image to be used for the container.
            runtime_model_factory (Callable): Factory function that creates runtime model instances.
            vm_container_overhead (float): Container startup overhead in seconds (from network_delays config).

        Returns:
            Container | None: The created container or None if the container could not be created.
        """
        if container_id in self.containers:
            logger.warning(
                f"[VM {self.vm_id}] Container {container_id} already exists.",
            )

        if (
            self.available_cpu < container_class.cores
            or self.available_memory < container_class.mem
        ):
            logger.error(
                f"[VM {self.vm_id}] Not enough resources to launch container {container_id}.",
            )

        container = Container(
            env=self.env,
            container_id=container_id,
            container_class=container_class,
            vm=self,
            runtime_model_factory=runtime_model_factory,
            image_name=image_name,
            rps=rps,
            event_bus=self.event_bus,
            vm_container_overhead=vm_container_overhead,
            drain_pending_requests=drain_pending_requests,
            drain_grace_period=drain_grace_period,
        )

        # Create DuplexChannel for Container <-> LoadBalancer communication
        # Forward: LoadBalancer -> Container (requests with lb_to_vm delay)
        # Backward: Container -> LoadBalancer (responses with lb_to_vm delay)
        # This will be registered with LoadBalancer via CONTAINER_READY event
        fwd_delay, bwd_delay = lb_to_vm_delays
        container.lb_duplex_channel = DuplexChannel(
            env=self.env,
            forward_delay=fwd_delay,
            backward_delay=bwd_delay,
        )

        await self.env.timeout(
            self.CONTAINER_CREATION_DELAY
        )  # Simulate container creation time

        self.containers[container_id] = container
        self.register_container(container)
        logger.info(f"[VM {self.vm_id}] Container {container_id} started.")

    def stop_container(self, container_id: str) -> None | Container:
        """
        Stop a container on the VM.

        This method checks if the container exists and stops it.

        Args:
            container_id (str): Unique identifier for the container to be stopped.

        Returns:
            Container | None: The stopped container or None if the container was not found or not running.
        """
        container = self.containers.get(container_id)

        if container and container.state == ContainerState.RUNNING:
            container.stop()
            logger.info(f"Container {container_id} stopped.")
            return container
        else:
            logger.warning(f"Container {container_id} not found or not running.")
            return None

    def remove_container(self, container_id: str) -> None | Container:
        """
        Remove a container from the VM.
        This method checks if the container exists and removes it from the VM. It also stops the container if it is running.

        Args:
            container_id (str): Unique identifier for the container to be removed.

        Returns:
            Container | None: The removed container or None if the container was not found.
        """
        container = self.containers.get(container_id)
        if not container:
            logger.warning(
                f"[VM {self.vm_id}] Container {container_id} not found for removal."
            )
            return None

        if container.state == ContainerState.RUNNING:
            container.stop()

        notify_event(
            event_bus=self.event_bus,
            topic=EventTopic.CONTAINER_REMOVED,
            origin=self.vm_id,
            obj=container,
            env=self.env,
        )

        self.deregister_container(container)

        logger.info(f"[VM {self.vm_id}] Container {container_id} removed.")

        return container

    async def update_usage(self, cpu_change: float, memory_change: float) -> bool:
        """
        Update the usage of CPU and memory based on container allocations.

        Args:
            cpu_change (float): Amount of CPU to allocate (negative to release).
            memory_change (float): Amount of memory to allocate (negative to release).

        Returns:
            bool: True if the update was successful, False if it exceeded limits.
        """
        # logger.info(
        #     f"--------> Ejecutando update_usage en VM {self.vm_id} (C:{cpu_change}, M:{memory_change})"
        # )
        used_cpu = (
            sum(container.cpu for container in self.containers.values()) + cpu_change
        )
        used_memory = (
            sum(container.memory for container in self.containers.values())
            + memory_change
        )

        if used_cpu > self.cpu or used_memory > self.memory:
            logger.error(f"VM {self.vm_id} exceeded resource limits.")
            return False

        # logger.info(f"VM {self.vm_id} resource update -> CPU: {used_cpu}/{self.cpu}, Memory: {used_memory}/{self.memory}")
        return True

    def add_image(self, image_name: str) -> None:
        """Add a new image to the VM."""
        if image_name not in self.images:
            logger.info(f"[VM {self.vm_id}] Adding image: {image_name}")
            self.images.add(image_name)

    def has_image(self, image_name: str) -> bool:
        """Check if the VM has the required image."""
        return image_name in self.images

    def __repr__(self) -> str:
        return f"VM(id={self.vm_id} [{self.state.value}], cpu={self.available_cpu}/{self.cpu}, memory={self.available_memory}/{self.memory}, images={self.images}). IC: {self.instance_class}"

    async def shutdown(self) -> None:
        """
        Shut down the VM and all its containers.

        Note: This method is async to properly await container shutdown coordination.
        The VM_STOPPED event is published AFTER all containers have stopped,
        ensuring cost models calculate the correct duration including drain time.
        """
        self.state = VMState.STOPPING

        # Shut down all containers in parallel to avoid serializing drain time
        containers = list(self.containers.values())
        if containers:
            procs = [self.env.process(c.stop()) for c in containers]
            try:
                await asimpy.AllOf(self.env, procs)
            except Exception as e:
                logger.warning(
                    f"[VM {self.vm_id}] container shutdown exception ({type(e).__name__}): {e}"
                )
        logger.info(f"[VM {self.vm_id}] All containers stopped.")

        self.state = VMState.STOPPED

        # CRITICAL: Publish VM_STOPPED AFTER containers have finished draining
        # This ensures cost models calculate duration including drain time
        self.event_bus.publish(
            topic=EventTopic.VM_STOPPED,
            payload={
                "vm": self,
                "vm_id": self.vm_id,
                "time": self.env.now,
            },
            origin=self.vm_id,
        )

        logger.info(f"[VM {self.vm_id}] VM shut down.")

    def _to_dict(self) -> dict[str, object]:
        """
        Convert the VM instance to a dictionary representation.
        This is useful for serialization or logging purposes.

        Returns:
            dict: Dictionary representation of the VM.
        """
        return {
            "vm_id": self.vm_id,
            "state": self.state.value,
            "cpu": self.cpu,
            "available_cpu": self.available_cpu,
            "memory": self.memory,
            "available_memory": self.available_memory,
            "images": list(self.images),
            "instance_class": str(self.instance_class),
        }
