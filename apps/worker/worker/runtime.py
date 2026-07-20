"""Celery CLI entrypoint for the Phase 1 worker skeleton."""

from worker.celery_app import create_celery

celery = create_celery()

# Force import and finalize tasks
import worker.tasks  # noqa: F401, E402

celery.finalize()

__all__ = ["celery"]
