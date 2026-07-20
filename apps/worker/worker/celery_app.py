"""Celery application factory."""

from celery import Celery
from kombu import Exchange, Queue

from worker.settings import BrokerSettings


def create_celery(settings: BrokerSettings | None = None) -> Celery:
    """Configure Celery without connecting to the broker."""

    resolved_settings = settings or BrokerSettings()
    celery_app = Celery(
        resolved_settings.app_name,
        broker=resolved_settings.broker_url.get_secret_value(),
        include=("worker.tasks",),
    )
    ingestion_exchange = Exchange("ingestion", type="direct", durable=True)
    dead_letter_exchange = Exchange("ingestion.dead", type="direct", durable=True)
    celery_app.conf.update(
        accept_content=("json",),
        enable_utc=True,
        result_serializer="json",
        task_acks_late=True,
        task_default_exchange="ingestion",
        task_default_exchange_type="direct",
        task_default_queue="ingestion",
        task_default_routing_key="document.process",
        task_queues=(
            Queue(
                "ingestion",
                ingestion_exchange,
                routing_key="document.process",
                durable=True,
                queue_arguments={
                    "x-dead-letter-exchange": "ingestion.dead",
                    "x-dead-letter-routing-key": "document.failed",
                },
            ),
            Queue(
                "ingestion.dead",
                dead_letter_exchange,
                routing_key="document.failed",
                durable=True,
            ),
        ),
        task_reject_on_worker_lost=True,
        task_routes={
            "worker.tasks.process_document": {
                "queue": "ingestion",
                "routing_key": "document.process",
            }
        },
        task_serializer="json",
        task_track_started=True,
        timezone="UTC",
        worker_prefetch_multiplier=1,
    )

    # Force import tasks to register them
    import worker.tasks  # noqa: F401

    return celery_app
