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
    dashscope_realtime_tts_model: str = "qwen3-tts-flash-realtime"
    dashscope_realtime_tts_voice: str = "Serena"
    dashscope_omni_realtime_model: str = "qwen3.5-omni-flash-realtime-2026-03-15"
    dashscope_omni_realtime_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    dashscope_omni_realtime_voice: str = "Serena"
    dashscope_omni_input_transcription_model: str = "qwen3-asr-flash-realtime"
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
    asterisk_deployment_mode: str = "server"
    voice_gateway_profile: str = "dinstar_8t_server"
    voice_gateway_label: str = ""
    voice_gateway_vendor: str = ""
    voice_gateway_model: str = ""
    voice_gateway_category: str = ""
    voice_gateway_transport: str = ""
    voice_gateway_line_type: str = ""
    voice_gateway_host: str = ""
    voice_gateway_sip_port: int = 5060
    voice_gateway_trunk_name: str = "dinstar8t"
    voice_gateway_max_channels: int = 8
    voice_gateway_admin_url: str = ""
    voice_gateway_discovery_mode: str = "manual_or_lan_scan"
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
    realtime_asr_model: str = "paraformer-realtime-8k-v2"
    realtime_tts_voice_id: str = ""
    realtime_tts_voice_name: str = ""
    realtime_tts_voice_type: str = "system"
    realtime_conversation_mode: str = "pipeline"
    realtime_llm_timeout_seconds: float = 1.2
    realtime_call_opening_text: str = "您好，我这边做视频号团购到店获客，来电确认微信同城曝光这块。"
    realtime_call_event_log_path: str = "/tmp/ai-acq-realtime-call-events.jsonl"
    realtime_reply_max_chars: int = 48
    realtime_barge_rms_threshold: int = 2600
    realtime_barge_frames: int = 8
    realtime_tts_gain: float = 1.4
    realtime_opening_grace_seconds: float = 1.2
    realtime_debug_audio_capture_enabled: bool = False
    realtime_debug_audio_capture_dir: str = "/tmp/ai-acq-realtime-audio"
    realtime_audio_quality_enabled: bool = True
    realtime_answer_classification_seconds: float = 7.0
    cors_origins: list[str] = ["http://localhost:5173"]
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    admin_secret_key: str = "change-me"
    auth_secret_key: str = "change-me-auth"
    access_token_expire_seconds: int = 60 * 60 * 24 * 7
    initial_client_username: str = ""
    initial_client_password: str = ""
    initial_client_display_name: str = "客户账号"
    initial_client_phone: str = ""
    initial_client_email: str = ""
    amap_web_key: str | None = None
    baidu_map_key: str | None = None
    tencent_map_key: str | None = None
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
