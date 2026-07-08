"""LiveKit 外呼 Agent 主入口（PoC）。

链路：dial_api 创建房间并 dispatch 本 agent
  -> agent 通过外呼 trunk 让网关拨打客户号码（wait_until_answered）
  -> 接通后 AgentSession 启动，音频直连 Qwen Omni Realtime（语音进语音出）
  -> 客户挂断/超时 -> 删房间收尾，落延迟打点日志

运行（开发模式）：python main.py dev
运行（生产模式）：python main.py start

关键设计：
1. Qwen Omni 走 DashScope 的 OpenAI Realtime 兼容端点，复用 livekit openai 插件，
   不自己造 websocket 轮子（协议若有出入，只需调 _build_realtime_model）。
2. 判停用 Omni 的 server_vad（静音毫秒可调）。第二阶段可换 LiveKit 语义判停对照。
3. 垫词：客户说完的瞬间播放本地极短音频（嗯/哎好），掩盖模型首包延迟。
4. 全程延迟打点到 JSONL，验收看数据不靠感觉。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from dotenv import load_dotenv

from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import openai

from metrics_recorder import MetricsRecorder
from sales_prompt import OPENING_LINE, build_instructions

load_dotenv()

logger = logging.getLogger("outbound-agent")

AGENT_NAME = "outbound-caller"
MAX_CALL_SECONDS = 300  # 单通电话硬上限，防止对着语音信箱烧钱


def _build_realtime_model() -> openai.realtime.RealtimeModel:
    """Qwen Omni Realtime，走 DashScope 的 OpenAI 兼容 Realtime 端点。

    如 DashScope 协议与 OpenAI Realtime 有出入（字段名/事件名），在这里适配，
    不要改 main 流程。
    """
    silence_ms = int(os.getenv("VAD_SILENCE_MS", "400"))
    return openai.realtime.RealtimeModel(
        base_url=os.getenv("QWEN_REALTIME_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"),
        model=os.getenv("QWEN_REALTIME_MODEL", "qwen3-omni-flash-realtime"),
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        voice=os.getenv("QWEN_VOICE", "Cherry"),
        temperature=0.7,
        turn_detection=openai.realtime.TurnDetection(
            type="server_vad",
            threshold=0.5,
            prefix_padding_ms=300,
            silence_duration_ms=silence_ms,
        ),
    )


class FillerPlayer:
    """垫词：判停瞬间播一个 ~0.4s 的本地音频（嗯/哎好），把体感响应压到 0.3-0.4s。

    音频要求：assets/filler_*.wav，48kHz 单声道 16bit PCM（gen_fillers.py 直接生成该格式）。
    """

    def __init__(self, room: rtc.Room, recorder: MetricsRecorder) -> None:
        self._recorder = recorder
        self._clips: list[bytes] = []
        self._idx = 0
        self._source: rtc.AudioSource | None = None
        self._room = room
        self._load_clips()

    def _load_clips(self) -> None:
        import glob
        import wave

        asset_dir = os.path.join(os.path.dirname(__file__), "assets")
        for path in sorted(glob.glob(os.path.join(asset_dir, "filler_*.wav"))):
            try:
                with wave.open(path, "rb") as w:
                    if w.getframerate() != 48000 or w.getnchannels() != 1:
                        logger.warning("垫词 %s 不是 48kHz 单声道，跳过", path)
                        continue
                    self._clips.append(w.readframes(w.getnframes()))
            except Exception:
                logger.exception("读取垫词失败：%s", path)
        logger.info("已加载 %d 个垫词音频", len(self._clips))

    async def start(self) -> None:
        if not self._clips:
            return
        self._source = rtc.AudioSource(48000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("filler", self._source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN)
        )

    async def play_once(self) -> None:
        if not self._clips or self._source is None:
            return
        clip = self._clips[self._idx % len(self._clips)]
        self._idx += 1
        self._recorder.emit("filler_played", clip_index=self._idx)
        frame_samples = 480  # 10ms @48k
        for offset in range(0, len(clip), frame_samples * 2):
            chunk = clip[offset : offset + frame_samples * 2]
            if len(chunk) < frame_samples * 2:
                chunk = chunk + b"\x00" * (frame_samples * 2 - len(chunk))
            frame = rtc.AudioFrame(
                data=chunk, sample_rate=48000, num_channels=1, samples_per_channel=frame_samples
            )
            await self._source.capture_frame(frame)


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # dial_api 传入的按通参数
    try:
        dial_info = json.loads(ctx.job.metadata or "{}")
    except json.JSONDecodeError:
        dial_info = {}
    phone: str = dial_info.get("phone_number", "")
    merchant: str = dial_info.get("merchant_name", os.getenv("MERCHANT_NAME_DEFAULT", "您的门店"))
    call_id: str = dial_info.get("call_id") or f"lk-{uuid.uuid4().hex[:12]}"

    recorder = MetricsRecorder(os.getenv("METRICS_DIR", "./metrics_logs"), call_id, phone)

    if not phone:
        recorder.emit("call_error", error="metadata 缺少 phone_number")
        ctx.shutdown(reason="missing phone_number")
        return

    trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID", "")
    if not trunk_id:
        recorder.emit("call_error", error="SIP_OUTBOUND_TRUNK_ID 未配置")
        ctx.shutdown(reason="missing trunk id")
        return

    # ---- 会话（先建好，接通即用，不浪费接通后的时间）----
    session = AgentSession(llm=_build_realtime_model())
    agent = Agent(instructions=build_instructions(merchant))

    filler: FillerPlayer | None = None
    if os.getenv("ENABLE_FILLER", "true").lower() == "true":
        filler = FillerPlayer(ctx.room, recorder)

    # ---- 打点挂钩 ----
    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:  # noqa: ANN001
        recorder.on_metrics(ev)

    last_user_stop = {"t": 0.0}

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:  # noqa: ANN001
        state = getattr(ev, "new_state", None)
        recorder.emit("user_state", state=str(state))
        if str(state) == "listening":  # 客户从说话转为停止：立即垫词
            last_user_stop["t"] = time.perf_counter()
            if filler is not None:
                asyncio.create_task(filler.play_once())

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:  # noqa: ANN001
        state = str(getattr(ev, "new_state", ""))
        recorder.emit("agent_state", state=state)
        if state == "speaking" and last_user_stop["t"]:
            # 客户停 -> AI 出声：这就是验收要看的真实转向延迟
            recorder.emit(
                "turn_latency",
                latency_ms=int((time.perf_counter() - last_user_stop["t"]) * 1000),
            )
            last_user_stop["t"] = 0.0

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:  # noqa: ANN001
        item = getattr(ev, "item", None)
        role = str(getattr(item, "role", ""))
        text = str(getattr(item, "text_content", "") or "")
        if text:
            recorder.emit("transcript", role=role, text=text[:200])

    # ---- 拨号：通过 trunk 让网关呼出，等待接通 ----
    recorder.emit("dial_start", trunk=trunk_id)
    dial_started = time.perf_counter()
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=trunk_id,
                sip_call_to=phone,
                participant_identity=f"callee-{phone}",
                wait_until_answered=True,
            )
        )
    except api.TwirpError as e:
        recorder.emit("dial_failed", error=str(e.message), sip_status=str(getattr(e, "metadata", {})))
        ctx.shutdown(reason="dial failed")
        return

    recorder.emit("call_connected", dial_seconds=round(time.perf_counter() - dial_started, 2))

    # ---- 接通：启动会话 + 垫词轨 + 开场白 ----
    await session.start(agent=agent, room=ctx.room)
    if filler is not None:
        await filler.start()

    # 接通立刻主动开口，不等客户先喂（旧系统最大的痛点之一）
    opening_at = time.perf_counter()
    await session.say(OPENING_LINE, allow_interruptions=True)
    recorder.emit("opening_spoken", elapsed_ms=int((time.perf_counter() - opening_at) * 1000))

    # ---- 客户挂断 -> 收尾；到时硬上限 -> 主动挂 ----
    hangup_event = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def _on_leave(p: rtc.RemoteParticipant) -> None:
        if p.identity.startswith("callee-"):
            recorder.emit("callee_hangup")
            hangup_event.set()

    try:
        await asyncio.wait_for(hangup_event.wait(), timeout=MAX_CALL_SECONDS)
    except asyncio.TimeoutError:
        recorder.emit("call_timeout", limit_seconds=MAX_CALL_SECONDS)

    recorder.emit("call_ended")
    with contextlib_suppress():
        await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
    ctx.shutdown(reason="call ended")


class contextlib_suppress:
    """轻量 suppress，避免收尾报错掩盖真实日志。"""

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *exc):  # noqa: ANN002, ANN204
        return True

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
        return True


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )
