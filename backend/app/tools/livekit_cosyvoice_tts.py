from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import uuid4
from weakref import WeakSet

import dashscope
from dashscope.audio.tts_v2 import ResultCallback, SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat
from livekit.agents import APIConnectionError, APIConnectOptions, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS


SAMPLE_RATE = 24000
NUM_CHANNELS = 1


class CosyVoiceTTS(tts.TTS):
    """LiveKit streaming TTS backed by a DashScope CosyVoice clone."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice_id: str,
        workspace: str = "",
        speech_rate: float = 1.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DashScope API key is required for CosyVoice TTS")
        if not voice_id.strip():
            raise ValueError("clone voice id is required for CosyVoice TTS")
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True, aligned_transcript=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._api_key = api_key.strip()
        self._model = model.strip() or "cosyvoice-v3.5-flash"
        self._voice_id = voice_id.strip()
        self._workspace = workspace.strip()
        self._speech_rate = speech_rate
        self._streams: WeakSet[_CosyVoiceSynthesizeStream] = WeakSet()

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "dashscope-cosyvoice"

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return self._synthesize_with_stream(text, conn_options=conn_options)

    def stream(
        self,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.SynthesizeStream:
        stream = _CosyVoiceSynthesizeStream(tts=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()


class _CosyVoiceCallback(ResultCallback):
    def __init__(self, loop: asyncio.AbstractEventLoop, items: asyncio.Queue[tuple[str, Any]]) -> None:
        self._loop = loop
        self._items = items
        self._finished = threading.Event()

    def _put(self, kind: str, value: Any = None) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._items.put_nowait, (kind, value))

    def on_data(self, data: bytes) -> None:
        if data:
            self._put("audio", bytes(data))

    def on_error(self, message: object) -> None:
        if not self._finished.is_set():
            self._finished.set()
            self._put("error", str(message))

    def on_complete(self) -> None:
        if not self._finished.is_set():
            self._finished.set()
            self._put("done")

    def on_close(self) -> None:
        if not self._finished.is_set():
            self._finished.set()
            self._put("done")


class _CosyVoiceSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts: CosyVoiceTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._cosyvoice_tts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = uuid4().hex
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/pcm",
            frame_size_ms=20,
            stream=True,
        )

        loop = asyncio.get_running_loop()
        items: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        callback = _CosyVoiceCallback(loop, items)
        dashscope.api_key = self._cosyvoice_tts._api_key
        synthesizer = SpeechSynthesizer(
            model=self._cosyvoice_tts.model,
            voice=self._cosyvoice_tts.voice_id,
            format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            speech_rate=self._cosyvoice_tts._speech_rate,
            language_hints=["zh"],
            callback=callback,
            workspace=self._cosyvoice_tts._workspace or None,
        )

        async def _feed_text() -> None:
            has_text = False
            try:
                async for item in self._input_ch:
                    if isinstance(item, self._FlushSentinel):
                        if has_text:
                            await asyncio.to_thread(synthesizer.streaming_flush)
                            await asyncio.to_thread(
                                synthesizer.streaming_complete,
                                int(max(20.0, self._conn_options.timeout) * 1000),
                            )
                        else:
                            callback.on_complete()
                        return
                    if not item:
                        continue
                    if not has_text:
                        self._mark_started()
                    has_text = True
                    await asyncio.to_thread(synthesizer.streaming_call, item)
                if has_text:
                    await asyncio.to_thread(
                        synthesizer.streaming_complete,
                        int(max(20.0, self._conn_options.timeout) * 1000),
                    )
                else:
                    callback.on_complete()
            except Exception as exc:  # noqa: BLE001
                callback.on_error(exc)

        feeder = asyncio.create_task(_feed_text(), name="cosyvoice_tts_feed")
        segment_started = False
        completed = False
        try:
            while True:
                kind, value = await items.get()
                if kind == "audio":
                    if not segment_started:
                        output_emitter.start_segment(segment_id=request_id)
                        segment_started = True
                    output_emitter.push(value)
                    continue
                if kind == "error":
                    raise APIConnectionError(f"DashScope CosyVoice TTS failed: {value}")
                if kind == "done":
                    completed = True
                    break
            await feeder
            if segment_started:
                output_emitter.end_segment()
        finally:
            if not feeder.done():
                feeder.cancel()
                try:
                    await feeder
                except asyncio.CancelledError:
                    pass
            if not completed:
                try:
                    await asyncio.to_thread(synthesizer.streaming_cancel)
                except Exception:  # noqa: BLE001
                    try:
                        await asyncio.to_thread(synthesizer.close)
                    except Exception:  # noqa: BLE001
                        pass
