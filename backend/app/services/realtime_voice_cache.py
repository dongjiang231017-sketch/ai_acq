from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.services.runtime_ai_config import get_runtime_ai_config


VOICE_CACHE_PROFILE_ID = "owner_clone_natural_v2_callready"
VOICE_CACHE_DISPLAY_NAME = "本人克隆音色-自然电销-v2"
VOICE_CACHE_VERSION = "2026-07-06-natural-v2-callready"

_SPLIT_RE = re.compile(r"[|/／,，;；]+")
_PUNCT_RE = re.compile(r"[\s。！？?!，,、.：:；;（）()【】\\[\\]《》<>“”\"'`~·…—_-]+")
_SEQ_PREFIX_RE = re.compile(r"^seq", re.IGNORECASE)
_EXTRA_TRIGGERS_BY_INTENT = {
    "script_10": (
        "抽成多少",
        "平台抽成多少",
        "手续费多少",
        "平台手续费多少",
        "手续费几个点",
        "怎么抽成",
        "抽几个点",
        "怎么抽佣",
        "扣几个点",
    ),
    "script_23": ("服务费多少", "你们服务费多少", "怎么计费", "怎么报价"),
    "greeting_confirm_store": ("喂", "喂喂", "你好", "您好", "哪位", "你哪位", "谁啊", "谁呀"),
    "willing_but_alert": (
        "你说",
        "您说",
        "行你说",
        "可以你说",
        "那你说",
        "那您说",
        "你讲",
        "您讲",
        "继续",
        "继续说",
        "继续讲",
        "接着说",
        "接着讲",
        "往下说",
        "往下讲",
        "说吧",
        "讲吧",
        "简单说",
        "讲重点",
        "说重点",
    ),
    "identity_who_are_you": (
        "你们是干嘛的",
        "你们干嘛的",
        "你是干嘛的",
        "你们是干什么的",
        "你们干什么的",
        "你是干什么的",
        "你们做什么的",
        "你们做啥的",
        "做什么的",
        "干嘛的",
        "干什么的",
        "什么业务",
        "哪个公司",
        "什么公司",
    ),
    "identity_not_official": ("你是不是官方", "你们官方吗", "官方的吗", "官方人员吗"),
    "phone_source": ("电话从哪里来的", "电话哪来的", "号码从哪里来的", "你怎么知道我号码"),
    "robot_concern": ("你是不是机器人", "是不是机器人", "你是不是ai", "是不是ai", "听着像ai"),
    "early_refusal": ("不要", "不想要", "暂时不要", "不考虑", "暂不考虑"),
    "what_is_videohao_groupbuy": ("团购是什么", "视频号团购什么意思", "微信视频号团购", "这是什么业务"),
    "benefit_opening": ("有什么好处", "能帮我什么", "对我有什么用", "能干嘛", "有什么帮助"),
    "compare_meituan": ("美团", "已经有美团", "我做了美团", "做了美团"),
    "compare_douyin": ("抖音", "已经有抖音", "我做了抖音", "做了抖音"),
    "no_guaranteed_rank": ("能不能保证排名", "保证曝光吗", "保证订单吗", "保证流量吗"),
}


@dataclass(frozen=True)
class CachedVoiceItem:
    seq: str
    scene_id: str
    scene_title: str
    section: str
    customer_trigger: str
    human_text: str
    wav_path: Path
    pcm_path: Path
    audio_format: str


@dataclass(frozen=True)
class CachedVoiceIntent:
    intent_id: str
    priority: str
    seq_candidates: tuple[str, ...]
    scene_title: str
    trigger_examples: tuple[str, ...]
    recommended_action: str


@dataclass(frozen=True)
class CachedVoiceMatch:
    intent_id: str
    scene_title: str
    matched_trigger: str
    confidence: float
    recommended_action: str
    items: tuple[CachedVoiceItem, ...]
    voice_profile: str = VOICE_CACHE_PROFILE_ID
    voice_display_name: str = VOICE_CACHE_DISPLAY_NAME
    asset_version: str = VOICE_CACHE_VERSION

    @property
    def seqs(self) -> tuple[str, ...]:
        return tuple(item.seq for item in self.items)

    @property
    def reply_text(self) -> str:
        return " ".join(item.human_text.strip() for item in self.items if item.human_text.strip())


@dataclass(frozen=True)
class VoiceCacheLibrary:
    root: Path
    items_by_seq: dict[str, CachedVoiceItem]
    intents: tuple[CachedVoiceIntent, ...]
    opening_seq: str = "002"
    profile: str = VOICE_CACHE_PROFILE_ID
    display_name: str = VOICE_CACHE_DISPLAY_NAME
    asset_version: str = VOICE_CACHE_VERSION


def match_cached_voice_reply(text: str) -> CachedVoiceMatch | None:
    runtime_config = get_runtime_ai_config()
    if not runtime_config.realtime_voice_cache_enabled:
        return None
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    if not library.items_by_seq or not library.intents:
        return None
    normalized_text = _normalize(text)
    if not normalized_text:
        return None

    best_intent: CachedVoiceIntent | None = None
    best_trigger = ""
    best_confidence = 0.0
    for intent in library.intents:
        confidence, trigger = _score_intent(normalized_text, intent.trigger_examples)
        assistant_reply = _normalize(
            " ".join(
                item.human_text.strip()
                for seq in intent.seq_candidates
                if (item := library.items_by_seq.get(_normalize_seq(seq))) and item.human_text.strip()
            )
        )
        if assistant_reply and (normalized_text == assistant_reply or assistant_reply in normalized_text):
            confidence = 1.01
            trigger = f"assistant_reply:{intent.intent_id}"
        if confidence > best_confidence:
            best_intent = intent
            best_trigger = trigger
            best_confidence = confidence
    if not best_intent or best_confidence < runtime_config.realtime_voice_cache_min_confidence:
        return None

    items = tuple(
        item
        for seq in best_intent.seq_candidates
        if (item := library.items_by_seq.get(_normalize_seq(seq))) and item.pcm_path.exists()
    )
    if not items:
        return None
    return CachedVoiceMatch(
        intent_id=best_intent.intent_id,
        scene_title=best_intent.scene_title,
        matched_trigger=best_trigger,
        confidence=round(best_confidence, 3),
        recommended_action=best_intent.recommended_action,
        items=items,
        voice_profile=library.profile,
        voice_display_name=library.display_name,
        asset_version=library.asset_version,
    )


def get_cached_opening_voice_match() -> CachedVoiceMatch | None:
    runtime_config = get_runtime_ai_config()
    if not runtime_config.realtime_voice_cache_enabled:
        return None
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    item = library.items_by_seq.get(library.opening_seq)
    if not item or not item.pcm_path.exists():
        return None
    return CachedVoiceMatch(
        intent_id="greeting_confirm_store",
        scene_title=item.scene_title,
        matched_trigger="opening",
        confidence=1.0,
        recommended_action="play_cached",
        items=(item,),
        voice_profile=library.profile,
        voice_display_name=library.display_name,
        asset_version=library.asset_version,
    )


def iter_cached_voice_pcm_chunks(match: CachedVoiceMatch, *, chunk_size: int = 320):
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    for item in match.items:
        data = item.pcm_path.read_bytes()
        if not data:
            continue
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]


def voice_cache_status() -> dict[str, object]:
    runtime_config = get_runtime_ai_config()
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    return {
        "enabled": runtime_config.realtime_voice_cache_enabled,
        "root": str(library.root),
        "profile": library.profile,
        "displayName": library.display_name,
        "assetVersion": library.asset_version,
        "openingSeq": library.opening_seq,
        "manifestLoaded": bool(library.items_by_seq),
        "itemCount": len(library.items_by_seq),
        "intentCount": len(library.intents),
        "minConfidence": runtime_config.realtime_voice_cache_min_confidence,
    }


def voice_cache_library(*, limit: int = 100) -> dict[str, object]:
    runtime_config = get_runtime_ai_config()
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    items = sorted(library.items_by_seq.values(), key=lambda item: item.seq)[:limit]
    return {
        **voice_cache_status(),
        "items": [
            {
                "seq": item.seq,
                "sceneId": item.scene_id,
                "sceneTitle": item.scene_title,
                "section": item.section,
                "customerTrigger": item.customer_trigger,
                "humanText": item.human_text,
                "audioFormat": item.audio_format,
                "audioUrl": f"/api/voice/cache/items/{item.seq}/file",
            }
            for item in items
        ],
        "intents": [
            {
                "intentId": intent.intent_id,
                "priority": intent.priority,
                "seqCandidates": list(intent.seq_candidates),
                "sceneTitle": intent.scene_title,
                "triggerExamples": list(intent.trigger_examples),
                "recommendedAction": intent.recommended_action,
            }
            for intent in library.intents
        ],
    }


def voice_cache_item_audio_path(seq: str) -> Path | None:
    runtime_config = get_runtime_ai_config()
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    item = library.items_by_seq.get(_normalize_seq(seq))
    if not item or not item.wav_path.exists() or not item.wav_path.is_file():
        return None
    return item.wav_path


def voice_cache_opening_audio_path() -> Path | None:
    runtime_config = get_runtime_ai_config()
    if not runtime_config.realtime_voice_cache_enabled:
        return None
    library = _load_library(runtime_config.realtime_voice_cache_dir)
    path = library.root / "audio_24k" / f"seq{library.opening_seq}.wav"
    return path if path.exists() and path.is_file() else None


@lru_cache(maxsize=8)
def _load_library(cache_dir: str) -> VoiceCacheLibrary:
    root = Path(cache_dir or settings.realtime_voice_cache_dir).expanduser()
    manifest_path = root / "manifests" / "natural_v2_manifest_ascii.csv"
    intent_path = root / "specs" / "INTENT_MAPPING_SEED.csv"
    meta = _load_cache_meta(root)
    items_by_seq: dict[str, CachedVoiceItem] = {}
    intents: list[CachedVoiceIntent] = []

    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                seq = _normalize_seq(row.get("seq", ""))
                ascii_filename = row.get("ascii_filename") or f"seq{seq}.wav"
                wav_path = root / "audio_ascii_8k" / ascii_filename
                pcm_path = root / "audio_pcm16_8k" / f"{Path(ascii_filename).stem}.pcm"
                items_by_seq[seq] = CachedVoiceItem(
                    seq=seq,
                    scene_id=str(row.get("scene_id") or "").strip(),
                    scene_title=str(row.get("scene_title") or "").strip(),
                    section=str(row.get("section") or "").strip(),
                    customer_trigger=str(row.get("customer_trigger") or "").strip(),
                    human_text=str(row.get("human_text") or "").strip(),
                    wav_path=wav_path,
                    pcm_path=pcm_path,
                    audio_format=str(row.get("audio_format") or "").strip(),
                )

    if intent_path.exists():
        with intent_path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                seq_candidates = tuple(_normalize_seq(value) for value in _split_examples(row.get("seq_candidates", "")) if value.strip())
                intent_id = str(row.get("intent_id") or "").strip()
                triggers = tuple(_split_examples(row.get("trigger_examples", ""))) + _EXTRA_TRIGGERS_BY_INTENT.get(intent_id, ())
                if not intent_id or not seq_candidates or not triggers:
                    continue
                intents.append(
                    CachedVoiceIntent(
                        intent_id=intent_id,
                        priority=str(row.get("priority") or "").strip(),
                        seq_candidates=seq_candidates,
                        scene_title=str(row.get("scene_title") or "").strip(),
                        trigger_examples=triggers,
                        recommended_action=str(row.get("recommended_action") or "").strip(),
                    )
                )

    return VoiceCacheLibrary(
        root=root,
        items_by_seq=items_by_seq,
        intents=tuple(intents),
        opening_seq=_normalize_seq(meta["openingSeq"]),
        profile=meta["profile"],
        display_name=meta["displayName"],
        asset_version=meta["assetVersion"],
    )


def _load_cache_meta(root: Path) -> dict[str, str]:
    meta = {
        "profile": VOICE_CACHE_PROFILE_ID,
        "displayName": VOICE_CACHE_DISPLAY_NAME,
        "assetVersion": VOICE_CACHE_VERSION,
        "openingSeq": "002",
    }
    meta_path = root / "voice_cache_meta.json"
    if not meta_path.exists():
        return meta
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return meta
    if isinstance(data, dict):
        for key in meta:
            value = str(data.get(key) or "").strip()
            if value:
                meta[key] = value
    return meta


def _split_examples(value: str | None) -> list[str]:
    return [part.strip() for part in _SPLIT_RE.split(str(value or "")) if part.strip()]


def _normalize(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("從哪", "从哪").replace("哪兒", "哪里").replace("哪儿", "哪里")
    text = text.replace("电话从哪里来的", "电话哪里来的")
    return _PUNCT_RE.sub("", text)


def _normalize_seq(value: str) -> str:
    seq = _SEQ_PREFIX_RE.sub("", str(value or "").strip())
    return seq.zfill(3)


def _score_intent(normalized_text: str, triggers: tuple[str, ...]) -> tuple[float, str]:
    best_confidence = 0.0
    best_trigger = ""
    for trigger in triggers:
        normalized_trigger = _normalize(trigger)
        if not normalized_trigger:
            continue
        if len(normalized_trigger) <= 1:
            confidence = 1.0 if normalized_trigger == normalized_text else 0.0
        elif normalized_trigger == "不要" and "要不要" in normalized_text:
            confidence = 0.0
        elif normalized_trigger in normalized_text:
            confidence = 1.0
        elif normalized_text in normalized_trigger and len(normalized_text) >= 3:
            confidence = 0.94
        else:
            confidence = SequenceMatcher(None, normalized_text, normalized_trigger).ratio()
        if confidence > best_confidence:
            best_confidence = confidence
            best_trigger = trigger
    return best_confidence, best_trigger
