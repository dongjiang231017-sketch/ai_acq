from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4
from weakref import WeakSet

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from livekit.agents import APIConnectionError, APIConnectOptions, stt
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr

from app.services.realtime_text_normalizer import normalize_realtime_sales_text


SAMPLE_RATE = 8000


class DashScopeSTT(stt.STT):
    """LiveKit streaming STT backed by DashScope Paraformer telephony ASR."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "paraformer-realtime-8k-v2",
        workspace: str = "",
    ) -> None:
        if not api_key.strip():
            raise ValueError("DashScope API key is required for streaming STT")
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                diarization=False,
                aligned_transcript=False,
                offline_recognize=False,
            )
        )
        self._api_key = api_key.strip()
        self._model = model.strip() or "paraformer-realtime-8k-v2"
        self._workspace = workspace.strip()
        self._streams: WeakSet[_DashScopeRecognizeStream] = WeakSet()

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "dashscope-paraformer"

    async def _recognize_impl(
        self,
        buffer: stt.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise APIConnectionError("DashScopeSTT only supports streaming recognition")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        stream = _DashScopeRecognizeStream(
            stt=self,
            conn_options=conn_options,
            language="zh" if language is NOT_GIVEN else str(language),
        )
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()


class _RecognitionCallback(RecognitionCallback):
    def __init__(
        self,
        stream: "_DashScopeRecognizeStream",
        loop: asyncio.AbstractEventLoop,
        error_future: asyncio.Future[str],
    ) -> None:
        self._stream = stream
        self._loop = loop
        self._error_future = error_future
        self._last_interim = ""

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        raw_text = str(sentence.get("text") or "").strip()
        if not raw_text:
            return
        is_final = RecognitionResult.is_sentence_end(sentence)
        if not is_final and raw_text == self._last_interim:
            return
        self._last_interim = "" if is_final else raw_text
        text = raw_text
        if is_final:
            normalization = normalize_realtime_sales_text(raw_text)
            text = normalization.normalized_text or raw_text
        event = stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT if is_final else stt.SpeechEventType.INTERIM_TRANSCRIPT,
            request_id=str(sentence.get("sentence_id") or self._stream.request_id),
            alternatives=[
                stt.SpeechData(
                    language="zh",
                    text=text,
                    start_time=float(sentence.get("begin_time") or 0) / 1000,
                    end_time=float(sentence.get("end_time") or 0) / 1000,
                    confidence=float(sentence.get("confidence") or 0),
                    metadata={"rawText": raw_text} if text != raw_text else None,
                )
            ],
        )
        self._loop.call_soon_threadsafe(self._stream.emit_event, event)

    def on_error(self, message: object) -> None:
        code = str(getattr(message, "code", "") or "").strip()
        detail = str(getattr(message, "message", "") or "").strip()
        request_id = str(getattr(message, "request_id", "") or "").strip()
        error = ": ".join(part for part in (code, detail) if part) or type(message).__name__
        if request_id:
            error = f"{error} (request_id={request_id})"

        def _set_error() -> None:
            if not self._error_future.done():
                self._error_future.set_result(error)

        self._loop.call_soon_threadsafe(_set_error)


class _DashScopeRecognizeStream(stt.RecognizeStream):
    def __init__(
        self,
        *,
        stt: DashScopeSTT,
        conn_options: APIConnectOptions,
        language: str,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=SAMPLE_RATE)
        self._dashscope_stt = stt
        self._language = language
        self.request_id = uuid4().hex

    def emit_event(self, event: stt.SpeechEvent) -> None:
        if not self._event_ch.closed:
            self._event_ch.send_nowait(event)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        error_future: asyncio.Future[str] = loop.create_future()
        callback = _RecognitionCallback(self, loop, error_future)
        dashscope.api_key = self._dashscope_stt._api_key
        recognition = Recognition(
            model=self._dashscope_stt.model,
            callback=callback,
            format="pcm",
            sample_rate=SAMPLE_RATE,
            workspace=self._dashscope_stt._workspace or None,
            disfluency_removal_enabled=True,
        )
        started = False

        async def _feed_audio() -> None:
            async for item in self._input_ch:
                if isinstance(item, self._FlushSentinel):
                    continue
                recognition.send_audio_frame(bytes(item.data))

        feed_task: asyncio.Task[None] | None = None
        try:
            await asyncio.to_thread(recognition.start)
            started = True
            feed_task = asyncio.create_task(_feed_audio(), name="dashscope_stt_feed")
            done, _ = await asyncio.wait({feed_task, error_future}, return_when=asyncio.FIRST_COMPLETED)
            if error_future in done:
                feed_task.cancel()
                try:
                    await feed_task
                except asyncio.CancelledError:
                    pass
                raise APIConnectionError(f"DashScope streaming STT failed: {error_future.result()}")
            await feed_task
        finally:
            if feed_task is not None and not feed_task.done():
                feed_task.cancel()
                try:
                    await feed_task
                except asyncio.CancelledError:
                    pass
            if started:
                try:
                    await asyncio.to_thread(recognition.stop)
                except Exception:  # noqa: BLE001
                    pass
