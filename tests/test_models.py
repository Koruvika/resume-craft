from resumecraft.db.models import Job, Resume


def test_job_table_columns() -> None:
    table = Job.__table__
    assert table.name == "jobs"
    expected = {
        "id",
        "user_id",
        "type",
        "status",
        "progress",
        "input",
        "result",
        "error",
        "celery_task_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert expected == set(table.columns.keys())


def test_resume_table_columns() -> None:
    table = Resume.__table__
    assert table.name == "resumes"
    expected = {
        "id",
        "user_id",
        "title",
        "content",
        "status",
        "error",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert expected == set(table.columns.keys())
