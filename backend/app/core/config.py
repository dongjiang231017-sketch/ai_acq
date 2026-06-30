from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai-acq-qian-api"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./local.db"
    redis_url: str = "redis://localhost:6379/0"
    outbound_queue_enabled: bool = False
    outbound_queue_name: str = "ai_acq:outbound_tasks"
    dm_queue_enabled: bool = False
    dm_queue_name: str = "ai_acq:dm_tasks"
    dm_gateway_mode: str = "simulator"
    dm_browser_profile_root: str = ".dm_browser_profiles"
    dm_browser_headless: bool = True
    dm_browser_channel: str = "chrome"
    dm_browser_timeout_ms: int = 15000
    dm_browser_slow_mo_ms: int = 0
    dm_browser_live_send_enabled: bool = False
    voice_sample_storage_root: str = ".voice_samples"
    voice_clone_training_enabled: bool = False
    voice_clone_engine_name: str = ""
    telephony_gateway_mode: str = "simulator"
    asterisk_host: str = "127.0.0.1"
    asterisk_ami_port: int = 5038
    asterisk_ami_username: str = ""
    asterisk_ami_password: str = ""
    asterisk_ami_timeout_seconds: int = 5
    asterisk_originate_context: str = "from-ai-acq"
    asterisk_originate_extension: str = "s"
    asterisk_originate_channel_template: str = "PJSIP/{phone}@{trunk}"
    asterisk_originate_timeout_ms: int = 30000
    asterisk_caller_id: str = "AI获客"
    asterisk_trunk_name: str = "uc100"
    asterisk_max_channels: int = 1
    asterisk_live_call_enabled: bool = False
    asterisk_bulk_call_enabled: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    admin_secret_key: str = "change-me"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
