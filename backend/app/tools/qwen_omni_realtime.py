"""
Qwen-Omni-Realtime LiveKit RealtimeModel 适配器（真机验证版 2026-07-08）

来源：Workbuddy 本地开发 + 当日真实通话/自测验证，含 5 个关键修复：
1. modalities 立即声明（原来等 response.done 才声明，框架把音频整句憋住不播）
2. 输出音频按 10ms 分帧（框架对大帧静默丢弃 -> AI 无声）
3. 开场白：DashScope 忽略"空上下文 + 手动 response.create"，
   generate_reply(instructions=...) 自动转为 conversation.item.create + response.create
4. 输入重采样奇数字节截断（LiveKit 音频帧偶发奇数字节导致 struct.error）
5. 【竞态·最关键】MessageGeneration 的发送移入 response.created 协程（事件循环线程），
   不再依赖 output_item.added（ws 线程）时 _current_gen 是否就绪。这是"间歇性不说话"
   的真正根源：修前自测 10 次仅约 37% 出声，修后 10/10 出声。

验证证据：自测连续 10/10 录到 AI 语音、客户语音逐字识别、打断正常（见 livekit-poc/README.md）。
判停延迟 silence_duration_ms 通过环境变量 VAD_SILENCE_MS 配置（默认 400ms，
实测 800ms 时转向延迟 ~1.3s，400ms 目标 ~0.9s；小于 300 容易抢话）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from typing import Optional

import websocket
from livekit import rtc
from livekit.agents import llm, utils
from livekit.agents.llm import (
    GenerationCreatedEvent,
    MessageGeneration,
    RealtimeCapabilities,
    RealtimeModel,
    RealtimeSession,
)
from livekit.agents.types import NOT_GIVEN

logger = logging.getLogger("qwen-omni-realtime")

DASHSCOPE_WSS = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
DEFAULT_MODEL = "qwen3-omni-flash-realtime"
DEFAULT_VOICE = "Chelsie"


class QwenOmniRealtimeModel(RealtimeModel):
    def __init__(self, *, model: str = DEFAULT_MODEL, api_key: str, voice: str = DEFAULT_VOICE,
                 instructions: str = "", base_url: str = DASHSCOPE_WSS) -> None:
        self._capabilities = RealtimeCapabilities(
            turn_detection=True, user_transcription=True, audio_output=True,
            message_truncation=False, auto_tool_reply_generation=False, manual_function_calls=False,
        )
        super().__init__(capabilities=self._capabilities)
        self._model = model
        self._api_key = api_key
        self._voice = voice
        self._instructions = instructions
        self._base_url = base_url

    @property
    def label(self) -> str:
        return f"Qwen-Omni-Realtime ({self._model})"

    @property
    def capabilities(self) -> RealtimeCapabilities:
        return self._capabilities

    def session(self) -> "QwenOmniRealtimeSession":
        return QwenOmniRealtimeSession(self)

    async def aclose(self) -> None:
        pass


class _Generation:
    def __init__(self):
        self.message_ch: utils.aio.Chan[MessageGeneration] = utils.aio.Chan()
        self.function_ch: utils.aio.Chan = utils.aio.Chan()
        self.text_ch: utils.aio.Chan[str] = utils.aio.Chan()
        self.audio_ch: utils.aio.Chan[rtc.AudioFrame] = utils.aio.Chan()
        self.message_id: str = ""
        self.modalities_fut: asyncio.Future = asyncio.Future()
        # 输出音频分帧缓冲：官方插件都按 10ms 帧送，框架对大帧可能静默丢弃
        self.audio_buf: bytearray = bytearray()


class QwenOmniRealtimeSession(RealtimeSession):
    def __init__(self, model: QwenOmniRealtimeModel) -> None:
        super().__init__(realtime_model=model)
        self._model = model
        self._loop = asyncio.get_event_loop()
        self._closed = False
        self._ws: Optional[websocket.WebSocketApp] = None
        self._send_lock = threading.Lock()
        self._reply_futures: dict[str, asyncio.Future] = {}
        self._current_gen: Optional[_Generation] = None
        self._chat_ctx = None
        self._tools: list = []
        self._session_ready = False
        self._pending_reply: Optional[dict] = None
        self._pending_auto_reply_timer: Optional[asyncio.TimerHandle] = None
        self._wait_connected = threading.Event()
        # 【2026-07-09 暗坑3】DashScope 在 server_vad 模式下、输入音频流活跃时，
        # 会静默忽略手动 conversation.item.create + response.create（开场白因此
        # 间歇性不响，探针 probe_v2.py 可复现）。修法：开场白（首个 response）
        # 完成前不向服务端喂输入音频。代价：开场那几秒检测不到客户插话，可接受。
        self._first_response_done = False
        self._input_gate_deadline = time.monotonic() + 12.0  # 失效保护：12s 后强制放开
        self._connect()

    @property
    def chat_ctx(self):
        return self._chat_ctx

    @property
    def tools(self):
        return self._tools

    # ===== 连接 =====
    def _connect(self) -> None:
        url = f"{self._model._base_url}?model={self._model._model}"
        headers = [f"Authorization: Bearer {self._model._api_key}"]
        self._ws = websocket.WebSocketApp(
            url, header=headers,
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close,
        )
        threading.Thread(target=self._ws.run_forever, daemon=True).start()
        self._wait_connected.wait(timeout=10)

    def _on_open(self, ws):
        logger.info("DashScope wss connected")

    def _on_error(self, ws, error):
        logger.error("DashScope wss error: %s", error)

    def _on_close(self, ws, code, msg):
        logger.info("DashScope wss closed: code=%s", code)
        self._closed = True

    def _on_message(self, ws, message):
        try:
            obj = json.loads(message)
        except Exception:
            return
        t = obj.get("type", "")
        logger.info("_on_message 收到: %s", t)
        if t == "session.created":
            self._send_session_update()
            self._wait_connected.set()
        elif t == "session.updated":
            logger.info("session.updated OK")
            self._session_ready = True
            if self._pending_reply:
                logger.info("发送缓存的 response.create")
                self._send(self._pending_reply)
                self._pending_reply = None
        elif t == "input_audio_buffer.speech_started":
            asyncio.run_coroutine_threadsafe(self._emit_speech_started(), self._loop)
        elif t == "input_audio_buffer.speech_stopped":
            asyncio.run_coroutine_threadsafe(self._handle_speech_stopped(), self._loop)
        elif t == "response.created":
            rid = obj.get("response", {}).get("id", "")
            self._handle_response_created(rid)
        elif t == "response.output_item.added":
            # 竞态修复：MessageGeneration 的发送已移入 _handle_response_created_async
            # （与 generation_created 同在事件循环线程一次性完成）。本事件只更新 id，
            # 不再负责发送——原来在这里发送会因 _current_gen 尚未就绪而丢失，
            # 导致约 60% 概率框架拿不到音频流、整句无声。
            item = obj.get("item", {})
            if item.get("type") == "message" and self._current_gen:
                self._current_gen.message_id = item.get("id", "")
        elif t == "response.audio.delta":
            self._handle_audio_delta(obj.get("delta", ""))
        elif t == "response.audio_transcript.delta":
            delta = obj.get("delta", "")
            logger.info("AI 转录 delta: %s", delta)
            if self._current_gen:
                self._current_gen.text_ch.send_nowait(delta)
        elif t == "response.done":
            self._handle_response_done()
        elif t == "conversation.item.input_audio_transcription.completed":
            transcript = obj.get("transcript", "")
            logger.info("用户输入转录 completed: %s", transcript)
        elif t == "error":
            logger.error("DashScope error: %s", obj.get("error"))

    def _handle_response_created(self, response_id: str):
        asyncio.run_coroutine_threadsafe(
            self._handle_response_created_async(response_id), self._loop
        )

    async def _handle_response_created_async(self, response_id: str):
        if self._pending_auto_reply_timer:
            self._pending_auto_reply_timer.cancel()
            self._pending_auto_reply_timer = None
        gen = _Generation()
        gen.message_id = response_id
        # 关键：立刻声明本回复含音频。原来等到 response.done 才 set，
        # 框架会一直等 modalities 才开始播音频 -> 整句憋完才出声/根本没出声。
        gen.modalities_fut.set_result(["text", "audio"])
        self._current_gen = gen
        # 【2026-07-09 修复"只说开场白后续不说话"】user_initiated 只有在存在
        # pending 的 generate_reply 时才能为 True——框架 _on_generation_created 对
        # user_initiated=True 直接 return（由 _realtime_reply_task 消费 future）。
        # VAD 触发的回复必须标 False，否则永远不会排播。
        pending = None
        for eid, fut in list(self._reply_futures.items()):
            if not fut.done():
                pending = (eid, fut)
                break
        generation_ev = GenerationCreatedEvent(
            message_stream=gen.message_ch,
            function_stream=gen.function_ch,
            user_initiated=pending is not None,
            response_id=response_id,
        )
        if pending is not None:
            eid, fut = pending
            fut.set_result(generation_ev)
            self._reply_futures.pop(eid, None)
        self._emit_generation_created(generation_ev)
        # 竞态修复：紧接着（同在事件循环线程）把 MessageGeneration 送进 message_ch。
        # 不依赖 output_item.added 事件到达时机，保证框架一定拿到音频流句柄。
        mg = MessageGeneration(
            message_id=response_id,
            text_stream=gen.text_ch,
            audio_stream=gen.audio_ch,
            modalities=gen.modalities_fut,
        )
        gen.message_ch.send_nowait(mg)

    _OUT_RATE = 24000
    _FRAME_SAMPLES = 240  # 10ms @ 24kHz
    _FRAME_BYTES = _FRAME_SAMPLES * 2

    def _handle_audio_delta(self, delta_b64: str):
        gen = self._current_gen
        if not gen:
            return
        try:
            gen.audio_buf.extend(base64.b64decode(delta_b64))
            while len(gen.audio_buf) >= self._FRAME_BYTES:
                chunk = bytes(gen.audio_buf[: self._FRAME_BYTES])
                del gen.audio_buf[: self._FRAME_BYTES]
                frame = rtc.AudioFrame(
                    data=chunk, sample_rate=self._OUT_RATE,
                    num_channels=1, samples_per_channel=self._FRAME_SAMPLES,
                )
                gen.audio_ch.send_nowait(frame)
        except Exception as e:
            logger.error("audio delta error: %s", e)

    def _flush_audio_buf(self):
        gen = self._current_gen
        if not gen or not gen.audio_buf:
            return
        chunk = bytes(gen.audio_buf)
        gen.audio_buf.clear()
        if len(chunk) % 2 == 1:
            chunk = chunk[:-1]
        samples = len(chunk) // 2
        if samples:
            gen.audio_ch.send_nowait(
                rtc.AudioFrame(data=chunk, sample_rate=self._OUT_RATE, num_channels=1, samples_per_channel=samples)
            )

    def _handle_response_done(self):
        # 开场白（首个 response）完成，放开输入音频门控（暗坑3）
        self._first_response_done = True
        self._flush_audio_buf()
        if self._current_gen:
            if not self._current_gen.modalities_fut.done():
                self._current_gen.modalities_fut.set_result(["text", "audio"])  # 兜底
            self._current_gen.text_ch.close()
            self._current_gen.audio_ch.close()
            self._current_gen.message_ch.close()
            self._current_gen.function_ch.close()
            self._current_gen = None
        self._emit_response_done()

    def _send_session_update(self):
        config = {
            "modalities": ["text", "audio"],
            "voice": self._model._voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                "silence_duration_ms": int(__import__("os").getenv("VAD_SILENCE_MS", "400")), "create_response": True, "interrupt_response": True,
            },
        }
        if self._model._instructions:
            config["instructions"] = self._model._instructions
        self._send({"event_id": self._eid(), "type": "session.update", "session": config})

    def _send(self, data: dict):
        if self._closed or not self._ws:
            logger.warning("_send 跳过: closed=%s ws_exists=%s", self._closed, self._ws is not None)
            return
        with self._send_lock:
            try:
                self._ws.send(json.dumps(data))
                logger.info("_send 发送: %s", data.get("type"))
            except Exception as e:
                logger.error("send failed: %s", e)

    def _eid(self):
        return f"event_{int(time.time()*1000)}_{threading.get_ident() & 0xffff}"

    async def _emit_speech_started(self):
        # 【2026-07-09 修打断失效】必须带事件对象。原来 emit 不带参数，
        # 框架回调 _on_input_speech_started(ev) 直接 TypeError，而异常落在
        # run_coroutine_threadsafe 的 future 里被静默吞掉——interrupt() 永远
        # 不会执行，表现为"客户插话 AI 不停嘴"。
        self.emit("input_speech_started", llm.InputSpeechStartedEvent())

    async def _handle_speech_stopped(self):
        logger.info("用户说话结束，commit_audio 并等待服务端自动 response")
        self.commit_audio()
        self.emit("input_speech_stopped", llm.InputSpeechStoppedEvent(user_transcription_enabled=True))
        # Qwen realtime 有时不会自动创建 response，延迟后自动补一个
        if self._pending_auto_reply_timer:
            self._pending_auto_reply_timer.cancel()
        self._pending_auto_reply_timer = self._loop.call_later(
            0.8, self._auto_generate_reply
        )

    def _auto_generate_reply(self):
        # 如果当前没有正在处理的 generation，主动生成回复
        if self._current_gen is None and self._session_ready:
            logger.info("服务端未自动回复，主动 generate_reply")
            asyncio.run_coroutine_threadsafe(
                self._async_generate_reply(), self._loop
            )

    async def _async_generate_reply(self):
        try:
            await self.generate_reply()
        except Exception as e:
            logger.error("自动 generate_reply 失败: %s", e)

    def _emit_generation_created(self, ev):
        self.emit("generation_created", ev)

    def _emit_response_done(self):
        pass  # 通过 stream 关闭表达

    # ===== RealtimeSession 抽象方法 =====
    def push_audio(self, frame: rtc.AudioFrame) -> None:
        # 开场白完成前不喂音频（见 __init__ 的暗坑3注释），防止手动 response.create 被丢
        if not self._first_response_done and time.monotonic() < self._input_gate_deadline:
            return
        try:
            pcm = frame.data
            if frame.sample_rate != 16000:
                pcm = _resample(pcm, frame.sample_rate, 16000)
            if not pcm:
                return
            self._send({"event_id": self._eid(), "type": "input_audio_buffer.append",
                         "audio": base64.b64encode(pcm).decode("ascii")})
        except Exception as e:
            logger.error("push_audio 失败: %s", e)

    def commit_audio(self) -> None:
        self._send({"event_id": self._eid(), "type": "input_audio_buffer.commit"})

    def clear_audio(self) -> None:
        self._send({"event_id": self._eid(), "type": "input_audio_buffer.clear"})

    def generate_reply(self, *, instructions=NOT_GIVEN, tool_choice=NOT_GIVEN, tools=NOT_GIVEN) -> asyncio.Future:
        eid = self._eid()
        fut = self._loop.create_future()
        self._reply_futures[eid] = fut
        # DashScope 对"空上下文 + 手动 response.create"不响应（开场白因此从来没播过）。
        # 修法：先塞一条用户文本 item 进对话，再让模型响应它。
        if instructions is not NOT_GIVEN and instructions:
            self._send({
                "event_id": self._eid(),
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(instructions)}],
                },
            })
            instructions = NOT_GIVEN
        req = {"event_id": eid, "type": "response.create", "response": {}}
        if instructions is not NOT_GIVEN:
            req["response"]["instructions"] = instructions
        logger.info("generate_reply 发 response.create")
        if self._session_ready:
            self._send(req)
        else:
            logger.info("response.create 缓存，等 session.updated")
            self._pending_reply = req
        def _timeout():
            self._reply_futures.pop(eid, None)
            if not fut.done():
                fut.set_exception(llm.RealtimeError("generate_reply timeout"))
        self._loop.call_later(10.0, _timeout)
        return fut

    def interrupt(self) -> None:
        self._send({"event_id": self._eid(), "type": "response.cancel"})

    async def update_instructions(self, instructions: str) -> None:
        self._model._instructions = instructions
        self._send_session_update()

    async def update_chat_ctx(self, chat_ctx) -> None:
        pass

    async def update_tools(self, tools) -> None:
        pass

    async def update_options(self, *, tool_choice=NOT_GIVEN) -> None:
        pass

    async def truncate(self, *, message_id, modalities, audio_end_ms, audio_transcript=NOT_GIVEN) -> None:
        pass

    def push_video(self, frame: rtc.VideoFrame) -> None:
        pass

    async def aclose(self) -> None:
        self._closed = True
        if self._ws:
            self._ws.close()


def _resample(data: bytes, from_rate: int, to_rate: int) -> bytes:
    import struct
    data = bytes(data)
    # LiveKit 音频帧偶尔会出现奇数字节，截断为偶数
    if len(data) % 2 == 1:
        data = data[:-1]
    n_samples = len(data) // 2
    if n_samples == 0:
        return b""
    expected = n_samples * 2
    if len(data) != expected:
        logger.warning("_resample 长度异常: len=%d expected=%d", len(data), expected)
        data = data[:expected]
    try:
        samples = struct.unpack(f"<{n_samples}h", data)
    except struct.error as e:
        logger.error("_resample unpack 失败: len=%d n_samples=%d err=%s", len(data), n_samples, e)
        return b""
    ratio = to_rate / from_rate
    n_out = int(len(samples) * ratio)
    out = []
    for i in range(n_out):
        idx = i / ratio
        i0 = int(idx)
        i1 = min(i0 + 1, len(samples) - 1)
        f = idx - i0
        out.append(int(samples[i0] * (1 - f) + samples[i1] * f))
    return struct.pack(f"<{len(out)}h", *out)
