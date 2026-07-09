"""多轮对话自测（不打电话）：开场白(固定录音,独立音轨) + 两轮客户发言各有 AI 回复。
用法：.venv/bin/python test_multiturn.py
"""
import asyncio
import os
import struct
import sys
import time
import wave

from dotenv import load_dotenv
load_dotenv()
from livekit import api, rtc  # noqa: E402

URL = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
KEY = os.getenv("LIVEKIT_API_KEY", "APIkey")
SECRET = os.getenv("LIVEKIT_API_SECRET", "secret-key-for-local-test-must-be-32-chars-long")
SPEECH_WAV = "/tmp/agent_selftest.wav"


def rms16(buf: bytes) -> float:
    n = len(buf) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", buf[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


async def main() -> int:
    room_name = f"multiturn-{int(time.time() * 1000)}"
    lkapi = api.LiveKitAPI(url=URL.replace("ws://", "http://"), api_key=KEY, api_secret=SECRET)
    try:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name="outbound-caller", room=room_name)
        )
    finally:
        await lkapi.aclose()

    token = (
        api.AccessToken(KEY, SECRET)
        .with_identity("sip_+8600000000001")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    room = rtc.Room()
    segments: list[tuple[float, float]] = []  # 所有音轨上已结束的 AI 语音段
    got_track = asyncio.Event()

    async def record(track: rtc.Track) -> None:
        cur = {"speaking": False, "start": 0.0, "last": 0.0}  # 每条音轨独立状态
        stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
        async for ev in stream:
            data = bytes(ev.frame.data)
            now = time.perf_counter()
            if rms16(data) > 200:
                if not cur["speaking"]:
                    cur["speaking"] = True
                    cur["start"] = now
                cur["last"] = now
            elif cur["speaking"] and now - cur["last"] > 0.8:
                segments.append((cur["start"], cur["last"]))
                cur["speaking"] = False
        if cur["speaking"]:
            segments.append((cur["start"], cur["last"]))

    @room.on("track_subscribed")
    def on_track(track, pub, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            got_track.set()
            asyncio.create_task(record(track))

    await room.connect(URL, token)
    source = rtc.AudioSource(24000, 1)
    mic = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    async def wait_new_segment(baseline: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(segments) > baseline:
                return True
            await asyncio.sleep(0.15)
        return False

    async def wait_quiet(timeout: float = 25.0) -> None:
        """段数 2 秒内不再增长即认为说完。"""
        deadline = time.time() + timeout
        last_n, last_t = len(segments), time.time()
        while time.time() < deadline:
            await asyncio.sleep(0.3)
            if len(segments) != last_n:
                last_n, last_t = len(segments), time.time()
            elif time.time() - last_t > 2.0:
                return

    wav = wave.open(SPEECH_WAV, "rb")
    all_frames = wav.readframes(wav.getnframes())
    wav.close()

    speak_buf: list[bytes] = []
    pump_stop = asyncio.Event()

    async def pump_mic() -> None:
        silence = b"\x00" * 480
        while not pump_stop.is_set():
            chunk = speak_buf.pop(0) if speak_buf else silence
            await source.capture_frame(
                rtc.AudioFrame(data=chunk, sample_rate=24000, num_channels=1, samples_per_channel=240)
            )

    async def speak(seconds: float, offset_s: float) -> None:
        start = int(24000 * offset_s) * 2
        need = int(24000 * seconds) * 2
        data = all_frames[start : start + need]
        for i in range(0, len(data), 480):
            chunk = data[i : i + 480]
            if len(chunk) < 480:
                chunk = chunk + b"\x00" * (480 - len(chunk))
            speak_buf.append(chunk)
        while speak_buf:
            await asyncio.sleep(0.1)

    results = {}
    pump_task = asyncio.create_task(pump_mic())
    try:
        await asyncio.wait_for(got_track.wait(), timeout=15)
        results["opening"] = await wait_new_segment(0, 20)   # 固定录音 ~10s + 收段
        await wait_quiet()
        base = len(segments)
        await speak(1.5, 4.8)
        results["turn1"] = await wait_new_segment(base, 15)
        await wait_quiet()
        base = len(segments)
        await speak(1.5, 8.0)
        results["turn2"] = await wait_new_segment(base, 15)
        await wait_quiet(10)
    except asyncio.TimeoutError:
        results.setdefault("opening", False)

    pump_stop.set()
    pump_task.cancel()
    await room.disconnect()
    lkapi2 = api.LiveKitAPI(url=URL.replace("ws://", "http://"), api_key=KEY, api_secret=SECRET)
    try:
        await lkapi2.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except Exception:
        pass
    finally:
        await lkapi2.aclose()

    ok = results.get("opening") and results.get("turn1") and results.get("turn2")
    print(f"RESULT opening={results.get('opening')} turn1={results.get('turn1')} turn2={results.get('turn2')} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
