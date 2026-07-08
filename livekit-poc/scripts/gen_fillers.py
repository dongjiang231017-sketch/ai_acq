"""用 DashScope CosyVoice 生成垫词音频（一次性运行）。

生成 agent/assets/filler_*.wav：48kHz 单声道 16bit PCM。
垫词内容刻意选无实义的承接音，任何语境接都不突兀。

用法：DASHSCOPE_API_KEY=sk-xxx python scripts/gen_fillers.py
如果不想跑这个脚本，也可以自己录音转成同格式放到 agent/assets/。
"""

from __future__ import annotations

import os
import sys
import wave

FILLERS = [
    ("filler_01.wav", "嗯"),
    ("filler_02.wav", "哎，好"),
    ("filler_03.wav", "嗯嗯"),
]

ASSET_DIR = os.path.join(os.path.dirname(__file__), "..", "agent", "assets")


def main() -> None:
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("请设置 DASHSCOPE_API_KEY")
        sys.exit(1)
    try:
        import dashscope
        from dashscope.audio.tts_v2 import SpeechSynthesizer
    except ImportError:
        print("请先 pip install dashscope")
        sys.exit(1)

    dashscope.api_key = api_key
    os.makedirs(ASSET_DIR, exist_ok=True)

    voice = os.getenv("FILLER_VOICE", "longxiaochun_v2")
    for filename, text in FILLERS:
        synthesizer = SpeechSynthesizer(
            model="cosyvoice-v2",
            voice=voice,
            format=_pcm_format(),
        )
        pcm: bytes = synthesizer.call(text)
        if not pcm:
            print(f"合成失败：{text}")
            continue
        out = os.path.join(ASSET_DIR, filename)
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(pcm)
        print(f"已生成 {out}（{text}，{len(pcm) / 96000:.2f}s）")


def _pcm_format():
    from dashscope.audio.tts_v2 import AudioFormat

    return AudioFormat.PCM_48000HZ_MONO_16BIT


if __name__ == "__main__":
    main()
