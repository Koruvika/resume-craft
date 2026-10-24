from celery import Celery

from resumecraft.core.celery_config import configure_celery
from resumecraft.core.config import Settings, get_settings


def create_celery(settings: Settings | None = None) -> Celery:
    app = Celery("resumecraft", include=["resumecraft.worker.tasks"])
    configure_celery(app, settings or get_settings())
    return app


celery_app = create_celery()
