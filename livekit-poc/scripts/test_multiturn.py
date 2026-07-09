"""多轮对话自测（不打电话）：开场白后模拟客户说话两轮，验证 AI 每轮都接话。

PASS 标准：开场白出声 + 两轮客户发言后各有一段新的 AI 语音。
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
SPEECH_WAV = "/tmp/agent_selftest.wav"  # 用真实语音触发服务端 VAD


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
    segments: list[tuple[float, float]] = []  # 已结束的 AI 语音段
    cur = {"speaking": False, "start": 0.0, "last": 0.0}
    got_track = asyncio.Event()

    async def record(track: rtc.Track) -> None:
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

    async def wait_ai_speech(baseline: int, timeout: float) -> bool:
        """等待出现第 baseline+1 段 AI 语音（进行中也算，但要等它开始）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(segments) > baseline or (cur["speaking"] and cur["start"] > 0):
                return True
            await asyncio.sleep(0.15)
        return False

    async def wait_ai_quiet(timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and cur["speaking"]:
            await asyncio.sleep(0.15)

    wav = wave.open(SPEECH_WAV, "rb")
    all_frames = wav.readframes(wav.getnframes())
    wav.close()

    # 模拟真实通话：麦克风从一开始就持续送帧（无话时送静音），
    # 否则 DashScope 会话冷启动，开场白 response.create 会超时。
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
        while speak_buf:  # 等播完
            await asyncio.sleep(0.1)

    results = {}
    pump_task = asyncio.create_task(pump_mic())
    try:
        await asyncio.wait_for(got_track.wait(), timeout=15)
        # 开场白
        cur["start"] = 0.0
        results["opening"] = await wait_ai_speech(0, 18)
        await wait_ai_quiet()
        # 第 1 轮
        base = len(segments)
        cur["start"] = 0.0
        await speak(1.5, 4.8)  # wav 前4秒静音;用短而连续的有声段,避免内部停顿被 VAD 拆成两次发言(会触发正当打断)
        results["turn1"] = await wait_ai_speech(base, 12)
        await wait_ai_quiet()
        # 第 2 轮
        base = len(segments)
        cur["start"] = 0.0
        await speak(1.5, 8.0)
        results["turn2"] = await wait_ai_speech(base, 12)
        await wait_ai_quiet(8)
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
