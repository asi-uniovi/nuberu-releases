from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..channels import DuplexChannel
    from ..components.container import Container

from ..workload.request import Request


class CostModelProtocol(Protocol):
    def run(self) -> None: ...
    def get_total_cost(self) -> float: ...


class RuntimeModelProtocol(Protocol):
    duplex_channel: (
        DuplexChannel  # Bidirectional channel for request/response communication
    )

    def can_enqueue(self, request: Request) -> bool:
        """Does this model accept (or enqueue) this request?"""
        ...

    def run(self) -> None:
        """Start the continuous execution process."""
        ...


class LoadBalancerProtocol(Protocol):
    def run(self) -> None:
        """Start the continuous execution process."""
        ...

    def select_container(self, request: Request) -> Container | None:
        """Returns the selected container for the given request."""
        ...


@runtime_checkable
class CustomPluginProtocol(Protocol):
    def prepare(self) -> None:
        """Called before the simulation starts."""
        ...

    def run(self) -> None:
        """Start the continuous execution process."""
        ...

    def finish(self) -> None:
        """Called after the simulation ends."""
        ...
