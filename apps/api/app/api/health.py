"""Process health endpoints."""

from typing import cast

from fastapi import APIRouter, Request, Response, status
from ntc_contracts import DependencyHealthResponse, DependencyStatusResponse, LivenessResponse

from app.application.get_dependency_health import GetDependencyHealth
from app.application.get_liveness import GetLiveness

router = APIRouter(tags=["health"])


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
)
async def get_liveness(request: Request) -> LivenessResponse:
    """Report that the API process can serve requests."""

    use_case = cast(GetLiveness, request.app.state.get_liveness)
    snapshot = use_case.execute()
    return LivenessResponse(
        status=snapshot.status,
        service=snapshot.service,
        version=snapshot.version,
    )


async def dependency_response(use_case: GetDependencyHealth) -> DependencyHealthResponse:
    """Map the use-case result without exposing adapter configuration."""

    health = await use_case.execute()
    return DependencyHealthResponse(
        status=health.status,
        ready=health.ready,
        dependencies=tuple(
            DependencyStatusResponse(
                name=dependency.name,
                status=dependency.status,
                required_for_readiness=dependency.required_for_readiness,
            )
            for dependency in health.dependencies
        ),
    )


@router.get("/health/dependencies", response_model=DependencyHealthResponse)
async def get_dependencies(request: Request) -> DependencyHealthResponse:
    """Return safe diagnostic state for configured infrastructure."""

    use_case = cast(GetDependencyHealth, request.app.state.get_dependency_health)
    return await dependency_response(use_case)


@router.get(
    "/health/ready",
    response_model=DependencyHealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": DependencyHealthResponse}},
)
async def get_readiness(request: Request, response: Response) -> DependencyHealthResponse:
    """Return 200 only when every required dependency, including LLM, is ready."""

    use_case = cast(GetDependencyHealth, request.app.state.get_dependency_health)
    result = await dependency_response(use_case)
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
