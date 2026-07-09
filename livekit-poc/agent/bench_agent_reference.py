"""
思维树 AI 外呼 Agent - LiveKit + DashScope Qwen-Omni-Realtime
通过自定义 RealtimeModel adapter 直连 DashScope
"""
import os
import json
import logging
import asyncio
from dotenv import load_dotenv
load_dotenv()
from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.types import NOT_GIVEN
from qwen_omni_realtime import QwenOmniRealtimeModel

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("outbound-agent")

# DashScope Qwen-Omni-Realtime 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
MODEL = os.getenv("QWEN_MODEL", "qwen3-omni-flash-realtime")
VOICE = os.getenv("QWEN_VOICE", "Ethan")

BASE_RULES = """你是视频号团购服务商的电话顾问，正在和本地实体店老板通电话。

【身份与称呼——铁律】
- 自称只用"我"。绝对不要说出"刘顾问"三个字——开场白里已经介绍过了，再说非常怪
- 称呼客户"老板"或"您"
- 真人销售的语气，口语化短句，绝不用书面语

【说话铁律】
- 每次回复只说一句话，最多两个短句，说完立刻停，等客户接话
- 一次只干一件事：要么回应，要么问一个问题，绝不能又答又问又推销
- 问了问题就闭嘴等答案，绝不自问自答
- 客户开口立刻停下听

【参考知识（用自己的话说，别背）】
- 视频号团购：帮实体店把团购挂到店铺定位上，客人刷视频、搜同城能看到，买券到店核销
- 卖点（一次只讲一个）：平台只收千分之六微信支付手续费、无抽成；周边3-5公里免费同城流量；客人能转发朋友圈裂变；核销时顺手加客户微信，客源沉淀自己手里
- 核销：手机扫码，不动现有收银系统，跟美团收银不冲突
- 外卖：骑手体系还没完善，实话实说，现阶段主做到店核销和自取
- 小程序：对接腾讯官方端口开发，钱走微信支付直接进商家自己账户
- 公司：南昌青山湖区紫阳大道1054号绿地集团写字楼，执照可发，欢迎实地考察
- 开通资料：主要三样——营业执照、法人身份证、门头照
- 价格：电话里绝对不报任何数字。问价就说"费用不高，看店型，方案和报价我微信发您，白纸黑字说得清楚"
- 答不准的问题绝不编造，统一说"这个我微信上发资料给您讲清楚"

【红线】不冒充腾讯官方（自称视频号服务商）；不承诺订单量；不贬低美团抖音；客户明确说别打了，立刻道别

【结束通话】客户明确拒绝两次、说要挂/在忙没空、或已确认好微信——用一句话道别，必须带"不打扰您了"和"再见"（这两个词是挂断暗号，其他任何时候严禁出现），说完系统自动挂断，不要再找新话题
"""

STAGE_PROMPTS = {
    "icebreak": """
【当前阶段：破冰——刚播完开场白】
- 你的任务只有一个：接住客户的第一反应，让对话自然继续
- 他问"什么东西/没听清"→ 一句话解释视频号团购是干嘛的
- 他说"开了/没开/在用美团"→ 顺着接一句，再问一个问题
- 本阶段严禁出现"微信"两个字，严禁连报多个卖点，严禁推销腔
""",
    "value": """
【当前阶段：讲价值】
- 一次只讲一个好处，挑和客户上一句最相关的那个
- 客户问什么答什么，答完最多反问一个问题
- 本阶段不要主动提加微信；只有客户自己要资料/要联系方式时才能顺势说微信
""",
    "close": """
【当前阶段：收网——时机已到】
- 现在可以自然提出："我微信把案例和营业执照发您，您这号就是微信吧？"
- 客户同意 → 确认这个手机号是不是微信号；不是就问微信号并复述确认，然后道别
- 客户犹豫 → 降门槛："就发几个同行案例您看看，不合适划走就行"
- 提微信整通不超过三次，两次之间必须隔一轮正常对话；三次被拒就礼貌道别
- 客户说忙 → "一句话，手续费才千分之六，加个微信我发资料您得空看"，确认微信后道别
""",
}

# 兼容旧引用：初始指令 = 基础规则 + 破冰阶段
INSTRUCTIONS = BASE_RULES + STAGE_PROMPTS["icebreak"]

OPENING_TEXT = (
    "老板您好！耽误您半分钟，我是做视频号团购的刘顾问，"
    "专门帮实体店从微信上拉客人到店。想问下，咱店里这块开通了没？"
)
# 兜底：没有 opening.wav 时退回模型即兴（不保证一字不差）
OPENING_LINE = "把下面这句开场白一字不差地说出来，不要增减、不要改写任何内容：" + OPENING_TEXT
OPENING_WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opening.wav")


class OpeningPlayer:
    """固定开场白录音：接通即播、一字不差、可被客户说话打断。

    为什么不用模型说开场白：conversation.item.create 会被 DashScope 静默忽略，
    模型只凭 session instructions 即兴发挥，无法保证照稿（真机反复验证）。
    """

    def __init__(self, room: "rtc.Room", path: str) -> None:
        self._room = room
        self._stop = False
        self._data = self._load(path)

    @staticmethod
    def _load(path: str) -> bytes:
        import struct
        import wave as _wave

        with _wave.open(path, "rb") as w:
            assert w.getframerate() == 24000 and w.getnchannels() == 1
            data = w.readframes(w.getnframes())

        def rms(seg: bytes) -> float:
            n = len(seg) // 2
            if not n:
                return 0.0
            ss = struct.unpack(f"<{n}h", seg[: n * 2])
            return (sum(x * x for x in ss) / n) ** 0.5

        win = 4800  # 100ms @24k
        start, end = 0, len(data)
        while start + win < end and rms(data[start:start + win]) < 200:
            start += win
        while end - win > start and rms(data[end - win:end]) < 200:
            end -= win
        return data[start:end]

    def stop(self) -> None:
        self._stop = True

    async def play(self) -> None:
        src = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("opening", src)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN)
        )
        logger.info("固定开场白开始播放（%.1fs）", len(self._data) / 48000)
        for i in range(0, len(self._data), 480):
            if self._stop:
                logger.info("开场白被客户说话打断，停止播放")
                break
            chunk = self._data[i:i + 480]
            if len(chunk) < 480:
                chunk += b"\x00" * (480 - len(chunk))
            await src.capture_frame(
                rtc.AudioFrame(data=chunk, sample_rate=24000, num_channels=1, samples_per_channel=240)
            )
        logger.info("固定开场白播放结束")


class OutboundAgent(Agent):
    def __init__(self):
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self):
        try:
            room_name = self.session.room_io.room.name
        except Exception:
            room_name = "unknown"
        logger.info("Agent 进入房间 %s", room_name)


async def _play_greeting(session: AgentSession, opening_player: "OpeningPlayer | None"):
    """SIP 接听后播开场白：优先固定录音（一字不差），无录音才退回模型即兴。"""
    await asyncio.sleep(0.3)
    logger.info("触发开场白")
    if opening_player is not None:
        await opening_player.play()
        return
    try:
        await session.generate_reply(instructions=OPENING_LINE)
        logger.info("开场白 generate_reply 已触发（兜底模式）")
    except Exception as e:
        logger.exception("开场白失败: %s", e)


async def entrypoint(ctx: JobContext):
    logger.info("连接 LiveKit room: %s", ctx.room.name)
    await ctx.connect()

    if not DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY 环境变量未设置")

    answered_event = asyncio.Event()
    greeting_triggered = False
    lead_phone = {"v": ""}  # 被叫号码（从 SIP participant identity 提取）
    sip_track = {"t": None}  # 客户音频轨（本地 VAD 用）

    def _on_track_subscribed(track, publication, participant):
        nonlocal greeting_triggered
        identity = getattr(participant, "identity", "") or ""
        source = getattr(publication, "source", None)
        logger.info("track_subscribed: identity=%s source=%s", identity, source)
        if identity.startswith("sip_"):
            lead_phone["v"] = identity[4:]
            if getattr(track, "kind", None) == rtc.TrackKind.KIND_AUDIO and sip_track["t"] is None:
                sip_track["t"] = track
        if identity.startswith("sip_") and not greeting_triggered:
            greeting_triggered = True
            logger.info("检测到 SIP participant %s 的音频轨道已订阅（信道已通，等真人开口）", identity)
            answered_event.set()

    def _on_track_published(publication, participant):
        identity = getattr(participant, "identity", "") or ""
        source = getattr(publication, "source", None)
        logger.info("track_published: identity=%s source=%s", identity, source)
        if identity.startswith("sip_") and str(source) == "SOURCE_MICROPHONE":
            logger.info("SIP participant %s 已发布麦克风轨道", identity)
            try:
                ctx.room.local_participant.subscribe(publication)
            except Exception as e:
                logger.warning("订阅 SIP 轨道失败: %s", e)

    def _on_participant_connected(participant):
        identity = getattr(participant, "identity", "") or ""
        logger.info("participant_connected: %s", identity)

    def _on_participant_disconnected(participant):
        identity = getattr(participant, "identity", "") or ""
        logger.info("participant_disconnected: %s", identity)

    ctx.room.on("track_subscribed", _on_track_subscribed)
    ctx.room.on("track_published", _on_track_published)
    ctx.room.on("participant_connected", _on_participant_connected)
    ctx.room.on("participant_disconnected", _on_participant_disconnected)

    llm_model = QwenOmniRealtimeModel(
        model=MODEL,
        api_key=DASHSCOPE_API_KEY,
        voice=VOICE,
        instructions=BASE_RULES + STAGE_PROMPTS["icebreak"],
    )
    session = AgentSession(llm=llm_model)

    # ---- 话术状态机：破冰 -> 讲价值 -> 收网，由代码控节奏，不靠模型自觉 ----
    stage = {"v": "icebreak"}
    user_turns = {"n": 0}
    _INTENT_KWS = ("多少钱", "价格", "费用", "怎么弄", "怎么做", "怎么开通", "什么资料",
                   "有效果", "流程", "怎么收费", "发我看看", "了解一下", "案例")
    _BUSY_KWS = ("在忙", "开车", "没空", "没时间", "回头再", "一会再", "等会")

    def _set_stage(new: str) -> None:
        if stage["v"] == new:
            return
        stage["v"] = new
        logger.info("【话术阶段】切换 -> %s", new)
        rt = getattr(llm_model, "last_session", None)
        if rt is not None:
            asyncio.create_task(rt.update_instructions(BASE_RULES + STAGE_PROMPTS[new]))

    shutdown_event = asyncio.Event()

    async def _on_shutdown(reason: str):
        # add_shutdown_callback 需要协程函数，同步函数会报 "a coroutine was expected"
        logger.info("收到 job shutdown: %s", reason)
        shutdown_event.set()

    ctx.add_shutdown_callback(_on_shutdown)

    opening_player = OpeningPlayer(ctx.room, OPENING_WAV) if os.path.exists(OPENING_WAV) else None
    if opening_player is None:
        logger.warning("未找到 opening.wav，开场白退回模型即兴（不保证照稿）")

    # ---- 状态日志（打断延迟排障用）+ 自动挂断（道别/静默/硬上限）----
    import time as _time
    from livekit import api as lk_api

    last_activity = {"t": _time.monotonic()}
    hangup_flag = {"v": False}

    async def _hangup(reason: str, delay: float = 0.0) -> None:
        if hangup_flag["v"]:
            return
        hangup_flag["v"] = True
        if delay:
            await asyncio.sleep(delay)
        logger.info("主动挂断: %s", reason)
        try:
            await ctx.api.room.delete_room(lk_api.DeleteRoomRequest(room=ctx.room.name))
        except Exception as e:
            logger.warning("删除房间失败: %s", e)

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        logger.info("agent_state -> %s", getattr(ev, "new_state", ""))
        last_activity["t"] = _time.monotonic()

    @session.on("user_state_changed")
    def _on_user_state(ev):
        st = str(getattr(ev, "new_state", ""))
        logger.info("user_state -> %s", st)
        last_activity["t"] = _time.monotonic()
        if st == "speaking" and opening_player is not None:
            opening_player.stop()  # 客户开口，立即停掉开场白录音

    _FAREWELLS = ("再见", "不打扰")

    call_started = {"t": 0.0}

    # ---- 意向客户标记：AI 问过微信 + 客户同意 => 写入 intent_leads.jsonl ----
    wechat_ask = {"pending": 0, "ai_text": ""}   # AI 要微信后，给客户 2 轮回应窗口
    lead_marked = {"v": False}
    _WECHAT_ASK_HINTS = ("微信", "加您", "加个微信", "加一下")
    _AGREE_WORDS = ("可以", "行", "好的", "好啊", "嗯", "加吧", "发吧", "就是微信", "是微信", "同意", "没问题")
    _REFUSE_WORDS = ("不用", "不加", "别加", "不需要", "不方便", "不行")
    _INTENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_leads.jsonl")

    def _mark_lead(customer_text: str) -> None:
        if lead_marked["v"]:
            return
        lead_marked["v"] = True
        record = {
            "time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "phone": lead_phone["v"],
            "room": getattr(ctx.room, "name", ""),
            "level": "A",
            "reason": "客户同意加微信",
            "ai_ask": wechat_ask["ai_text"][:120],
            "customer_reply": customer_text[:120],
        }
        with open(_INTENT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("【意向客户已标记】%s -> %s", lead_phone["v"], customer_text[:60])

    @session.on("conversation_item_added")
    def _on_item(ev):
        item = getattr(ev, "item", None)
        role = str(getattr(item, "role", ""))
        text = str(getattr(item, "text_content", "") or "")
        if role == "user" and text:
            user_turns["n"] += 1
            if ("微信" in text) or any(k in text for k in _INTENT_KWS) or any(k in text for k in _BUSY_KWS):
                _set_stage("close")   # 意向信号/客户赶时间 -> 直接收网
            elif stage["v"] == "icebreak" and user_turns["n"] >= 1:
                _set_stage("value")   # 第一反应接住之后进入讲价值
            elif stage["v"] == "value" and user_turns["n"] >= 4:
                _set_stage("close")   # 聊了几轮还没信号，主动收网
        if role == "assistant" and any(w in text for w in _WECHAT_ASK_HINTS):
            wechat_ask["pending"] = 2
            wechat_ask["ai_text"] = text
        elif role == "user" and wechat_ask["pending"] > 0:
            if any(w in text for w in _REFUSE_WORDS):
                wechat_ask["pending"] = 0
            elif any(w in text for w in _AGREE_WORDS):
                _mark_lead(text)
                wechat_ask["pending"] = 0
            else:
                wechat_ask["pending"] -= 1
        if role == "assistant" and any(w in text for w in _FAREWELLS):
            # 保护：接通 20 秒内不因道别语挂断（防模型口滑/话术污染误触发）
            if call_started["t"] and _time.monotonic() - call_started["t"] < 20.0:
                logger.warning("AI 过早说出道别语（接通<20s），忽略挂断触发")
                return
            logger.info("检测到 AI 道别，4 秒后自动挂断")
            asyncio.create_task(_hangup("AI 道别", delay=4.0))

    MAX_CALL_SECONDS = int(os.getenv("MAX_CALL_SECONDS", "300"))
    IDLE_HANGUP_SECONDS = float(os.getenv("IDLE_HANGUP_SECONDS", "25"))

    async def _watchdog() -> None:
        start = _time.monotonic()
        while not shutdown_event.is_set() and not hangup_flag["v"]:
            await asyncio.sleep(2.0)
            if _time.monotonic() - start > MAX_CALL_SECONDS:
                await _hangup(f"到达单通硬上限 {MAX_CALL_SECONDS}s（防语音信箱空耗）")
                return
            if _time.monotonic() - last_activity["t"] > IDLE_HANGUP_SECONDS:
                await _hangup(f"双方静默超 {IDLE_HANGUP_SECONDS:.0f}s")
                return

    try:
        await session.start(agent=OutboundAgent(), room=ctx.room)
        logger.info("AgentSession 已启动，等待 SIP 接听...")

        # 等待信道接通 -> 本地 VAD 等真人开口 -> 播开场白（治网关"提前应答"）
        try:
            await asyncio.wait_for(answered_event.wait(), timeout=25.0)

            import struct as _struct

            SPEAK_RMS = int(os.getenv("OPENING_SPEAK_RMS", "600"))       # 人声能量阈值
            SUSTAIN_S = float(os.getenv("OPENING_SUSTAIN_S", "0.30"))    # 持续多久算真开口
            FALLBACK_S = float(os.getenv("OPENING_FALLBACK_S", "8.0"))   # 兜底：没等到也播
            human_spoke = asyncio.Event()
            greeting_on = {"v": False}

            def _rms16(buf: bytes) -> float:
                n = len(buf) // 2
                if n == 0:
                    return 0.0
                try:
                    s = _struct.unpack(f"<{n}h", buf[: n * 2])
                except _struct.error:
                    return 0.0
                return (sum(x * x for x in s) / n) ** 0.5

            async def _local_vad() -> None:
                """本地能量 VAD：接通前不喂 DashScope，靠它判断真人开口 + 开场白期间打断。"""
                track = sip_track["t"]
                if track is None:
                    human_spoke.set()  # 拿不到轨，退回立即播
                    return
                stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
                speaking_since = None
                async for ev in stream:
                    loud = _rms16(bytes(ev.frame.data)) > SPEAK_RMS
                    now = _time.monotonic()
                    if not greeting_on["v"]:
                        # 阶段A：等真人持续开口
                        if loud:
                            if speaking_since is None:
                                speaking_since = now
                            elif now - speaking_since >= SUSTAIN_S:
                                logger.info("本地 VAD 检测到真人开口，触发开场白")
                                human_spoke.set()
                        else:
                            speaking_since = None
                    else:
                        # 阶段B：开场白播放中，客户出声即打断
                        if loud and opening_player is not None:
                            opening_player.stop()

            rt = getattr(llm_model, "last_session", None)
            if rt is not None:
                rt.input_open = False  # 关输入总闸：接通前客户音频不进模型

            vad_task = asyncio.create_task(_local_vad())
            try:
                await asyncio.wait_for(human_spoke.wait(), timeout=FALLBACK_S)
            except asyncio.TimeoutError:
                logger.info("等真人开口超时(%.0fs)，兜底直接播开场白", FALLBACK_S)

            greeting_on["v"] = True
            call_started["t"] = _time.monotonic()
            await _play_greeting(session, opening_player)   # 播完/被打断才返回

            if rt is not None:
                rt.input_open = True  # 开输入总闸：正式进入对话
            logger.info("开场白结束，输入总闸打开，进入对话")
            asyncio.create_task(_watchdog())
        except asyncio.TimeoutError:
            logger.warning("25 秒内未检测到 SIP 接听")

        logger.info("等待 shutdown...")
        await shutdown_event.wait()
    finally:
        logger.info("Agent session 结束")
