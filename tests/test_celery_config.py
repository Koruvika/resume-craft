from resumecraft.core.celery_app import celery_app


def test_celery_app_configured() -> None:
    assert celery_app.main == "resumecraft"
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.task_default_queue == "default"
    assert celery_app.conf.task_routes == {"resumecraft.worker.tasks.*": {"queue": "default"}}
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_generate_resume_task_registered() -> None:
    assert "resumecraft.worker.tasks.generate_resume" in celery_app.tasks
