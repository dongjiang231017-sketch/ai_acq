"""dial_policy 单元测试——限流逻辑必须可测，不碰真机。

运行（backend 目录下）：
    .venv/bin/python -m unittest tests.test_dial_policy -v
全部用假时钟 + 固定随机数，毫秒级跑完。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from app.services.dial_policy import (
    CODE_DISABLED,
    CODE_OK,
    CODE_PORT_DAILY,
    CODE_PORT_GAP,
    CODE_PORT_HOURLY,
    CODE_SAME_NUMBER_DAILY,
    CODE_SAME_NUMBER_INTERVAL,
    DialPolicy,
)


class FixedRng:
    """uniform 恒返回 fixed，让随机间隔可断言。"""

    def __init__(self, fixed: float) -> None:
        self.fixed = fixed

    def uniform(self, a: float, b: float) -> float:  # noqa: ARG002
        return self.fixed


class DialPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.t = 1_800_000_000.0  # 假时钟
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "policy.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make(self, **kw) -> DialPolicy:
        defaults = dict(
            db_path=self.db,
            ports=["p1"],
            hourly_cap=6,
            daily_cap=50,
            same_number_min_interval_s=1800,
            same_number_daily_cap=3,
            gap_min_s=0,
            gap_max_s=0,
            enabled=True,
            now_fn=lambda: self.t,
            rng=FixedRng(0.0),
        )
        defaults.update(kw)
        return DialPolicy(**defaults)

    # ---- 规则 3：同号 ----

    def test_same_number_min_interval(self) -> None:
        p = self.make()
        self.assertTrue(p.acquire("18100000001").allowed)
        d = p.acquire("18100000001")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_SAME_NUMBER_INTERVAL)
        self.assertEqual(d.wait_seconds, 1800)
        self.t += 1800
        self.assertTrue(p.acquire("18100000001").allowed)

    def test_same_number_daily_cap(self) -> None:
        p = self.make()
        for _ in range(3):
            self.assertTrue(p.acquire("18100000001").allowed)
            self.t += 1800
        d = p.acquire("18100000001")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_SAME_NUMBER_DAILY)
        self.assertGreater(d.wait_seconds, 0)  # 等到次日
        self.t += 86400  # 跨天后重置
        self.assertTrue(p.acquire("18100000001").allowed)

    def test_plus86_prefix_is_same_number(self) -> None:
        p = self.make()
        self.assertTrue(p.acquire("+8618100000001").allowed)
        d = p.acquire("18100000001")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_SAME_NUMBER_INTERVAL)

    # ---- 规则 1：单卡小时上限（滚动窗口）----

    def test_port_hourly_cap(self) -> None:
        p = self.make()
        for i in range(6):
            self.assertTrue(p.acquire(f"1810000000{i}").allowed)
            self.t += 10
        d = p.acquire("18100000099")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_PORT_HOURLY)
        # 最早一通在 now-60s，需再等 3600-60=3540s 让其滑出窗口
        self.assertEqual(d.wait_seconds, 3540)
        self.t += 3540
        self.assertTrue(p.acquire("18100000099").allowed)

    # ---- 规则 2：单卡日上限 ----

    def test_port_daily_cap(self) -> None:
        p = self.make(hourly_cap=1000, daily_cap=5)
        for i in range(5):
            self.assertTrue(p.acquire(f"1810000010{i}").allowed)
            self.t += 10
        d = p.acquire("18100000199")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_PORT_DAILY)
        self.t += 86400
        self.assertTrue(p.acquire("18100000199").allowed)

    # ---- 规则 4：同卡随机间隔 ----

    def test_port_gap_randomized(self) -> None:
        p = self.make(gap_min_s=60, gap_max_s=150, rng=FixedRng(100.0))
        self.assertTrue(p.acquire("18100000001").allowed)
        d = p.acquire("18100000002")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, CODE_PORT_GAP)
        self.assertEqual(d.wait_seconds, 100)
        self.t += 100
        self.assertTrue(p.acquire("18100000002").allowed)

    def test_gap_within_configured_bounds(self) -> None:
        import random

        p = self.make(gap_min_s=60, gap_max_s=150, rng=random.Random(42))
        self.assertTrue(p.acquire("18100000001").allowed)
        d = p.acquire("18100000002")
        self.assertFalse(d.allowed)
        self.assertGreaterEqual(d.wait_seconds, 60)
        self.assertLessEqual(d.wait_seconds, 150)

    # ---- 多卡轮换 ----

    def test_two_ports_rotate_lru(self) -> None:
        p = self.make(ports=["p1", "p2"], gap_min_s=60, gap_max_s=60, rng=FixedRng(60.0))
        d1 = p.acquire("18100000001")
        self.assertTrue(d1.allowed)
        # p1 进入 60s 冷却，第二通应自动落到 p2 而不是被拒
        d2 = p.acquire("18100000002")
        self.assertTrue(d2.allowed)
        self.assertNotEqual(d1.port, d2.port)
        # 两口都冷却中 -> 拒绝
        d3 = p.acquire("18100000003")
        self.assertFalse(d3.allowed)
        self.assertEqual(d3.code, CODE_PORT_GAP)

    def test_rotation_prefers_least_recently_used(self) -> None:
        p = self.make(ports=["p1", "p2"])  # gap=0 不冷却
        d1 = p.acquire("18100000001")
        self.t += 10
        d2 = p.acquire("18100000002")
        self.t += 10
        d3 = p.acquire("18100000003")
        self.assertEqual(d1.port, "p1")
        self.assertEqual(d2.port, "p2")
        self.assertEqual(d3.port, "p1")  # 回到最久未用

    # ---- cancel 退回额度 ----

    def test_cancel_refunds_quota(self) -> None:
        p = self.make()
        d = p.acquire("18100000001")
        self.assertTrue(d.allowed)
        p.cancel(d.reservation_id)
        # 同号立即可再呼（上一次没真的打出去）
        self.assertTrue(p.acquire("18100000001").allowed)

    # ---- 开关 ----

    def test_disabled_always_allows(self) -> None:
        p = self.make(enabled=False)
        for _ in range(20):
            d = p.acquire("18100000001")
            self.assertTrue(d.allowed)
            self.assertEqual(d.code, CODE_DISABLED)

    # ---- 观测 ----

    def test_stats_counts(self) -> None:
        p = self.make(gap_min_s=30, gap_max_s=30, rng=FixedRng(30.0))
        p.acquire("18100000001")
        s = p.stats()
        self.assertTrue(s["enabled"])
        self.assertEqual(s["ports"]["p1"]["hourlyUsed"], 1)
        self.assertEqual(s["ports"]["p1"]["dailyUsed"], 1)
        self.assertEqual(s["ports"]["p1"]["cooldownSeconds"], 30)

    # ---- 事故场景回放：一小时十几通短呼必须被拦 ----

    def test_incident_replay_burst_calls_blocked(self) -> None:
        p = self.make(gap_min_s=0, gap_max_s=0)
        allowed = 0
        for i in range(15):  # 模拟当天：一小时内对外狂打 15 通
            if p.acquire(f"181000002{i:02d}").allowed:
                allowed += 1
            self.t += 240  # 每 4 分钟一通
        self.assertLessEqual(allowed, 6, "小时上限必须拦住突发短呼")


if __name__ == "__main__":
    unittest.main()
