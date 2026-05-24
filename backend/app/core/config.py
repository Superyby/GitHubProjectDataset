from functools import lru_cache
from urllib.parse import quote, unquote

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "GitHub Project Dataset"
    env: str = "dev"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str

    github_token: str | None = None
    github_per_page: int = Field(default=50, ge=1, le=100)
    github_max_pages_per_query: int = Field(default=2, ge=1, le=10)
    github_daily_repo_limit: int = Field(default=1000, ge=1, le=10000)

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_enabled: bool = False

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    ai_enabled: bool = False

    scheduler_enabled: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if "://" not in value or "@" not in value:
            return value

        scheme, rest = value.split("://", 1)
        authority, separator, tail = rest.partition("/")
        if not separator or ":" not in authority or "@" not in authority:
            return value

        username, password_and_host = authority.split(":", 1)
        password, host = password_and_host.rsplit("@", 1)
        encoded_password = quote(unquote(password), safe="")
        return f"{scheme}://{username}:{encoded_password}@{host}/{tail}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
