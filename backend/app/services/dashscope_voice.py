from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, VoiceEnrollmentService
from dashscope.audio.tts_v2.enrollment import VoiceEnrollmentException
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat

from app.core.config import settings
from app.models.growth import VoiceProfile, VoiceSample


class VoiceProviderError(RuntimeError):
    """Raised when the configured voice provider cannot complete the request."""


@dataclass(frozen=True)
class VoiceProviderStatus:
    provider: str
    configured: bool
    ready: bool
    status: str
    message: str
    engine_name: str
    clone_model: str
    tts_model: str
    sample_public_base_url_configured: bool


@dataclass(frozen=True)
class VoiceCloneResult:
    external_voice_id: str
    preview_audio_path: str
    message: str


@dataclass(frozen=True)
class SystemVoicePreviewResult:
    audio_url: str
    message: str


def _provider_name() -> str:
    return (settings.voice_clone_provider or "dashscope").strip().lower()


def _api_key() -> str:
    return settings.dashscope_api_key.strip()


def _configure_dashscope_sdk() -> None:
    key = _api_key()
    if key:
        dashscope.api_key = key


def _workspace() -> str | None:
    value = settings.dashscope_workspace.strip()
    return value or None


def _language_hints() -> list[str] | None:
    hints = [item.strip() for item in settings.dashscope_voice_language_hints.split(",") if item.strip()]
    return hints or None


def _normalized_prefix(profile: VoiceProfile) -> str:
    configured = settings.dashscope_voice_prefix.strip().lower()
    base = re.sub(r"[^a-z0-9]", "", configured or "aiacq")[:8] or "aiacq"
    suffix = re.sub(r"[^a-z0-9]", "", profile.id.lower())[:2]
    return (base + suffix)[:10]


def dashscope_provider_status(probe: bool = False) -> VoiceProviderStatus:
    provider = _provider_name()
    engine_name = settings.voice_clone_engine_name.strip() or "DashScope CosyVoice"
    key_configured = bool(_api_key())
    base_configured = bool(settings.voice_sample_public_base_url.strip())

    if provider != "dashscope":
        return VoiceProviderStatus(
            provider=provider,
            configured=False,
            ready=False,
            status="不支持",
            message=f"当前只内置 DashScope CosyVoice 接入，暂不支持 {provider}。",
            engine_name=engine_name,
            clone_model=settings.dashscope_voice_clone_model,
            tts_model=settings.dashscope_tts_model,
            sample_public_base_url_configured=base_configured,
        )

    configured = bool(settings.voice_clone_training_enabled and key_configured)
    if not settings.voice_clone_training_enabled:
        status = "未启用"
        message = "声音复刻开关未启用，请配置 VOICE_CLONE_TRAINING_ENABLED=true。"
    elif not key_configured:
        status = "缺少API Key"
        message = "缺少 DASHSCOPE_API_KEY，不能调用 DashScope/CosyVoice。"
    elif not base_configured:
        status = "缺少公网样本地址"
        message = "DashScope 创建音色需要可公网访问的录音 URL，请配置 VOICE_SAMPLE_PUBLIC_BASE_URL。"
    else:
        status = "已配置"
        message = "DashScope/CosyVoice 已配置，可提交授权样本生成复刻音色。"

    if probe and configured:
        try:
            VoiceEnrollmentService(api_key=_api_key(), workspace=_workspace()).list_voices(page_index=0, page_size=1)
        except Exception as exc:  # noqa: BLE001 - provider SDK raises several public exception types
            return VoiceProviderStatus(
                provider=provider,
                configured=True,
                ready=False,
                status="连接失败",
                message=f"DashScope 连接失败：{_safe_provider_error(exc)}",
                engine_name=engine_name,
                clone_model=settings.dashscope_voice_clone_model,
                tts_model=settings.dashscope_tts_model,
                sample_public_base_url_configured=base_configured,
            )
        status = "连接正常" if base_configured else status
        message = "DashScope API Key 可用，声音服务连通正常。" if base_configured else message

    return VoiceProviderStatus(
        provider=provider,
        configured=configured,
        ready=configured and base_configured and status not in {"连接失败"},
        status=status,
        message=message,
        engine_name=engine_name,
        clone_model=settings.dashscope_voice_clone_model,
        tts_model=settings.dashscope_tts_model,
        sample_public_base_url_configured=base_configured,
    )


def public_sample_url(sample: VoiceSample) -> str:
    base_url = settings.voice_sample_public_base_url.strip().rstrip("/")
    if not base_url:
        raise VoiceProviderError("DashScope 创建音色需要可公网访问的录音 URL，请先配置 VOICE_SAMPLE_PUBLIC_BASE_URL。")
    return f"{base_url}/api/voice/samples/{quote(sample.id)}/file"


def create_dashscope_voice_clone(profile: VoiceProfile, sample: VoiceSample, record_id: str) -> VoiceCloneResult:
    status = dashscope_provider_status(probe=False)
    if not status.ready:
        raise VoiceProviderError(status.message)

    service = VoiceEnrollmentService(api_key=_api_key(), workspace=_workspace())
    try:
        voice_id = service.create_voice(
            target_model=settings.dashscope_voice_clone_model,
            prefix=_normalized_prefix(profile),
            url=public_sample_url(sample),
            language_hints=_language_hints(),
            max_prompt_audio_length=10,
        )
    except VoiceEnrollmentException as exc:
        raise VoiceProviderError(_safe_provider_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise VoiceProviderError(_safe_provider_error(exc)) from exc

    preview_path = synthesize_dashscope_preview(profile.id, record_id, voice_id)
    return VoiceCloneResult(
        external_voice_id=voice_id,
        preview_audio_path=str(preview_path),
        message=f"DashScope 音色复刻完成，voice_id={voice_id}，已生成试听音频。",
    )


def synthesize_dashscope_preview(profile_id: str, record_id: str, voice_id: str) -> Path:
    output_root = Path(settings.voice_output_storage_root).expanduser()
    if not output_root.is_absolute():
        output_root = (Path.cwd() / output_root).resolve()
    output_dir = output_root / profile_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{record_id}.wav"

    try:
        _configure_dashscope_sdk()
        synthesizer = SpeechSynthesizer(
            model=settings.dashscope_tts_model,
            voice=voice_id,
            format=AudioFormat.WAV_16000HZ_MONO_16BIT,
            workspace=_workspace(),
        )
        audio = synthesizer.call(settings.dashscope_preview_text)
    except Exception as exc:  # noqa: BLE001
        raise VoiceProviderError(f"音色已创建，但生成试听失败：{_safe_provider_error(exc)}") from exc

    if not audio:
        raise VoiceProviderError("音色已创建，但 DashScope 未返回试听音频。")
    output_path.write_bytes(audio)
    return output_path


def synthesize_qwen_system_voice_preview(voice_param: str, preview_text: str) -> SystemVoicePreviewResult:
    if not _api_key():
        raise VoiceProviderError("缺少 DASHSCOPE_API_KEY，不能生成系统内置音色试听。")

    try:
        response = dashscope.MultiModalConversation.call(
            api_key=_api_key(),
            model=settings.dashscope_system_tts_model,
            text=preview_text,
            voice=voice_param,
            language_type=settings.dashscope_system_tts_language_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise VoiceProviderError(f"Qwen-TTS 试听生成失败：{_safe_provider_error(exc)}") from exc

    status_code = _nested_response_value(response, "status_code")
    if status_code and int(status_code) >= 400:
        message = _nested_response_value(response, "message") or _nested_response_value(response, "code") or "provider error"
        raise VoiceProviderError(f"Qwen-TTS 试听生成失败：{_safe_provider_error(Exception(str(message)))}")

    audio_url = _nested_response_value(response, "output", "audio", "url")
    if not isinstance(audio_url, str) or not audio_url:
        raise VoiceProviderError("Qwen-TTS 未返回可播放的试听音频 URL。")

    return SystemVoicePreviewResult(
        audio_url=audio_url,
        message=f"Qwen-TTS 已生成 {voice_param} 的试听音频。",
    )


def _nested_response_value(response: object, *keys: str) -> object | None:
    current: object | None = response
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
            continue
        if hasattr(current, "to_dict"):
            try:
                current = current.to_dict()
            except Exception:  # noqa: BLE001
                pass
            if isinstance(current, dict):
                current = current.get(key)
                continue
        current = getattr(current, key, None)
    return current


def _safe_provider_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "DASHSCOPE_API_KEY", text)
    if "Arrearage" in redacted or "overdue-payment" in redacted:
        return "阿里云 DashScope 账户计费状态异常或欠费，服务拒绝访问。请在阿里云控制台确认百炼/DashScope 账户余额、欠费状态和模型服务开通状态后重试。"
    return redacted[:500]
