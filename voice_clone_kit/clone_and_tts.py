#!/usr/bin/env python3
"""
一键：百炼声音克隆 + 话术批量合成试听
================================================
流程：本地起文件服务 → cloudflared 临时隧道（给百炼一个公网URL）
     → VoiceEnrollmentService 注册音色 → SpeechSynthesizer 批量合成 mp3

用法（在 ai_acq 目录下）:
    python3 voice_clone_kit/clone_and_tts.py                 # 完整流程
    python3 voice_clone_kit/clone_and_tts.py --model cosyvoice-v2
    python3 voice_clone_kit/clone_and_tts.py --voice <已有音色ID>   # 跳过克隆只合成
    python3 voice_clone_kit/clone_and_tts.py --no-compare    # 不做 v2 对比音频

依赖：pip install dashscope；brew install cloudflared
API key：自动读 backend/.env 的 DASHSCOPE_API_KEY（也可用环境变量覆盖）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
SAMPLE_FILE = "sample_for_clone.wav"
PREFIX = "jfx197"  # 解放西路197号；仅字母数字，<=10字符
DEFAULT_MODEL = "cosyvoice-v3.5-flash"
FALLBACK_MODEL = "cosyvoice-v2"
PRICE_PER_10K = 2.0  # 元/万字符（cosyvoice 合成参考价）


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def load_api_key() -> str:
    import os
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    for env_path in (KIT_DIR.parent / "backend" / ".env", Path.cwd() / "backend" / ".env", Path.cwd() / ".env"):
        if env_path.is_file():
            m = re.search(r"^DASHSCOPE_API_KEY=(.+)$", env_path.read_text(), re.M)
            if m and m.group(1).strip():
                log(f"API key 读取自 {env_path}")
                return m.group(1).strip()
    die("找不到 DASHSCOPE_API_KEY（backend/.env 或环境变量）")
    return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    if not shutil.which("cloudflared"):
        die("未安装 cloudflared。请先: brew install cloudflared")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url, deadline = None, time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break
    if not url:
        proc.terminate()
        die("60秒内未拿到 trycloudflare 隧道地址，请重试")
    log(f"隧道已建立: {url}")
    return proc, url


def wait_public(url: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-255", "User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status in (200, 206) and r.read(64):
                    log("公网可访问性验证通过")
                    return
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(3)
    die(f"公网URL {timeout}s 内不可访问: {last}")


def enroll(model: str, sample_url: str):
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    svc = VoiceEnrollmentService()
    vid = svc.create_voice(target_model=model, prefix=PREFIX, url=sample_url)
    return vid


def synth(model: str, voice: str, text: str) -> bytes:
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    audio = SpeechSynthesizer(model=model, voice=voice).call(text)
    if not audio or not isinstance(audio, (bytes, bytearray)):
        raise RuntimeError(f"合成返回为空: {type(audio)}")
    return bytes(audio)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--voice", default="", help="已有音色ID，跳过克隆")
    ap.add_argument("--no-compare", action="store_true", help="不注册v2对比音色")
    ap.add_argument("--lines", default="lines.json", help="台词文件名（kit目录内）")
    args = ap.parse_args()

    import dashscope
    dashscope.api_key = load_api_key()

    lines = json.loads((KIT_DIR / args.lines).read_text())["lines"]
    out_dir = KIT_DIR / "output"
    out_dir.mkdir(exist_ok=True)
    if not (KIT_DIR / SAMPLE_FILE).is_file():
        die(f"缺少样本 {KIT_DIR / SAMPLE_FILE}")

    voices: dict[str, str] = {}
    tunnel = server = None
    try:
        # ---------- 1. 克隆 ----------
        if args.voice:
            voices[args.model] = args.voice
            log(f"跳过克隆，直接用音色 {args.voice}")
        else:
            port = free_port()
            server = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(KIT_DIR)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            tunnel, base = start_tunnel(port)
            sample_url = f"{base}/{SAMPLE_FILE}"
            wait_public(sample_url)

            for model in dict.fromkeys([args.model] + ([] if args.no_compare else [FALLBACK_MODEL])):
                try:
                    log(f"注册音色（{model}）…")
                    vid = enroll(model, sample_url)
                    voices[model] = vid
                    log(f"✓ 音色注册成功: {vid}")
                except Exception as e:  # noqa: BLE001
                    log(f"✗ {model} 注册失败: {e}")
            if not voices:
                die("所有模型注册均失败，请检查 API key / 模型开通情况")
            time.sleep(3)

        # ---------- 2. 批量合成 ----------
        primary_model = args.model if args.model in voices else next(iter(voices))
        primary_voice = voices[primary_model]
        manifest, total_chars = [], 0
        for item in lines:
            fid, text = item["id"], item["text"]
            fp = out_dir / f"{fid}.mp3"
            if fp.exists() and fp.stat().st_size > 1000:
                manifest.append({"file": fp.name, "model": primary_model, "chars": len(text), "text": text})
                log(f"↷ {fp.name} 已存在，跳过")
                continue
            for attempt in (1, 2, 3):
                try:
                    fp.write_bytes(synth(primary_model, primary_voice, text))
                    total_chars += len(text)
                    manifest.append({"file": fp.name, "model": primary_model, "chars": len(text), "text": text})
                    log(f"✓ {fp.name} ({len(text)}字)")
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 3:
                        log(f"✗ {fid} 三次失败: {e}")
                    else:
                        time.sleep(2 * attempt)
            time.sleep(0.5)

        # v2 对比：只合成第一条开场白
        cmp_model = FALLBACK_MODEL
        if cmp_model in voices and cmp_model != primary_model:
            try:
                fp = out_dir / f"00_对比_{cmp_model}_开场白A.mp3"
                fp.write_bytes(synth(cmp_model, voices[cmp_model], lines[0]["text"]))
                total_chars += len(lines[0]["text"])
                log(f"✓ {fp.name}（v2对比版）")
            except Exception as e:  # noqa: BLE001
                log(f"✗ v2对比版失败: {e}")

        # ---------- 3. 记录 ----------
        manifest_name = f"manifest_{Path(args.lines).stem}.json"
        (out_dir / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        if not args.voice:
            (out_dir / "voices.json").write_text(json.dumps({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "sample": SAMPLE_FILE,
            "voices": [{"model": m, "voice_id": v} for m, v in voices.items()],
            "note": "voice_id 与模型绑定：合成时 model 必须用注册时的 target_model。接入系统：更新 backend/.env 的 DASHSCOPE_VOICE_CLONE_MODEL / DASHSCOPE_TTS_MODEL。",
        }, ensure_ascii=False, indent=2))

        print("\n" + "=" * 50)
        print(f"完成：{len(manifest)}/{len(lines)} 条台词 → {out_dir}")
        for m, v in voices.items():
            print(f"音色 [{m}]: {v}")
        print(f"合成 {total_chars} 字符，预估费用 ≈ {total_chars / 10000 * PRICE_PER_10K:.2f} 元（克隆本身免费）")
    finally:
        for p in (tunnel, server):
            if p:
                p.terminate()


if __name__ == "__main__":
    main()
