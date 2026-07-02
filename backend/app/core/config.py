from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai-acq-qian-api"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./local.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    admin_secret_key: str = "change-me"
    auth_secret_key: str = "change-me-auth"
    access_token_expire_seconds: int = 60 * 60 * 24 * 7
    amap_web_key: str | None = None
    collection_request_timeout_seconds: int = 8
    collection_http_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )
    browser_profile_root: str = ".runtime/browser-profiles"
    browser_default_timeout_seconds: int = 40

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
