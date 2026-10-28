from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from the environment with prefix RC_.

    All fields have defaults so the package imports cleanly with no .env file.
    """

    model_config = SettingsConfigDict(env_prefix="RC_", env_file=".env", extra="ignore")

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres — components, not DSN, so passwords with special chars are never URL-parsed.
    database_host: str = "localhost"
    database_port: int = 5434
    database_user: str = "resumecraft"
    database_password: SecretStr = SecretStr("resumecraft")
    database_name: str = "resumecraft"
    database_use_ssl: bool = False

    # Redis broker/result backend for Celery.
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend_url: str = "redis://localhost:6379/1"
    celery_max_retries: int = 3
    celery_retry_delay: int = 60
    celery_soft_time_limit: int = 600
    celery_hard_time_limit: int = 660
    celery_concurrency: int = 2

    # LLM — any OpenAI-compatible endpoint.
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"

    # GPTResearcher — company research tasks. Web search retriever: tavily when
    # a key is set, else the free duckduckgo fallback. The embedding string is
    # gpt-researcher's '<provider>:<model>' form and must point at an
    # embeddings-capable endpoint.
    tavily_api_key: SecretStr | None = None
    embedding_model: str = "openai:text-embedding-3-small"
    # Per-query wall-clock budget; must stay under celery_soft_time_limit.
    research_query_timeout: int = 240
    # Max research queries in flight at once; bursts of concurrent LLM calls
    # trigger server-side stalls on the LLM provider.
    research_max_concurrency: int = 2
    # De-duplication: POST /companies reuses the user's latest research
    # from the last N days whose processed name has Jaro-Winkler similarity >=
    # the threshold (and same processed website, when both sides have one).
    research_dedup_window_days: int = 30
    research_dedup_name_threshold: float = 0.92

    # LlamaCloud — PDF resume parsing (extract API).
    llama_cloud_api_key: SecretStr | None = None

    # Auth — local JWT issuer: /auth/login signs tokens with this key.
    jwt_secret_key: SecretStr = SecretStr("dev-only-jwt-secret-key-change-me")
    access_token_expire_minutes: int = 60

    @property
    def database_url(self) -> str:
        user = quote(self.database_user, safe="")
        password = quote(self.database_password.get_secret_value(), safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
