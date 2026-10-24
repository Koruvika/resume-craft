from resumecraft.core.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    assert (
        settings.database_url
        == "postgresql+asyncpg://resumecraft:resumecraft@localhost:5432/resumecraft"
    )
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.llm_model == "gpt-4o-mini"


def test_env_prefix_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RC_DATABASE_HOST", "db.example.com")
    monkeypatch.setenv("RC_DATABASE_USE_SSL", "true")
    settings = Settings(_env_file=None)
    assert settings.database_host == "db.example.com"
    assert settings.database_use_ssl is True


def test_database_url_quotes_special_chars() -> None:
    settings = Settings(_env_file=None, database_password="p@ss:word/123")
    assert "p%40ss%3Aword%2F123" in settings.database_url
