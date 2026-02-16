from enum import Enum

"""
Note:
    There is a potential issue with overlapping state values across different Enums, such as "RUNNING" being present in both `VMState` and `ContainerState`. 

    When serializing to YAML or JSON, Enums are  converted to their string values (e.g., `ContainerState.RUNNING` becomes "RUNNING" and the same applies to `VMState.RUNNING`). This could lead to ambiguity during deserialization, as it would be unclear whether the state originated 
    from a VM or a Container.
"""


class RequestState(str, Enum):
    """Possible states of a request.
    GENERATED: Request has been generated (initial state)
    REJECTED: Request has been rejected
    COMPLETED: Request has been completed
    LOST: Request has been lost (e.g., due to timeout or failure)

    Note: Intermediate states (ACCEPTED, ASSIGNED, PROCESSING) are tracked
    via the request's timeline attribute instead of explicit states.
    """

    GENERATED = "GENERATED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    LOST = "LOST"


class VMState(str, Enum):
    """Possible states of a VM.
    PENDING: VM is being initialized
    RUNNING: VM is running and active
    STOPPING: VM is in the process of stopping
    STOPPED: VM has been stopped
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class ContainerState(str, Enum):
    """Possible states of a container.
    CREATED: Container has been created but not started
    RUNNING: Container is currently running
    STOPPING: Container is stopping
    STOPPED: Container has been stopped
    IDLE: Container is running but not handling any load
    """

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    IDLE = "IDLE"
