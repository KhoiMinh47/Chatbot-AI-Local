"""Health endpoint response contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class LivenessResponse(BaseModel):
    """Process-liveness response returned by every HTTP service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    service: NonBlankString
    version: NonBlankString


class DependencyStatusResponse(BaseModel):
    """One redacted dependency result suitable for an unauthenticated probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonBlankString
    status: Literal["ok", "unavailable", "unconfigured"]
    required_for_readiness: bool


class DependencyHealthResponse(BaseModel):
    """Aggregate dependency response used by diagnostics and readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "degraded"]
    ready: bool
    dependencies: tuple[DependencyStatusResponse, ...]
