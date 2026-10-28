from resumecraft.db.models import Resume, Task


def test_task_table_columns() -> None:
    table = Task.__table__
    assert table.name == "tasks"
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
