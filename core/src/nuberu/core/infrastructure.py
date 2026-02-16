from dataclasses import dataclass

from ..plugins.hookspecs import ArrivalDistributionSpecs


@dataclass(frozen=True)
class App:
    """Represents an application."""

    name: str


@dataclass(frozen=True)
class InstanceClass:
    """Represents a type of VM instance with its resources.

    Attributes:
        name (str): Name of the instance type.
        cores (float): Number of CPU cores available.
        mem (float): Amount of memory in GB.
        price (float): Cost per unit time.
        limit (int): Maximum number of instances allowed.
    """

    name: str
    cores: float
    mem: float
    price: float
    limit: int  # Max. number of VMs of this instance class

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, InstanceClass):
            return False
        return (
            self.name == other.name
            and self.cores == other.cores
            and self.mem == other.mem
            and self.price == other.price
            and self.limit == other.limit
        )

    def __hash__(self) -> int:
        return hash((self.name, self.cores, self.mem, self.price, self.limit))


@dataclass(frozen=True)
class ContainerClass:
    """Represents a type of container with resource requirements.

    Attributes:
        name (str): Name of the container type.
        cores (float): CPU cores required by the container.
        mem (float): Memory required in GB.
        app (App): The application that runs inside the container.
    """

    name: str
    cores: float
    mem: float
    app: App

    def __eq__(self, other: object) -> bool:
        """
        Two ContainerClass objects are equal if their name, cores, mem, and app name match.
        """
        if not isinstance(other, ContainerClass):
            return False
        return (
            self.name == other.name
            and self.cores == other.cores
            and self.mem == other.mem
            and self.app.name == other.app.name
        )

    def __hash__(self) -> int:
        """
        Build a hash from name, cores, memory, and the app name.
        """
        return hash((self.name, self.cores, self.mem, self.app.name))


@dataclass(frozen=True)
class Family:
    """Represents a family of instance types, grouping multiple InstanceClasses.

    Attributes:
        name (str): Name of the instance family.
        ics (tuple[InstanceClass]): Tuple of instance types in the family.
    """

    name: str
    ics: tuple[InstanceClass]


@dataclass(frozen=True)
class Workload:
    """Represents a workload for an application over a time period.

    Attributes:
        app (App): The application generating the workload.
        distribution (ArrivalDistributionSpecs): Distribution of request arrivals.
    """

    app: App
    distribution: ArrivalDistributionSpecs


@dataclass(frozen=True)
class System:
    """Represents the overall cloud system configuration.

    Attributes:
        apps (tuple[App]): Tuple of applications in the system.
        ics (tuple[InstanceClass]): Available VM instance types.
        ccs (tuple[ContainerClass]): Available container types.
        families (tuple[Family] | None): Optional grouping of instance families.
    """

    apps: tuple[App]
    ics: tuple[InstanceClass]
    ccs: tuple[ContainerClass]
    families: tuple[Family] | None = None
