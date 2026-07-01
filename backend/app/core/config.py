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
    comment_intercept_live_sync_enabled: bool = False
    comment_intercept_adapter_mode: str = "disabled"
    voice_sample_storage_root: str = ".voice_samples"
    voice_output_storage_root: str = ".voice_outputs"
    voice_clone_training_enabled: bool = False
    voice_clone_provider: str = "dashscope"
    voice_clone_engine_name: str = "DashScope CosyVoice"
    voice_sample_public_base_url: str = ""
    dashscope_api_key: str = ""
    dashscope_workspace: str = ""
    dashscope_voice_clone_model: str = "cosyvoice-v2"
    dashscope_tts_model: str = "cosyvoice-v2"
    dashscope_system_tts_model: str = "qwen3-tts-flash"
    dashscope_system_tts_language_type: str = "Chinese"
    dashscope_voice_prefix: str = "aiacq"
    dashscope_voice_language_hints: str = "zh"
    dashscope_preview_text: str = "您好，我是本地生活服务顾问，想和您确认一下是否方便了解视频号团购获客。"
    dashscope_system_tts_preview_text: str = "您好，我是本地生活服务顾问，想和您确认一下是否方便了解视频号团购获客。"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 5.0
    deepseek_max_tokens: int = 80
    deepseek_stream_first_sentence: bool = True
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
    asterisk_test_call_result_wait_seconds: float = 12.0
    asterisk_caller_id: str = "AI获客"
    asterisk_trunk_name: str = "uc100"
    asterisk_max_channels: int = 1
    asterisk_live_call_enabled: bool = False
    asterisk_bulk_call_enabled: bool = False
    asterisk_audio_socket_bind_host: str = "127.0.0.1"
    asterisk_audio_socket_host: str = "127.0.0.1"
    asterisk_audio_socket_port: int = 9019
    realtime_asr_model: str = "paraformer-realtime-v2"
    realtime_tts_voice_id: str = ""
    realtime_tts_voice_name: str = ""
    realtime_call_opening_text: str = "您好，我是本地生活助手，请问现在方便沟通吗？"
    realtime_call_event_log_path: str = "/tmp/ai-acq-realtime-call-events.jsonl"
    realtime_reply_max_chars: int = 72
    cors_origins: list[str] = ["http://localhost:5173"]
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    admin_secret_key: str = "change-me"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
