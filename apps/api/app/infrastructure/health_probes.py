"""Bounded, read-only health probes for Phase 2 infrastructure."""

import math
from dataclasses import dataclass

import httpx2 as httpx
import psycopg
from pydantic import AnyHttpUrl, SecretStr
from redis.asyncio import Redis

from app.application.get_dependency_health import DependencyProbe
from app.core.settings import ApiSettings


@dataclass(frozen=True, slots=True)
class UnconfiguredProbe:
    """Explicitly represent a required dependency deferred to a later phase."""

    name: str
    required_for_readiness: bool

    @property
    def configured(self) -> bool:
        return False

    async def check(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PostgresProbe:
    name: str
    required_for_readiness: bool
    host: str | None
    port: int
    database: str
    user: str
    password: SecretStr | None
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return self.host is not None and self.password is not None

    async def check(self) -> bool:
        if self.host is None or self.password is None:
            return False
        connection = await psycopg.AsyncConnection.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password.get_secret_value(),
            connect_timeout=math.ceil(self.timeout_seconds),
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                row = await cursor.fetchone()
                return row == (1,)
        finally:
            await connection.close()


@dataclass(frozen=True, slots=True)
class RedisProbe:
    name: str
    required_for_readiness: bool
    host: str | None
    port: int
    password: SecretStr | None
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return self.host is not None and self.password is not None

    async def check(self) -> bool:
        if self.host is None or self.password is None:
            return False
        client = Redis(
            host=self.host,
            port=self.port,
            password=self.password.get_secret_value(),
            socket_connect_timeout=self.timeout_seconds,
            socket_timeout=self.timeout_seconds,
        )
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()


@dataclass(frozen=True, slots=True)
class HttpProbe:
    name: str
    required_for_readiness: bool
    url: AnyHttpUrl | None
    timeout_seconds: float
    username: str | None = None
    password: SecretStr | None = None

    @property
    def configured(self) -> bool:
        credentials_complete = (self.username is None) == (self.password is None)
        return self.url is not None and credentials_complete

    async def check(self) -> bool:
        if not self.configured or self.url is None:
            return False
        auth = None
        if self.username is not None and self.password is not None:
            auth = (self.username, self.password.get_secret_value())
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.get(str(self.url), auth=auth)
        return response.status_code == 200


def build_dependency_probes(settings: ApiSettings) -> tuple[DependencyProbe, ...]:
    """Compose the Phase 2 probes; active LLM remains unconfigured until Phase 3."""

    llm_probe: DependencyProbe
    if settings.llm_health_url is None:
        llm_probe = UnconfiguredProbe(name="llm", required_for_readiness=True)
    else:
        llm_probe = HttpProbe(
            name="llm",
            required_for_readiness=True,
            url=settings.llm_health_url,
            timeout_seconds=settings.dependency_timeout_seconds,
        )

    return (
        PostgresProbe(
            name="postgres",
            required_for_readiness=True,
            host=settings.database_host,
            port=settings.database_port,
            database=settings.database_name,
            user=settings.database_user,
            password=settings.database_password,
            timeout_seconds=settings.dependency_timeout_seconds,
        ),
        RedisProbe(
            name="redis",
            required_for_readiness=True,
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            timeout_seconds=settings.dependency_timeout_seconds,
        ),
        HttpProbe(
            name="qdrant",
            required_for_readiness=True,
            url=settings.qdrant_health_url,
            timeout_seconds=settings.dependency_timeout_seconds,
        ),
        HttpProbe(
            name="rabbitmq",
            required_for_readiness=False,
            url=settings.rabbitmq_health_url,
            timeout_seconds=settings.dependency_timeout_seconds,
            username=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
        ),
        HttpProbe(
            name="minio",
            required_for_readiness=False,
            url=settings.minio_health_url,
            timeout_seconds=settings.dependency_timeout_seconds,
        ),
        llm_probe,
    )
