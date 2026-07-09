"""外呼防封卡策略（交接文档待办 4）。

背景：2026-07-08 真机测试中，同一 SIM 一小时内十几通短呼被移动风控停机。
上量（8 口鼎信）前，所有真实拨号入口必须过这一层，否则封卡会比延迟更早爆发。

四条规则（全部环境变量可调，见 .env.example「防封卡」段）：
1. 单卡小时上限（滚动 60 分钟窗口，默认 6 通——事故当天 10+ 通/时触发风控）
2. 单卡日上限（本地自然日，默认 50 通）
3. 同号最小间隔 + 同号日上限（默认 30 分钟 / 3 通）
4. 同卡两通之间随机间隔（默认 60-150s 均匀随机，打散机械节奏）

多卡轮换：策略按 port（SIM 口）记账，DIAL_PORTS 配多个口时自动选
「最久未呼且未触顶」的口；单卡（UC100）时退化为纯节流。

设计约束：
- 自包含：仅标准库 + SQLite 状态文件，不 import 任何 app.* —— 因为
  livekit-poc/agent/dial_api.py（终验入口）也要用同一个文件。
- 此文件在 backend/app/services/ 与 livekit-poc/agent/ 各有一份，
  【单一来源是 backend 这份】，改动后请同步拷贝。
- 多进程安全：check+记账在同一个 BEGIN IMMEDIATE 事务里；backend 与
  dial_api 同机部署时把 DIAL_POLICY_DB 指到同一个绝对路径即可共享额度。

用法：
    policy = get_dial_policy()
    d = policy.acquire("+8618100000000")
    if not d.allowed:
        ...  # d.reason / d.code / d.wait_seconds
    try:
        真正拨号(port=d.port)
    except Exception:
        policy.cancel(d.reservation_id)  # 没真的打出去，退回额度
        raise
"""

from __future__ import annotations

import math
import os
import random
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

__all__ = ["DialDecision", "DialPolicy", "get_dial_policy"]

# 拒绝原因代码（调用方按 code 分流，不要匹配中文文案）
CODE_OK = "ok"
CODE_DISABLED = "disabled"
CODE_SAME_NUMBER_INTERVAL = "same_number_interval"
CODE_SAME_NUMBER_DAILY = "same_number_daily"
CODE_PORT_GAP = "port_gap"
CODE_PORT_HOURLY = "port_hourly"
CODE_PORT_DAILY = "port_daily"

_HOUR = 3600.0


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DialDecision:
    allowed: bool
    code: str
    reason: str
    port: str | None = None
    reservation_id: int | None = None
    wait_seconds: int = 0


class DialPolicy:
    def __init__(
        self,
        db_path: str | None = None,
        ports: list[str] | str | None = None,
        hourly_cap: int | None = None,
        daily_cap: int | None = None,
        same_number_min_interval_s: int | None = None,
        same_number_daily_cap: int | None = None,
        gap_min_s: int | None = None,
        gap_max_s: int | None = None,
        enabled: bool | None = None,
        now_fn=time.time,
        rng: random.Random | None = None,
    ) -> None:
        env = os.getenv
        self.db_path = db_path or env("DIAL_POLICY_DB", "./dial_policy.sqlite3")
        raw_ports = ports if ports is not None else env("DIAL_PORTS", "default")
        if isinstance(raw_ports, str):
            raw_ports = raw_ports.split(",")
        self.ports = [p.strip() for p in raw_ports if p.strip()] or ["default"]
        self.hourly_cap = int(hourly_cap if hourly_cap is not None else env("DIAL_PORT_HOURLY_CAP", "6"))
        self.daily_cap = int(daily_cap if daily_cap is not None else env("DIAL_PORT_DAILY_CAP", "50"))
        self.same_number_min_interval_s = int(
            same_number_min_interval_s
            if same_number_min_interval_s is not None
            else env("DIAL_SAME_NUMBER_MIN_INTERVAL_S", "1800")
        )
        self.same_number_daily_cap = int(
            same_number_daily_cap if same_number_daily_cap is not None else env("DIAL_SAME_NUMBER_DAILY_CAP", "3")
        )
        self.gap_min_s = int(gap_min_s if gap_min_s is not None else env("DIAL_GAP_MIN_S", "60"))
        self.gap_max_s = int(gap_max_s if gap_max_s is not None else env("DIAL_GAP_MAX_S", "150"))
        if self.gap_max_s < self.gap_min_s:
            self.gap_max_s = self.gap_min_s
        self.enabled = enabled if enabled is not None else _env_bool("DIAL_POLICY_ENABLED", "true")
        self._now = now_fn
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._init_db()

    # ---------- 对外接口 ----------

    def acquire(self, phone: str) -> DialDecision:
        """检查并预占一次拨号额度。允许时已记账；拨号未发出要 cancel() 退回。"""
        norm = self._normalize(phone)
        if not self.enabled:
            with self._lock, self._conn() as conn:
                rid = self._log(conn, self._now(), norm, self.ports[0])
            return DialDecision(True, CODE_DISABLED, "策略已禁用（DIAL_POLICY_ENABLED=false），仅记账不拦截", self.ports[0], rid)

        with self._lock, self._conn() as conn:
            now = self._now()
            day = self._day(now)

            # 规则 3：同号
            row = conn.execute(
                "SELECT MAX(ts) FROM dial_log WHERE phone=? AND cancelled=0", (norm,)
            ).fetchone()
            last_ts = row[0] or 0.0
            since = now - last_ts
            if last_ts and since < self.same_number_min_interval_s:
                wait = math.ceil(self.same_number_min_interval_s - since)
                return DialDecision(
                    False, CODE_SAME_NUMBER_INTERVAL,
                    f"同号最小间隔未到（{self.same_number_min_interval_s}s，还差 {wait}s）",
                    wait_seconds=wait,
                )
            n_today = conn.execute(
                "SELECT COUNT(*) FROM dial_log WHERE phone=? AND day=? AND cancelled=0", (norm, day)
            ).fetchone()[0]
            if n_today >= self.same_number_daily_cap:
                wait = self._seconds_to_midnight(now)
                return DialDecision(
                    False, CODE_SAME_NUMBER_DAILY,
                    f"同号今日已呼 {n_today} 通，达日上限 {self.same_number_daily_cap}",
                    wait_seconds=wait,
                )

            # 规则 1/2/4：选口
            best_port: str | None = None
            best_last_ts = float("inf")
            min_wait = float("inf")
            min_wait_code = CODE_PORT_GAP
            for port in self.ports:
                hourly_used = conn.execute(
                    "SELECT COUNT(*) FROM dial_log WHERE port=? AND ts>? AND cancelled=0",
                    (port, now - _HOUR),
                ).fetchone()[0]
                daily_used = conn.execute(
                    "SELECT COUNT(*) FROM dial_log WHERE port=? AND day=? AND cancelled=0", (port, day)
                ).fetchone()[0]
                gap_row = conn.execute(
                    "SELECT next_allowed_ts FROM port_state WHERE port=?", (port,)
                ).fetchone()
                gap_wait = max(0.0, (gap_row[0] if gap_row else 0.0) - now)

                waits: list[tuple[float, str]] = []
                if daily_used >= self.daily_cap:
                    waits.append((float(self._seconds_to_midnight(now)), CODE_PORT_DAILY))
                if hourly_used >= self.hourly_cap:
                    oldest = conn.execute(
                        "SELECT MIN(ts) FROM dial_log WHERE port=? AND ts>? AND cancelled=0",
                        (port, now - _HOUR),
                    ).fetchone()[0]
                    waits.append((max(0.0, (oldest or now) + _HOUR - now), CODE_PORT_HOURLY))
                if gap_wait > 0:
                    waits.append((gap_wait, CODE_PORT_GAP))

                if not waits:  # 该口现在可用
                    port_last = conn.execute(
                        "SELECT MAX(ts) FROM dial_log WHERE port=? AND cancelled=0", (port,)
                    ).fetchone()[0] or 0.0
                    if port_last < best_last_ts:
                        best_last_ts = port_last
                        best_port = port
                else:  # 记录该口解禁时间（所有约束都清除才可用 -> 取 max）
                    port_wait, port_code = max(waits, key=lambda w: w[0])
                    if port_wait < min_wait:
                        min_wait = port_wait
                        min_wait_code = port_code
            if best_port is None:
                wait = math.ceil(min_wait if min_wait != float("inf") else self.gap_min_s)
                labels = {
                    CODE_PORT_DAILY: "所有卡口均达日上限",
                    CODE_PORT_HOURLY: "所有卡口均达小时上限或在冷却",
                    CODE_PORT_GAP: "卡口随机间隔冷却中",
                }
                return DialDecision(False, min_wait_code, f"{labels[min_wait_code]}（约 {wait}s 后可呼）", wait_seconds=wait)

            rid = self._log(conn, now, norm, best_port)
            next_allowed = now + self._rng.uniform(self.gap_min_s, self.gap_max_s)
            conn.execute(
                "INSERT INTO port_state(port, next_allowed_ts) VALUES(?,?) "
                "ON CONFLICT(port) DO UPDATE SET next_allowed_ts=excluded.next_allowed_ts",
                (best_port, next_allowed),
            )
            return DialDecision(True, CODE_OK, "放行", best_port, rid)

    def cancel(self, reservation_id: int | None) -> None:
        """拨号实际未发出（dispatch/AMI 抛错）时退回额度。真实呼出后不要调。"""
        if reservation_id is None:
            return
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE dial_log SET cancelled=1 WHERE id=?", (reservation_id,))

    def stats(self) -> dict:
        """观测用：各口今日/滚动一小时用量与冷却剩余。"""
        with self._lock, self._conn() as conn:
            now = self._now()
            day = self._day(now)
            ports = {}
            for port in self.ports:
                hourly = conn.execute(
                    "SELECT COUNT(*) FROM dial_log WHERE port=? AND ts>? AND cancelled=0", (port, now - _HOUR)
                ).fetchone()[0]
                daily = conn.execute(
                    "SELECT COUNT(*) FROM dial_log WHERE port=? AND day=? AND cancelled=0", (port, day)
                ).fetchone()[0]
                gap_row = conn.execute("SELECT next_allowed_ts FROM port_state WHERE port=?", (port,)).fetchone()
                ports[port] = {
                    "hourlyUsed": hourly,
                    "hourlyCap": self.hourly_cap,
                    "dailyUsed": daily,
                    "dailyCap": self.daily_cap,
                    "cooldownSeconds": max(0, math.ceil((gap_row[0] if gap_row else 0.0) - now)),
                }
            return {"enabled": self.enabled, "day": day, "ports": ports}

    # ---------- 内部 ----------

    def _init_db(self) -> None:
        d = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(d, exist_ok=True)
        with self._lock, self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dial_log ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " ts REAL NOT NULL, day TEXT NOT NULL,"
                " phone TEXT NOT NULL, port TEXT NOT NULL,"
                " cancelled INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dial_log_phone ON dial_log(phone, ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dial_log_port ON dial_log(port, ts)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS port_state (port TEXT PRIMARY KEY, next_allowed_ts REAL NOT NULL DEFAULT 0)"
            )

    @contextmanager
    def _conn(self):
        """独占事务：check 与记账在同一个 BEGIN IMMEDIATE 里，跨进程安全。"""
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _log(self, conn: sqlite3.Connection, ts: float, phone: str, port: str) -> int:
        cur = conn.execute(
            "INSERT INTO dial_log(ts, day, phone, port) VALUES(?,?,?,?)",
            (ts, self._day(ts), phone, port),
        )
        return int(cur.lastrowid)

    def _day(self, ts: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(ts))

    def _seconds_to_midnight(self, ts: float) -> int:
        lt = time.localtime(ts)
        passed = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
        return max(1, 86400 - passed)

    @staticmethod
    def _normalize(phone: str) -> str:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        # +8618xxxxxxxxx 与 18xxxxxxxxx 视为同号：取末 11 位
        return digits[-11:] if len(digits) > 11 else digits


_singleton: DialPolicy | None = None
_singleton_lock = threading.Lock()


def get_dial_policy() -> DialPolicy:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = DialPolicy()
        return _singleton
