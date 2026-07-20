"""Framework-independent service health values."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """Identity exposed by process health endpoints."""

    name: str
    version: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("service name must not be blank")
        if not self.version.strip():
            raise ValueError("service version must not be blank")


@dataclass(frozen=True, slots=True)
class LivenessSnapshot:
    """Framework-independent output of the liveness use case."""

    status: Literal["ok"]
    service: str
    version: str


DependencyState = Literal["ok", "unavailable", "unconfigured"]


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    """Safe dependency state without URLs, credentials, or exception details."""

    name: str
    status: DependencyState
    required_for_readiness: bool


@dataclass(frozen=True, slots=True)
class DependencyHealthSnapshot:
    """Aggregate state for dependency diagnostics and readiness."""

    status: Literal["ok", "degraded"]
    ready: bool
    dependencies: tuple[DependencySnapshot, ...]
