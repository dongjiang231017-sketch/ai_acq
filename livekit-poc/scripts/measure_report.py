"""汇总延迟打点，输出 PoC 验收报告。

用法：python scripts/measure_report.py agent/metrics_logs/

验收线（和主线路对比用同一标准）：
  turn_latency  P50 <= 800ms, P95 <= 1500ms
  垫词后体感（filler 到位即认为体感 ~300-400ms）
"""

from __future__ import annotations

import glob
import json
import os
import sys
from statistics import median


def pctl(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python measure_report.py <metrics_logs目录>")
        sys.exit(1)
    log_dir = sys.argv[1]
    files = sorted(glob.glob(os.path.join(log_dir, "*.jsonl")))
    if not files:
        print(f"{log_dir} 下没有打点文件")
        sys.exit(1)

    turn_latencies: list[float] = []
    calls = 0
    connected = 0
    dial_failed = 0
    hangups = 0
    fillers = 0

    for path in files:
        calls += 1
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = ev.get("event")
                if name == "call_connected":
                    connected += 1
                elif name == "dial_failed":
                    dial_failed += 1
                elif name == "callee_hangup":
                    hangups += 1
                elif name == "filler_played":
                    fillers += 1
                elif name == "turn_latency":
                    turn_latencies.append(float(ev.get("latency_ms", 0)))

    print("=" * 46)
    print("LiveKit PoC 延迟验收报告")
    print("=" * 46)
    print(f"通话数           : {calls}（接通 {connected}，拨号失败 {dial_failed}，客户挂断 {hangups}）")
    print(f"有效转向样本数    : {len(turn_latencies)}")
    print(f"垫词播放次数      : {fillers}")
    if turn_latencies:
        p50 = median(turn_latencies)
        p95 = pctl(turn_latencies, 95)
        print(f"turn_latency P50 : {p50:.0f} ms   {'PASS' if p50 <= 800 else 'FAIL'}（目标 <=800）")
        print(f"turn_latency P95 : {p95:.0f} ms   {'PASS' if p95 <= 1500 else 'FAIL'}（目标 <=1500）")
        print(f"最快 / 最慢      : {min(turn_latencies):.0f} / {max(turn_latencies):.0f} ms")
    else:
        print("没有 turn_latency 样本——检查通话里客户是否真的说了话")
    print("=" * 46)


if __name__ == "__main__":
    main()
