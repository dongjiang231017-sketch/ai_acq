from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.operations import SystemSetting


@dataclass(frozen=True)
class RuntimeAiConfig:
    dashscope_api_key: str
    dashscope_workspace: str
    dashscope_voice_clone_model: str
    dashscope_tts_model: str
    dashscope_system_tts_model: str
    dashscope_realtime_tts_model: str
    dashscope_realtime_tts_voice: str
    dashscope_omni_realtime_model: str
    dashscope_omni_realtime_url: str
    dashscope_omni_realtime_voice: str
    dashscope_omni_input_transcription_model: str
    dashscope_system_tts_language_type: str
    dashscope_voice_prefix: str
    dashscope_voice_language_hints: str
    dashscope_preview_text: str
    dashscope_system_tts_preview_text: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_chat_model: str
    deepseek_timeout_seconds: float
    deepseek_max_tokens: int
    deepseek_stream_first_sentence: bool
    realtime_asr_model: str
    realtime_tts_voice_id: str
    realtime_tts_voice_name: str
    realtime_tts_voice_type: str
    realtime_conversation_mode: str
    realtime_llm_timeout_seconds: float
    realtime_reply_max_chars: int
    realtime_voice_cache_enabled: bool
    realtime_voice_cache_dir: str
    realtime_voice_cache_min_confidence: float
    voice_clone_provider: str
    voice_clone_training_enabled: bool
    voice_clone_engine_name: str
    voice_sample_public_base_url: str


MODEL_SETTING_MAP = {
    "dashscope_api_key": "dashscope_api_key",
    "dashscope_workspace": "dashscope_workspace",
    "dashscope_voice_clone_model": "dashscope_voice_clone_model",
    "dashscope_tts_model": "dashscope_tts_model",
    "dashscope_system_tts_model": "dashscope_system_tts_model",
    "dashscope_realtime_tts_model": "dashscope_realtime_tts_model",
    "dashscope_realtime_tts_voice": "dashscope_realtime_tts_voice",
    "dashscope_omni_realtime_model": "dashscope_omni_realtime_model",
    "dashscope_omni_realtime_url": "dashscope_omni_realtime_url",
    "dashscope_omni_realtime_voice": "dashscope_omni_realtime_voice",
    "dashscope_omni_input_transcription_model": "dashscope_omni_input_transcription_model",
    "dashscope_system_tts_language_type": "dashscope_system_tts_language_type",
    "dashscope_voice_prefix": "dashscope_voice_prefix",
    "dashscope_voice_language_hints": "dashscope_voice_language_hints",
    "dashscope_preview_text": "dashscope_preview_text",
    "dashscope_system_tts_preview_text": "dashscope_system_tts_preview_text",
    "deepseek_api_key": "deepseek_api_key",
    "deepseek_base_url": "deepseek_base_url",
    "deepseek_chat_model": "deepseek_chat_model",
    "deepseek_timeout_seconds": "deepseek_timeout_seconds",
    "deepseek_max_tokens": "deepseek_max_tokens",
    "deepseek_stream_first_sentence": "deepseek_stream_first_sentence",
    "realtime_asr_model": "realtime_asr_model",
    "realtime_tts_voice_id": "realtime_tts_voice_id",
    "realtime_tts_voice_name": "realtime_tts_voice_name",
    "realtime_tts_voice_type": "realtime_tts_voice_type",
    "realtime_conversation_mode": "realtime_conversation_mode",
    "realtime_llm_timeout_seconds": "realtime_llm_timeout_seconds",
    "realtime_reply_max_chars": "realtime_reply_max_chars",
    "realtime_voice_cache_enabled": "realtime_voice_cache_enabled",
    "realtime_voice_cache_dir": "realtime_voice_cache_dir",
    "realtime_voice_cache_min_confidence": "realtime_voice_cache_min_confidence",
    "voice_clone_provider": "voice_clone_provider",
    "voice_clone_training_enabled": "voice_clone_training_enabled",
    "voice_clone_engine_name": "voice_clone_engine_name",
    "voice_sample_public_base_url": "voice_sample_public_base_url",
}


def get_runtime_ai_config() -> RuntimeAiConfig:
    overrides = _load_model_overrides()
    return RuntimeAiConfig(
        dashscope_api_key=_str(overrides, "dashscope_api_key", settings.dashscope_api_key),
        dashscope_workspace=_str(overrides, "dashscope_workspace", settings.dashscope_workspace),
        dashscope_voice_clone_model=_str(overrides, "dashscope_voice_clone_model", settings.dashscope_voice_clone_model),
        dashscope_tts_model=_str(overrides, "dashscope_tts_model", settings.dashscope_tts_model),
        dashscope_system_tts_model=_str(overrides, "dashscope_system_tts_model", settings.dashscope_system_tts_model),
        dashscope_realtime_tts_model=_str(overrides, "dashscope_realtime_tts_model", settings.dashscope_realtime_tts_model),
        dashscope_realtime_tts_voice=_str(overrides, "dashscope_realtime_tts_voice", settings.dashscope_realtime_tts_voice),
        dashscope_omni_realtime_model=_str(overrides, "dashscope_omni_realtime_model", settings.dashscope_omni_realtime_model),
        dashscope_omni_realtime_url=_str(overrides, "dashscope_omni_realtime_url", settings.dashscope_omni_realtime_url),
        dashscope_omni_realtime_voice=_str(overrides, "dashscope_omni_realtime_voice", settings.dashscope_omni_realtime_voice),
        dashscope_omni_input_transcription_model=_str(
            overrides,
            "dashscope_omni_input_transcription_model",
            settings.dashscope_omni_input_transcription_model,
        ),
        dashscope_system_tts_language_type=_str(
            overrides,
            "dashscope_system_tts_language_type",
            settings.dashscope_system_tts_language_type,
        ),
        dashscope_voice_prefix=_str(overrides, "dashscope_voice_prefix", settings.dashscope_voice_prefix),
        dashscope_voice_language_hints=_str(overrides, "dashscope_voice_language_hints", settings.dashscope_voice_language_hints),
        dashscope_preview_text=_str(overrides, "dashscope_preview_text", settings.dashscope_preview_text),
        dashscope_system_tts_preview_text=_str(
            overrides,
            "dashscope_system_tts_preview_text",
            settings.dashscope_system_tts_preview_text,
        ),
        deepseek_api_key=_str(overrides, "deepseek_api_key", settings.deepseek_api_key),
        deepseek_base_url=_str(overrides, "deepseek_base_url", settings.deepseek_base_url),
        deepseek_chat_model=_str(overrides, "deepseek_chat_model", settings.deepseek_chat_model),
        deepseek_timeout_seconds=_float(overrides, "deepseek_timeout_seconds", settings.deepseek_timeout_seconds),
        deepseek_max_tokens=_int(overrides, "deepseek_max_tokens", settings.deepseek_max_tokens),
        deepseek_stream_first_sentence=_bool(
            overrides,
            "deepseek_stream_first_sentence",
            settings.deepseek_stream_first_sentence,
        ),
        realtime_asr_model=_str(overrides, "realtime_asr_model", settings.realtime_asr_model),
        realtime_tts_voice_id=_str(overrides, "realtime_tts_voice_id", settings.realtime_tts_voice_id),
        realtime_tts_voice_name=_str(overrides, "realtime_tts_voice_name", settings.realtime_tts_voice_name),
        realtime_tts_voice_type=_str(overrides, "realtime_tts_voice_type", settings.realtime_tts_voice_type),
        realtime_conversation_mode=_str(overrides, "realtime_conversation_mode", settings.realtime_conversation_mode),
        realtime_llm_timeout_seconds=_float(overrides, "realtime_llm_timeout_seconds", settings.realtime_llm_timeout_seconds),
        realtime_reply_max_chars=_int(overrides, "realtime_reply_max_chars", settings.realtime_reply_max_chars),
        realtime_voice_cache_enabled=_bool(
            overrides,
            "realtime_voice_cache_enabled",
            settings.realtime_voice_cache_enabled,
        ),
        realtime_voice_cache_dir=_str(
            overrides,
            "realtime_voice_cache_dir",
            settings.realtime_voice_cache_dir,
        ),
        realtime_voice_cache_min_confidence=_float(
            overrides,
            "realtime_voice_cache_min_confidence",
            settings.realtime_voice_cache_min_confidence,
        ),
        voice_clone_provider=_str(overrides, "voice_clone_provider", settings.voice_clone_provider),
        voice_clone_training_enabled=_bool(overrides, "voice_clone_training_enabled", settings.voice_clone_training_enabled),
        voice_clone_engine_name=_str(overrides, "voice_clone_engine_name", settings.voice_clone_engine_name),
        voice_sample_public_base_url=_str(overrides, "voice_sample_public_base_url", settings.voice_sample_public_base_url),
    )


def _load_model_overrides() -> dict[str, str]:
    try:
        with SessionLocal() as db:
            rows = db.scalars(select(SystemSetting).where(SystemSetting.group_key == "model")).all()
            return {MODEL_SETTING_MAP[row.item_key]: row.value for row in rows if row.item_key in MODEL_SETTING_MAP}
    except Exception:  # noqa: BLE001 - runtime config must not break boot when migrations are not applied yet.
        return {}


def _str(values: dict[str, str], key: str, fallback: str) -> str:
    value = values.get(key)
    if value is None:
        return fallback
    return str(value).strip()


def _bool(values: dict[str, str], key: str, fallback: bool) -> bool:
    value = values.get(key)
    if value is None:
        return fallback
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "已启用"}


def _int(values: dict[str, str], key: str, fallback: int) -> int:
    value = values.get(key)
    if value is None:
        return fallback
    try:
        return int(str(value).strip())
    except ValueError:
        return fallback


def _float(values: dict[str, str], key: str, fallback: float) -> float:
    value = values.get(key)
    if value is None:
        return fallback
    try:
        return float(str(value).strip())
    except ValueError:
        return fallback
