from __future__ import annotations

import pickle
from typing import TYPE_CHECKING, TypeVar

import asimpy

from ..core.events import EventBus, EventTopic

if TYPE_CHECKING:
    from ..components.container import Container
    from ..components.vm import VM

T = TypeVar("T")


def load_pickle_file(pickle_path: str, expected_type: type[T]) -> T:
    """
    Loads a pickle file and validates its type.

    Args:
        pickle_path (str): The path to the pickle file.
        expected_type (Type[T]): The expected type of the deserialized object.

    Returns:
        T: The deserialized object of the expected type.

    Raises:
        TypeError: If the deserialized object is not of the expected type.
    """
    with open(pickle_path, "rb") as f:
        data = pickle.load(f)

    if not isinstance(data, expected_type):
        raise TypeError(f"Expected {expected_type.__name__}, got {type(data).__name__}")

    return data


def time_unit_to_seconds(time_unit: str) -> int:
    """Convert time units to seconds"""
    conversion_factors = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    return conversion_factors.get(time_unit, 1)


def build_payload(obj: VM | Container, env: asimpy.Environment) -> dict:
    """
    Build a payload dictionary based on the type of object (VM or Container).

    Args:
        obj (VM | Container): The object to build the payload for.
        env (asimpy.Environment): The simulation environment to get the current time.

    Returns:
        dict: A dictionary containing the payload information.
    """
    # Importing here to avoid circular import issues
    from ..components.container import Container
    from ..components.vm import VM

    match obj:
        case VM():
            return {
                "vm": obj,
                "vm_id": obj.vm_id,
                "instance_class": obj.instance_class.name,
                "time": env.now,
            }
        case Container():
            return {
                "container": obj,
                "container_id": obj.container_id,
                "app_name": obj.app.name,
                "vm_id": obj.vm.vm_id,
                "time": env.now,
            }
        case _:
            raise ValueError(f"Unknown event object: {obj}")


def notify_event(
    event_bus: EventBus,
    topic: EventTopic,
    origin: str,
    obj: VM | Container,
    env: asimpy.Environment,
) -> None:
    """
    Notifies the event bus about a specific event related to a VM or Container.

    Args:
        event_bus (EventBus): The event bus to publish the event to.
        topic (EventTopic): The type of event to notify.
        origin (str): The origin of the event.
        obj (VM | Container): The object related to the event.
    """
    payload = build_payload(obj, env)
    event_bus.publish(topic=topic, payload=payload, origin=origin)
