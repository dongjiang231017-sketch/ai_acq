"""开场白音频生成 v2:完全对齐成功探针的配置,打印所有事件。"""
import base64, json, os, threading, time, wave
from dotenv import load_dotenv
load_dotenv()
import websocket

URL = os.getenv("QWEN_REALTIME_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime") + "?model=" + os.getenv("QWEN_MODEL", "qwen3-omni-flash-realtime")
KEY = os.getenv("DASHSCOPE_API_KEY", "")
VOICE = os.getenv("QWEN_VOICE", "Cherry")
TARGET = "老板您好！耽误您半分钟，我是做视频号团购的刘顾问，专门帮实体店从微信上拉客人到店。想问下，咱店里这块开通了没？"

audio, transcript, done = bytearray(), [""], threading.Event()

def on_message(ws, msg):
    d = json.loads(msg); t = d.get("type")
    if t not in ("response.audio.delta", "response.audio_transcript.delta"):
        print("<<", t, flush=True)
    if t == "error":
        print(json.dumps(d, ensure_ascii=False)[:300], flush=True)
    elif t == "response.audio.delta":
        audio.extend(base64.b64decode(d.get("delta", "")))
    elif t == "response.audio_transcript.done":
        transcript[0] = d.get("transcript", "")
    elif t == "response.done":
        done.set(); ws.close()

def on_open(ws):
    ws.send(json.dumps({"event_id": "e1", "type": "session.update", "session": {
        "modalities": ["text", "audio"], "voice": VOICE,
        "input_audio_format": "pcm16", "output_audio_format": "pcm16",
        "instructions": "你是一个只会照稿朗读的播音员。收到任何生成请求时，用自然的打电话语气一字不差地朗读这段话，只读这段话，不加任何其他内容：" + TARGET,
        "turn_detection": {"type": "server_vad", "silence_duration_ms": 400},
    }}))
    def go():
        time.sleep(1.0)
        print(">> response.create", flush=True)
        ws.send(json.dumps({"event_id": "e3", "type": "response.create", "response": {}}))
        done.wait(timeout=25)
    threading.Thread(target=go, daemon=True).start()

ws = websocket.WebSocketApp(URL, header={"Authorization": "Bearer " + KEY}, on_open=on_open, on_message=on_message)
threading.Thread(target=ws.run_forever, daemon=True).start()
done.wait(timeout=30)
time.sleep(0.5)
tx = transcript[0].strip()
print("转写:", tx)
if audio and all(m in tx for m in ["老板您好", "视频号团购", "刘顾问", "开通"]):
    with wave.open("opening.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(bytes(audio))
    print(f"SAVED opening.wav {len(audio)/48000:.1f}s")
else:
    print("NOT_SAVED")
