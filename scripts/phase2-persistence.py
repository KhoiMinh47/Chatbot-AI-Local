"""Seed and verify restart-persistence sentinels in Phase 2 datastores."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import httpx2 as httpx
import psycopg
from kombu import Connection, Exchange, Producer, Queue
from minio import Minio
from redis import Redis


class PersistenceStageError(RuntimeError):
    """A redacted failure that identifies only the datastore stage."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"Phase 2 persistence stage failed: {stage}")
        self.stage = stage


@contextmanager
def datastore_stage(name: str) -> Iterator[None]:
    """Preserve a safe stage name while suppressing credential-bearing errors."""

    try:
        yield
    except PersistenceStageError:
        raise
    except Exception as error:
        raise PersistenceStageError(name) from error


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required non-secret environment is missing: {name}")
    return value


def secret(name: str) -> str:
    path = Path(required(name))
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"unable to read secret file for {name}") from error
    if not value:
        raise RuntimeError(f"secret file for {name} is empty")
    return value


def postgres_connection() -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=required("PHASE2_POSTGRES_HOST"),
        dbname=required("PHASE2_POSTGRES_DB"),
        user=required("PHASE2_POSTGRES_USER"),
        password=secret("PHASE2_POSTGRES_PASSWORD_FILE"),
        connect_timeout=5,
    )


def redis_client() -> Redis:
    return Redis(
        host=required("PHASE2_REDIS_HOST"),
        port=6379,
        password=secret("PHASE2_REDIS_PASSWORD_FILE"),
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


def rabbit_connection() -> Connection:
    return Connection(
        hostname=required("PHASE2_RABBITMQ_HOST"),
        port=5672,
        userid=required("PHASE2_RABBITMQ_USER"),
        password=secret("PHASE2_RABBITMQ_PASSWORD_FILE"),
        virtual_host="/",
        connect_timeout=5,
    )


def minio_client() -> Minio:
    return Minio(
        f"{required('PHASE2_MINIO_HOST')}:9000",
        access_key=required("PHASE2_MINIO_USER"),
        secret_key=secret("PHASE2_MINIO_PASSWORD_FILE"),
        secure=False,
    )


def qdrant_request(method: str, path: str, *, json: object | None = None) -> httpx.Response:
    url = f"http://{required('PHASE2_QDRANT_HOST')}:6333{path}"
    response = httpx.request(method, url, timeout=5, json=json, trust_env=False)
    response.raise_for_status()
    return response


def rabbit_body_matches_marker(body: object, marker: str) -> bool:
    """Normalize Kombu transports that expose JSON text or raw bytes."""

    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return False
    if isinstance(body, str):
        with suppress(json.JSONDecodeError):
            body = json.loads(body)
    return body == marker


def seed(marker: str) -> None:
    with datastore_stage("postgres-seed"), postgres_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app.phase2_acceptance_probe (
                marker text PRIMARY KEY,
                created_at timestamptz NOT NULL DEFAULT current_timestamp
            )
            """
        )
        connection.execute(
            "INSERT INTO app.phase2_acceptance_probe (marker) VALUES (%s)",
            (marker,),
        )

    with datastore_stage("redis-seed"):
        redis = redis_client()
        try:
            redis.set(f"phase2:acceptance:{marker}", marker)
        finally:
            redis.close()

    with datastore_stage("rabbitmq-seed"):
        queue_name = f"phase2.acceptance.{marker}"
        with rabbit_connection() as connection:
            channel = connection.channel()
            queue = Queue(queue_name, exchange=Exchange("", type="direct"), routing_key=queue_name)
            queue(channel).declare()
            Producer(channel).publish(
                marker,
                exchange="",
                routing_key=queue_name,
                delivery_mode=2,
                serializer="json",
                declare=[queue],
            )
            channel.close()

    with datastore_stage("minio-seed"):
        bucket = "phase2-acceptance"
        object_name = f"{marker}.txt"
        client = minio_client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        payload = marker.encode()
        client.put_object(bucket, object_name, io.BytesIO(payload), len(payload))

    with datastore_stage("qdrant-seed"):
        collection = f"phase2_acceptance_{marker.replace('-', '_')}"
        qdrant_request(
            "PUT",
            f"/collections/{collection}",
            json={"vectors": {"size": 1, "distance": "Cosine"}},
        )
        qdrant_request(
            "PUT",
            f"/collections/{collection}/points?wait=true",
            json={"points": [{"id": 1, "vector": [1.0], "payload": {"marker": marker}}]},
        )
    time.sleep(2)


def verify_and_cleanup(marker: str) -> None:
    queue_name = f"phase2.acceptance.{marker}"
    bucket = "phase2-acceptance"
    object_name = f"{marker}.txt"
    collection = f"phase2_acceptance_{marker.replace('-', '_')}"

    # Verify every datastore before mutating any sentinel. A failed verification
    # can therefore be retried after the underlying service is repaired.
    with datastore_stage("postgres-verify"), postgres_connection() as connection:
        row = connection.execute(
            "SELECT marker FROM app.phase2_acceptance_probe WHERE marker = %s",
            (marker,),
        ).fetchone()
        if row != (marker,):
            raise RuntimeError("sentinel is missing")

    with datastore_stage("redis-verify"):
        redis = redis_client()
        try:
            if redis.get(f"phase2:acceptance:{marker}") != marker:
                raise RuntimeError("sentinel is missing")
        finally:
            redis.close()

    with datastore_stage("rabbitmq-verify"), rabbit_connection() as connection:
        channel = connection.channel()
        message = channel.basic_get(queue=queue_name, no_ack=False)
        if message is None or not rabbit_body_matches_marker(message.body, marker):
            raise RuntimeError("sentinel is missing or changed")
        channel.basic_reject(message.delivery_tag, requeue=True)
        channel.close()

    with datastore_stage("minio-verify"):
        client = minio_client()
        response = client.get_object(bucket, object_name)
        try:
            if response.read().decode() != marker:
                raise RuntimeError("sentinel changed")
        finally:
            response.close()
            response.release_conn()

    with datastore_stage("qdrant-verify"):
        point = qdrant_request("GET", f"/collections/{collection}/points/1").json()
        if point.get("result", {}).get("payload", {}).get("marker") != marker:
            raise RuntimeError("sentinel is missing")

    cleanup_failures: list[str] = []

    def cleanup(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except Exception:
            cleanup_failures.append(name)

    def cleanup_postgres() -> None:
        with postgres_connection() as connection:
            connection.execute(
                "DELETE FROM app.phase2_acceptance_probe WHERE marker = %s",
                (marker,),
            )
            connection.execute("DROP TABLE IF EXISTS app.phase2_acceptance_probe")

    def cleanup_redis() -> None:
        redis = redis_client()
        try:
            redis.delete(f"phase2:acceptance:{marker}")
        finally:
            redis.close()

    def cleanup_rabbitmq() -> None:
        with rabbit_connection() as connection:
            channel = connection.channel()
            message = channel.basic_get(queue=queue_name, no_ack=False)
            if message is not None:
                channel.basic_ack(message.delivery_tag)
            channel.queue_delete(queue=queue_name)
            channel.close()

    def cleanup_minio() -> None:
        client = minio_client()
        client.remove_object(bucket, object_name)
        if not tuple(client.list_objects(bucket)):
            client.remove_bucket(bucket)

    def cleanup_qdrant() -> None:
        qdrant_request("DELETE", f"/collections/{collection}")

    cleanup("postgres-cleanup", cleanup_postgres)
    cleanup("redis-cleanup", cleanup_redis)
    cleanup("rabbitmq-cleanup", cleanup_rabbitmq)
    cleanup("minio-cleanup", cleanup_minio)
    cleanup("qdrant-cleanup", cleanup_qdrant)
    if cleanup_failures:
        raise PersistenceStageError(",".join(cleanup_failures))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "verify"}:
        print("usage: phase2-persistence.py [seed|verify] <marker>", file=sys.stderr)
        return 2
    action, marker = sys.argv[1:]
    try:
        if action == "seed":
            seed(marker)
            print("Phase 2 persistence sentinels seeded.")
        else:
            verify_and_cleanup(marker)
            print("Phase 2 persistence survived container recreation and was cleaned.")
    except PersistenceStageError as error:
        print(
            f"Phase 2 datastore {action} failed at {error.stage}; values suppressed.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            f"Phase 2 datastore {action} failed ({type(error).__name__}); values suppressed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
