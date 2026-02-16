import logging

import asimpy

from ..core.events import Event, EventBus, EventTopic
from .container import Container

logger = logging.getLogger(__name__)


class Registry:
    """
    Registry maintains the mapping between applications and the containers that serve them.

    It listens to infrastructure updates (via a Channel) to stay synchronized with the running containers.
    It acts as a service discovery mechanism that the LoadBalancer can query at any time.

    Args:
        env (asimpy.Environment): The simulation environment.
        event_bus (EventBus): Central bus for publishing system-wide events.
    """

    env: asimpy.Environment
    event_bus: EventBus
    apps_to_containers: dict[str, list[Container]]
    queue: asimpy.Store

    def __init__(
        self,
        env: asimpy.Environment,
        event_bus: EventBus,
    ) -> None:
        self.env = env
        self.event_bus = event_bus
        self.apps_to_containers: dict[str, list[Container]] = {}
        self._draining_containers: set[str] = set()  # Containers in drain mode
        self.queue: asimpy.Store = asimpy.Store(env)

        # Subscribe to relevant topics
        self.event_bus.subscribe(EventTopic.CONTAINER_READY, self.queue)
        self.event_bus.subscribe(EventTopic.CONTAINER_DRAINING, self.queue)
        self.event_bus.subscribe(EventTopic.CONTAINER_REMOVED, self.queue)

    async def _listener(self) -> None:
        """
        Listen for events from the event bus and update the registry accordingly.
        """
        while True:
            event: Event = await self.queue.get()
            container: Container | None = None
            container_obj: object = event.payload.get("container")
            if isinstance(container_obj, Container):
                container = container_obj
            if not container:
                continue

            if event.topic == EventTopic.CONTAINER_READY:
                self.register(container)
            elif event.topic == EventTopic.CONTAINER_DRAINING:
                self.mark_draining(container)
            elif event.topic == EventTopic.CONTAINER_REMOVED:
                self.deregister(container)

    def register(self, container: Container) -> None:
        """
        Register a container as available for the specified application.

        Args:
            container (Container): Container instance to register.
        """
        self.apps_to_containers.setdefault(container.app.name, []).append(container)
        logger.info(
            f"Registered container {container.container_id} for app {container.app.name}",
        )
        logger.debug("Current registry state:")
        for app_name, containers in self.apps_to_containers.items():
            logger.debug(
                f"\tApp '{app_name}' has {len(containers)} containers registered."
            )

    def mark_draining(self, container: Container) -> None:
        """
        Mark a container as draining (stops receiving new requests but continues processing pending ones).

        Args:
            container (Container): Container instance entering drain mode.
        """
        container_id = container.container_id
        self._draining_containers.add(container_id)
        logger.info(
            f"Marked container {container_id} as DRAINING for app {container.app.name}",
        )

    def deregister(self, container: Container) -> None:
        """
        Remove a container from the registry.

        Args:
            container (Container): Container instance to remove.
        """
        container_id = container.container_id
        app_name = container.app.name

        # Remove from draining set if present
        self._draining_containers.discard(container_id)

        if app_name in self.apps_to_containers:
            original_len = len(self.apps_to_containers[app_name])
            self.apps_to_containers[app_name] = [
                c
                for c in self.apps_to_containers[app_name]
                if c.container_id != container_id
            ]
            if len(self.apps_to_containers[app_name]) < original_len:
                logger.info(
                    f"Deregistered container {container_id} from app {app_name}",
                )
            else:
                logger.warning(
                    f"Container {container_id} not found in registry for app {app_name}",
                )

    def get_containers(self, app_name: str) -> list[Container]:
        """
        Retrieve the list of containers registered for a given application.

        Automatically filters out containers in drain mode (can process pending
        requests but should not receive new ones).

        Args:
            app_name (str): Application name.

        Returns:
            list[Container]: List of active (non-draining) containers for the app.
        """
        all_containers = self.apps_to_containers.get(app_name, [])
        # Filter out draining containers
        return [
            c for c in all_containers if c.container_id not in self._draining_containers
        ]
