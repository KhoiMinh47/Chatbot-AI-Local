"""Stable contracts shared across process boundaries."""

from ntc_contracts.health import (
    DependencyHealthResponse,
    DependencyStatusResponse,
    LivenessResponse,
)

__all__ = ["DependencyHealthResponse", "DependencyStatusResponse", "LivenessResponse"]
