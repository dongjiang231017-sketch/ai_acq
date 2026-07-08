"""延迟打点（飞行记录仪的 PoC 版）。

每通电话一个 JSONL 文件，记录每一轮的分段延迟：
- eou_delay: 客户停止说话 -> 系统判定"说完了"（判停耗时）
- ttft: 判定说完 -> 模型第一个 token/音频
- total_turn_latency: 客户说完 -> AI 出声（约等于 eou_delay + ttft）
以及打断、垫词、挂断等事件。

跑完用 scripts/measure_report.py 汇总 P50/P95。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


class MetricsRecorder:
    def __init__(self, metrics_dir: str, call_id: str, phone: str) -> None:
        os.makedirs(metrics_dir, exist_ok=True)
        self._path = os.path.join(metrics_dir, f"{call_id}.jsonl")
        self._lock = threading.Lock()
        self._call_id = call_id
        self.emit("call_created", phone=phone)

    def emit(self, event: str, **fields: Any) -> None:
        record = {
            "ts": round(time.time(), 3),
            "call_id": self._call_id,
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False)
        # 追加写 + 行缓冲；每通电话事件量不大（几十条），不做异步队列
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ---- livekit-agents metrics 事件适配 ----

    def on_metrics(self, ev: Any) -> None:
        """挂到 session.on("metrics_collected") 上。兼容多种指标类型，取到什么记什么。"""
        m = getattr(ev, "metrics", ev)
        cls = type(m).__name__
        fields: dict[str, Any] = {"metrics_type": cls}
        for attr in (
            "end_of_utterance_delay",   # EOU: 判停耗时
            "transcription_delay",
            "ttft",                     # 模型首token耗时
            "ttfb",                     # TTS/模型首音频耗时
            "duration",
            "audio_duration",
            "input_tokens",
            "output_tokens",
            "speech_id",
        ):
            value = getattr(m, attr, None)
            if value is not None:
                fields[attr] = value
        self.emit("metrics", **fields)
