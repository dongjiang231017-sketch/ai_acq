from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord, VoiceProfile
from app.models.operations import SystemSetting
from app.models.task import CallScript
from app.services.runtime_ai_config import get_runtime_ai_config


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
KIT_ROOT = REPO_ROOT / "voice_clone_kit"
DEFAULT_ZIP = BACKEND_ROOT / ".voice_samples" / "incoming" / "AI电销克隆音频_74条_不报服务价_保留千分之六.zip"
DEFAULT_PACK_ROOT = BACKEND_ROOT / ".voice_samples" / "packs" / "video_group_buying_20260710"

SCRIPT_NAME = "视频号团购电销话术手册 2026-07-10"
VOICE_PROFILE_NAME = "视频号团购招商顾问克隆音色"
VOICE_PACK_PROFILE = "video_group_buying_clone_20260710"
VOICE_PACK_VERSION = "2026-07-10-script-voice-v1"
VOICE_PREFIX = "jfx197"
VOICE_MODEL = "cosyvoice-v3.5-flash"
PENDING_IDS = {"56", "57", "58", "60", "62", "70", "71"}
REGENERATE_IDS = {"03", "05", "09", "10", "11", "45", "77"}

MAIN_TRIGGERS = {
    "01": "（电话接通后主动开场）",
    "02": "没开 / 没听说过这个",
    "03": "开了 / 已经在做了",
    "04": "什么 / 没听清",
    "05": "在忙 / 在开车",
    "06": "（本地已有真实同行案例时主动开场）",
    "07": "（回拨 / 二次跟进）",
    "08": "（开场后进入摸底）",
    "09": "主要靠美团 / 都在做",
    "10": "抽成挺高 / 百分之十几",
    "11": "千分之六？这么低？",
    "12": "有什么好处 / 能带来什么流量",
    "13": "怎么裂变 / 微信怎么传播",
    "14": "怎么沉淀私域 / 客人归谁",
    "15": "不会操作 / 怕麻烦",
    "16": "可以了解 / 发案例看看",
    "17": "团购挂在哪里 / 客人从哪看到",
    "18": "能预约吗 / 客人怎么下单",
    "19": "单子从哪出来 / 能连打印机吗 / 怎么核销",
    "20": "外卖怎么做 / 谁负责配送",
    "21": "开通后有哪些功能",
    "22": "是不是你们自己做的小程序",
    "23": "多少钱 / 怎么收费 / 费用多少",
    "24": "太贵了 / 能不能便宜 / 别人报价更低",
    "25": "多家店怎么收费 / 五家店多少钱",
    "26": "再便宜点 / 凑个整",
    "27": "你们公司在哪",
    "28": "有营业执照吗",
    "29": "你们是腾讯官方的吗",
    "30": "怎么证明靠谱 / 怕是骗子",
    "31": "到底有没有效果",
    "32": "生意很好 / 不缺客人",
    "33": "团购价低会不会亏",
    "34": "不会弄 / 太麻烦",
    "35": "再考虑考虑",
    "36": "先发资料看看",
    "37": "开通要准备什么",
    "38": "多久能上线",
    "39": "上线后还管吗",
    "40": "问过价格 / 资料 / 流程，意向较高",
    "41": "确认当前手机号就是微信",
    "42": "这个号不是微信",
    "43": "听完未拒绝但仍犹豫",
    "44": "明确说不需要",
    "45": "老板不在 / 我是店员",
    "46": "别再打了 / 明显反感",
    "47": "到我店里来聊",
    "48": "以前开过 / 没效果",
}

MAIN_TIPS = {
    "01": "语速放慢，咬清“视频号团购”；说完立即停，等客户反应。",
    "02": "转入主流程摸底，不继续堆叠介绍。",
    "05": "忙碌客户只给最省事的加微信出口。",
    "06": "只能使用真实同行案例，不能编造店名。",
    "09": "让客户自己说出抽成高，不替客户下结论。",
    "10": "只说微信支付手续费千分之六，不举其他金额算例。",
    "12": "三板斧一次只说一板，说完停一下。",
    "13": "三板斧一次只说一板，说完停一下。",
    "14": "三板斧一次只说一板，说完停一下。",
    "19": "核心是手机扫码核销，不动客户现有收银系统。",
    "20": "配送能力必须实话实说，现阶段主做到店核销和自取。",
    "23": "电话中不报本公司服务价；回答平台手续费后转微信发案例和门店方案。",
    "24": "不重复客户口中的价格，不还价，转微信说明交付差异。",
    "25": "多店也不在电话里报总价，转微信给门店方案。",
    "26": "不报底价或打包价，只推进看案例和门店方案。",
    "29": "绝不冒充腾讯官方，只称视频号服务商。",
    "35": "给看案例的低门槛动作，不虚构名额或期限。",
    "36": "客户要资料时顺势确认微信，不改发短信。",
    "37": "电话里只说三样，完整资料清单通过微信发送。",
    "42": "微信号必须复述确认，记错号码等于白打。",
    "44": "体面收线并留钩子，按低意向节奏再触达。",
    "46": "立即结束并标记勿扰，之后永不再呼。",
}

SETTING_META = {
    "dashscope_voice_clone_model": ("声音复刻模型", "当前默认复刻音色对应的 DashScope 模型。"),
    "dashscope_tts_model": ("实时合成模型", "pipeline 自由回复使用的 DashScope TTS 模型。"),
    "realtime_tts_voice_id": ("默认实时音色 ID", "外呼 pipeline 自由回复使用的音色 ID。"),
    "realtime_tts_voice_name": ("默认实时音色名称", "外呼页面展示的默认音色名称。"),
    "realtime_tts_voice_type": ("默认实时音色类型", "system 或 clone。"),
    "realtime_voice_cache_dir": ("外呼语音包目录", "固定话术语音包的本机绝对路径。"),
    "realtime_voice_cache_enabled": ("外呼语音包开关", "命中固定话术时优先播放克隆录音。"),
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_confirmed_lines() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_name in ("lines.json", "lines_part2.json", "lines_part3.json"):
        payload = json.loads((KIT_ROOT / file_name).read_text(encoding="utf-8"))
        rows.extend(payload["lines"])
    ids = [str(row["id"])[:2] for row in rows]
    if len(rows) != 74 or len(set(ids)) != 74:
        raise RuntimeError(f"确认话术应为 74 条且编号唯一，实际 {len(rows)} 条/{len(set(ids))} 个编号。")
    expected = {f"{number:02d}" for number in range(1, 82)} - PENDING_IDS
    if set(ids) != expected:
        raise RuntimeError(f"确认话术编号不匹配：缺少 {sorted(expected - set(ids))}，多出 {sorted(set(ids) - expected)}。")
    return rows


def _load_pending_ids() -> set[str]:
    payload = json.loads((KIT_ROOT / "lines_part3_pending.json").read_text(encoding="utf-8"))
    ids = {str(row["id"])[:2] for row in payload["lines"]}
    if ids != PENDING_IDS:
        raise RuntimeError(f"待确认编号应为 {sorted(PENDING_IDS)}，实际为 {sorted(ids)}。")
    return ids


def _decode_zip_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _zip_audio_members(source_zip: Path) -> dict[str, tuple[zipfile.ZipInfo, str]]:
    members: dict[str, tuple[zipfile.ZipInfo, str]] = {}
    with zipfile.ZipFile(source_zip) as archive:
        for info in archive.infolist():
            decoded = Path(_decode_zip_name(info.filename)).name
            match = re.match(r"^(\d{2})_.+\.mp3$", decoded, re.IGNORECASE)
            if not match or info.is_dir():
                continue
            members[match.group(1)] = (info, decoded)
    return members


def _category(entry_id: str) -> str:
    label = entry_id.split("_", 2)[1]
    if label.startswith("开场白"):
        return "开场"
    if label.startswith("主流程"):
        return "主流程"
    if label.startswith("问答"):
        return label[:3]
    if label == "收尾":
        return "收尾"
    return "特殊"


def _structured_entries(lines: list[dict[str, Any]], filenames: dict[str, str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for row in lines:
        entry_id = str(row["id"])
        number = entry_id[:2]
        trigger = str(row.get("customer") or MAIN_TRIGGERS.get(number) or "").strip()
        tip = str(row.get("note") or MAIN_TIPS.get(number) or "").strip()
        entries.append(
            {
                "number": number,
                "category": _category(entry_id),
                "customer_trigger": trigger,
                "content": str(row["text"]).strip(),
                "execution_tip": tip,
                "audio_file": filenames[number],
            }
        )
    return entries


def _validate_compliance(entries: list[dict[str, str]]) -> None:
    forbidden_service_prices = re.compile(r"(?<!\d)(?:299|400|500|580|2500)(?!\d)")
    offenders = [entry["number"] for entry in entries if forbidden_service_prices.search(entry["content"])]
    if offenders:
        raise RuntimeError(f"AI 话术仍含服务价格，拒绝导入：{offenders}")
    forbidden_fee_claims = ("不抽成", "没有抽成", "零抽成", "0抽成")
    fee_offenders = [
        entry["number"]
        for entry in entries
        if any(claim in entry["content"] for claim in forbidden_fee_claims)
        or (("抽成" in entry["content"] or "手续费" in entry["content"]) and "千分之六" not in entry["content"])
    ]
    if fee_offenders:
        raise RuntimeError(f"抽成口径未收敛到千分之六：{fee_offenders}")
    free_service_offenders = [
        entry["number"] for entry in entries if "免费帮您" in entry["content"] or "免费拉客" in entry["content"]
    ]
    if free_service_offenders:
        raise RuntimeError(f"话术含容易被理解为零服务价的表述：{free_service_offenders}")
    placeholder_offenders = [entry["number"] for entry in entries if "⚠" in entry["content"] or "【人设名】" in entry["content"]]
    if placeholder_offenders:
        raise RuntimeError(f"确认话术中仍含未确认占位符：{placeholder_offenders}")


def _discover_clone_voice(model: str, explicit_voice_id: str) -> tuple[str, str]:
    if explicit_voice_id:
        return model, explicit_voice_id
    import dashscope
    from dashscope.audio.tts_v2 import VoiceEnrollmentService

    runtime_config = get_runtime_ai_config()
    if not runtime_config.dashscope_api_key:
        raise RuntimeError("缺少 DashScope API key，无法确认克隆 voice id。")
    dashscope.api_key = runtime_config.dashscope_api_key
    rows = VoiceEnrollmentService().list_voices(prefix=VOICE_PREFIX, page_index=0, page_size=100)
    candidates = [row for row in rows if row.get("status") == "OK" and row.get("target_model") == model]
    if not candidates:
        raise RuntimeError(f"DashScope 中没有前缀 {VOICE_PREFIX}、模型 {model} 的可用克隆音色。")
    latest = max(candidates, key=lambda row: str(row.get("gmt_modified") or row.get("gmt_create") or ""))
    return str(latest["target_model"]), str(latest["voice_id"])


def _synthesize_override(path: Path, *, model: str, voice_id: str, text: str) -> None:
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer

    runtime_config = get_runtime_ai_config()
    dashscope.api_key = runtime_config.dashscope_api_key
    audio = SpeechSynthesizer(model=model, voice=voice_id).call(text)
    if not audio or not isinstance(audio, (bytes, bytearray)):
        raise RuntimeError("DashScope 没有返回可用的克隆音频。")
    path.write_bytes(bytes(audio))


def _prepare_audio_pack(
    source_zip: Path,
    pack_root: Path,
    lines: list[dict[str, Any]],
    members: dict[str, tuple[zipfile.ZipInfo, str]],
    *,
    voice_model: str,
    voice_id: str,
) -> list[dict[str, str]]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("缺少 ffmpeg，无法把 MP3 转成电话播放格式。")
    for directory in ("source_mp3", "audio_24k", "audio_ascii_8k", "audio_pcm16_8k", "manifests", "specs"):
        target = pack_root / directory
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    filenames = {number: decoded for number, (_, decoded) in members.items()}
    with zipfile.ZipFile(source_zip) as archive:
        for number, (info, decoded) in members.items():
            (pack_root / "source_mp3" / decoded).write_bytes(archive.read(info))

    entries = _structured_entries(lines, filenames)
    _validate_compliance(entries)
    by_number = {entry["number"]: entry for entry in entries}
    for number in sorted(REGENERATE_IDS):
        entry = by_number[number]
        _synthesize_override(
            pack_root / "source_mp3" / entry["audio_file"],
            model=voice_model,
            voice_id=voice_id,
            text=entry["content"],
        )

    for entry in entries:
        number = entry["number"]
        source = pack_root / "source_mp3" / entry["audio_file"]
        seq = number.zfill(3)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(pack_root / "audio_24k" / f"seq{seq}.wav"),
            "-vn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(pack_root / "audio_ascii_8k" / f"seq{seq}.wav"),
            "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-c:a", "pcm_s16le", str(pack_root / "audio_pcm16_8k" / f"seq{seq}.pcm"),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"音频 {number} 转码失败：{result.stderr.strip()}")

    _write_cache_files(pack_root, entries, voice_model=voice_model, voice_id=voice_id)
    return entries


def _write_cache_files(pack_root: Path, entries: list[dict[str, str]], *, voice_model: str, voice_id: str) -> None:
    manifest_path = pack_root / "manifests" / "natural_v2_manifest_ascii.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "seq", "scene_id", "scene_title", "section", "customer_trigger", "human_text",
                "ascii_filename", "audio_format", "source_mp3",
            ],
        )
        writer.writeheader()
        for entry in entries:
            seq = entry["number"].zfill(3)
            writer.writerow(
                {
                    "seq": seq,
                    "scene_id": entry["number"],
                    "scene_title": Path(entry["audio_file"]).stem,
                    "section": entry["category"],
                    "customer_trigger": entry["customer_trigger"],
                    "human_text": entry["content"],
                    "ascii_filename": f"seq{seq}.wav",
                    "audio_format": "pcm_s16le_8000_mono",
                    "source_mp3": entry["audio_file"],
                }
            )

    intent_path = pack_root / "specs" / "INTENT_MAPPING_SEED.csv"
    with intent_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["intent_id", "priority", "seq_candidates", "scene_title", "trigger_examples", "recommended_action"],
        )
        writer.writeheader()
        for entry in entries:
            seq = entry["number"].zfill(3)
            writer.writerow(
                {
                    "intent_id": f"script_{entry['number']}",
                    "priority": "P0" if entry["number"] in {"01", "23", "24", "25", "26", "46"} else "P1",
                    "seq_candidates": seq,
                    "scene_title": Path(entry["audio_file"]).stem,
                    "trigger_examples": f"{entry['customer_trigger']}|{entry['content']}",
                    "recommended_action": "play_cached",
                }
            )

    meta = {
        "profile": VOICE_PACK_PROFILE,
        "displayName": VOICE_PROFILE_NAME,
        "assetVersion": VOICE_PACK_VERSION,
        "openingSeq": "001",
        "itemCount": len(entries),
        "excludedPendingIds": sorted(PENDING_IDS),
        "voiceModel": voice_model,
        "voiceId": voice_id,
        "regeneratedIds": sorted(REGENERATE_IDS),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    (pack_root / "voice_cache_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_setting(db: Any, item_key: str, value: str) -> None:
    setting = db.scalar(
        select(SystemSetting).where(SystemSetting.group_key == "model", SystemSetting.item_key == item_key)
    )
    label, description = SETTING_META[item_key]
    if setting is None:
        setting = SystemSetting(group_key="model", item_key=item_key, label=label, value_type="text")
        db.add(setting)
    setting.label = label
    setting.value = value
    setting.status = "已配置"
    setting.description = description
    setting.updated_by = "话术语音导入"
    setting.updated_at = _utcnow()


def _import_database(entries: list[dict[str, str]], pack_root: Path, *, voice_model: str, voice_id: str) -> dict[str, str]:
    audio_mapping = {entry["number"]: entry["audio_file"] for entry in entries}
    with SessionLocal() as db:
        for script in db.scalars(select(CallScript)).all():
            script.is_active = False
        script = db.scalar(select(CallScript).where(CallScript.name == SCRIPT_NAME))
        values = {
            "opening": next(entry["content"] for entry in entries if entry["number"] == "01"),
            "qualification": "按主流程 1-5：摸底当前获客渠道；只讲微信支付手续费千分之六；依次讲同城流量、微信裂变、私域沉淀；说明全托管；收口加微信发案例。",
            "objection": "按已确认的结构化条目回答。电话中不报本公司服务价，不冒充腾讯官方，不承诺订单或效果，不贬低美团抖音；未确认的公司政策或人设信息统一转顾问确认。",
            "closing": "您这个号就是微信吧？我加您，把案例发您看。客户明确拒绝时礼貌结束并标记勿扰。",
            "entries": entries,
            "audio_mapping": audio_mapping,
            "is_active": True,
        }
        if script is None:
            script = CallScript(name=SCRIPT_NAME, **values)
            db.add(script)
        else:
            for key, value in values.items():
                setattr(script, key, value)

        profile = db.scalar(select(VoiceProfile).where(VoiceProfile.name == VOICE_PROFILE_NAME))
        if profile is None:
            profile = VoiceProfile(name=VOICE_PROFILE_NAME)
            db.add(profile)
            db.flush()
        profile.owner_name = "已授权招商顾问"
        profile.scenario = "视频号团购外呼"
        profile.status = "可用"
        profile.authorization_status = "授权通过"
        profile.sample_count = len(entries)
        profile.fallback_voice = "DashScope omni 内置音色"
        profile.consent_material = "用户提供的已授权克隆语音包；原始授权样本不入 Git。"
        profile.risk_note = "74 条确认话术已导入；7 条带警告的政策/人设条目未导入。"
        profile.updated_at = _utcnow()

        record = db.scalar(select(VoiceCloneRecord).where(VoiceCloneRecord.external_voice_id == voice_id))
        if record is None:
            record = VoiceCloneRecord(profile_id=profile.id, external_voice_id=voice_id)
            db.add(record)
        record.profile_id = profile.id
        record.cloned_voice_name = VOICE_PROFILE_NAME
        record.engine = f"DashScope {voice_model}"
        record.preview_audio_path = str((pack_root / "audio_24k" / "seq001.wav").resolve())
        record.status = "可用"
        record.sample_count = len(entries)
        record.result = json.dumps(
            {"packVersion": VOICE_PACK_VERSION, "itemCount": len(entries), "pendingExcluded": sorted(PENDING_IDS)},
            ensure_ascii=False,
        )
        record.completed_at = record.completed_at or _utcnow()

        for key, value in {
            "dashscope_voice_clone_model": voice_model,
            "dashscope_tts_model": voice_model,
            "realtime_tts_voice_id": voice_id,
            "realtime_tts_voice_name": VOICE_PROFILE_NAME,
            "realtime_tts_voice_type": "clone",
            "realtime_voice_cache_dir": str(pack_root.resolve()),
            "realtime_voice_cache_enabled": "true",
        }.items():
            _upsert_setting(db, key, value)
        db.commit()
        db.refresh(script)
        db.refresh(record)
        return {"scriptId": script.id, "voiceProfileId": profile.id, "voiceCloneRecordId": record.id}


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 2026-07-10 新话术与 74 条克隆语音包。")
    parser.add_argument("--source-zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--pack-root", type=Path, default=DEFAULT_PACK_ROOT)
    parser.add_argument("--voice-model", default=VOICE_MODEL)
    parser.add_argument("--voice-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_zip = args.source_zip.expanduser().resolve()
    pack_root = args.pack_root.expanduser().resolve()
    if not source_zip.is_file():
        raise SystemExit(f"找不到语音 ZIP：{source_zip}")
    lines = _load_confirmed_lines()
    pending_ids = _load_pending_ids()
    members = _zip_audio_members(source_zip)
    audio_ids = set(members)
    confirmed_ids = {str(row["id"])[:2] for row in lines}
    if audio_ids != confirmed_ids:
        raise SystemExit(f"ZIP 编号不匹配：缺少 {sorted(confirmed_ids - audio_ids)}，多出 {sorted(audio_ids - confirmed_ids)}")
    if ({f"{number:02d}" for number in range(1, 82)} - audio_ids) != pending_ids:
        raise SystemExit("ZIP 缺号与 7 条待确认清单不一致，拒绝导入。")

    filenames = {number: decoded for number, (_, decoded) in members.items()}
    entries = _structured_entries(lines, filenames)
    _validate_compliance(entries)
    if args.dry_run:
        print(json.dumps({"confirmed": len(entries), "excluded": sorted(pending_ids), "zipFiles": len(members)}, ensure_ascii=False))
        return

    voice_model, voice_id = _discover_clone_voice(args.voice_model, args.voice_id.strip())
    entries = _prepare_audio_pack(
        source_zip,
        pack_root,
        lines,
        members,
        voice_model=voice_model,
        voice_id=voice_id,
    )
    database_ids = _import_database(entries, pack_root, voice_model=voice_model, voice_id=voice_id)
    print(
        json.dumps(
            {
                "status": "ok",
                "script": SCRIPT_NAME,
                "confirmed": len(entries),
                "excluded": sorted(pending_ids),
                "packRoot": str(pack_root),
                "voiceModel": voice_model,
                "voiceId": voice_id,
                "regenerated": sorted(REGENERATE_IDS),
                **database_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
