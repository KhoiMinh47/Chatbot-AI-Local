"""Dependency diagnostics and readiness use case."""

import asyncio
from collections.abc import Sequence
from typing import Literal, Protocol

from app.domain.health import DependencyHealthSnapshot, DependencySnapshot, DependencyState


class DependencyProbe(Protocol):
    """Port implemented by infrastructure-specific health probes."""

    @property
    def name(self) -> str:
        """Stable, non-sensitive dependency name."""

    @property
    def required_for_readiness(self) -> bool:
        """Whether a failed probe closes API readiness."""

    @property
    def configured(self) -> bool:
        """Return whether the dependency has enough configuration to probe."""

    async def check(self) -> bool:
        """Return true only after a real dependency round trip."""


class GetDependencyHealth:
    """Aggregate dependency probes without leaking their failure details."""

    def __init__(self, probes: Sequence[DependencyProbe], timeout_seconds: float = 2.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("dependency probe timeout must be positive")
        self._probes = tuple(probes)
        self._timeout_seconds = timeout_seconds

    async def execute(self) -> DependencyHealthSnapshot:
        """Probe configured dependencies concurrently and calculate readiness."""

        results = await asyncio.gather(
            *(self._safe_check(probe) for probe in self._probes),
        )
        ready = all(
            dependency.status == "ok" for dependency in results if dependency.required_for_readiness
        )
        status: Literal["ok", "degraded"] = (
            "ok" if all(dependency.status == "ok" for dependency in results) else "degraded"
        )
        return DependencyHealthSnapshot(
            status=status,
            ready=ready,
            dependencies=tuple(results),
        )

    async def _safe_check(self, probe: DependencyProbe) -> DependencySnapshot:
        if not probe.configured:
            state: DependencyState = "unconfigured"
        else:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    state = "ok" if await probe.check() else "unavailable"
            except Exception:  # Health responses intentionally suppress adapter details.
                state = "unavailable"
        return DependencySnapshot(
            name=probe.name,
            status=state,
            required_for_readiness=probe.required_for_readiness,
        )
