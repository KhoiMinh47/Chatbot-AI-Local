"""Liveness use case."""

from app.domain.health import LivenessSnapshot, ServiceIdentity


class GetLiveness:
    """Read process-local health without probing external dependencies."""

    def __init__(self, identity: ServiceIdentity) -> None:
        self._identity = identity

    def execute(self) -> LivenessSnapshot:
        """Return a stable snapshot for the live process."""

        return LivenessSnapshot(
            status="ok",
            service=self._identity.name,
            version=self._identity.version,
        )
