"""核心计算的离线测试：涨跌幅、RSI、异动判定、输入校验、新闻倾向事后验证。python3 -m unittest discover tests"""

import math
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as s  # noqa: E402


class Calc(unittest.TestCase):
    def test_chg(self):
        self.assertAlmostEqual(s.chg([100, 110], 1), 10.0)
        self.assertIsNone(s.chg([100], 1))
        self.assertIsNone(s.chg([0, 5], 1))  # 起点为 0 不能算百分比

    def test_rsi_bounds(self):
        up = list(range(1, 40))
        self.assertEqual(s.rsi(up), 100.0)
        down = list(range(40, 1, -1))
        self.assertAlmostEqual(s.rsi(down), 0.0)
        flat_wiggle = [10, 11] * 20
        self.assertTrue(40 < s.rsi(flat_wiggle) < 60)
        self.assertIsNone(s.rsi([1, 2, 3]))

    def test_close_on_or_after(self):
        h = {"days": ["2026-01-02", "2026-01-05"], "close": [1.0, 2.0]}
        self.assertEqual(s.close_on_or_after(h, "2026-01-03"), ("2026-01-05", 2.0))
        self.assertEqual(s.close_on_or_after(h, "2026-02-01"), (None, None))
        self.assertEqual(s.close_on_or_after(h, "2020-01-01"), (None, None))  # 早于历史起点

    def test_num_and_finite(self):
        self.assertEqual(s.num("5", 0, 3), 3)
        with self.assertRaises(s.ApiError):
            s.num("NaN", 0, 100)
        with self.assertRaises(s.ApiError):
            s.num("inf", 0, 100)
        self.assertEqual(s.finite({"a": [1.0, float("nan")], "b": math.inf}), {"a": [1.0, None], "b": None})


class Indicators(unittest.TestCase):
    def chart(self, closes):
        return {"sym": "X", "name": "X", "currency": "USD", "exchange": "X", "type": "EQUITY",
                "close": closes, "volume": [100] * len(closes), "ts": [i * 86400 for i in range(len(closes))]}

    def test_52w_includes_the_oldest_previous_session(self):
        for oldest, last, flag in ((200, 150, "new_hi52"), (50, 75, "new_lo52")):
            with self.subTest(flag=flag), mock.patch.object(s, "yahoo_chart", return_value=self.chart([oldest] + [100] * 251 + [last])):
                self.assertFalse(s.quote_summary("X")[flag])

    def test_52w_requires_a_full_year_and_excludes_older_prices(self):
        for n in (200, 252, 253):
            for last, flag in ((150, "new_hi52"), (50, "new_lo52")):
                with self.subTest(n=n, flag=flag), mock.patch.object(s, "yahoo_chart", return_value=self.chart([100] * (n - 1) + [last])):
                    self.assertEqual(s.quote_summary("X")[flag], n == 253)
        with mock.patch.object(s, "yahoo_chart", return_value=self.chart([200] + [100] * 252 + [150])):
            self.assertTrue(s.quote_summary("X")["new_hi52"])

    def test_detail_rsi_aligns_with_prices_and_summary(self):
        for n in (30, 200, 252, 300):
            closes = [100 + i % 7 for i in range(n)]
            with self.subTest(n=n), mock.patch.object(s, "yahoo_chart", return_value=self.chart(closes)):
                d = s.detail("X")
                self.assertEqual({len(v) for v in d["series"].values()}, {min(n, 252)})
                self.assertEqual(d["series"]["rsi"][-1], d["rsi14"])
                if n <= 252:
                    self.assertEqual(d["series"]["rsi"][:14], [None] * 14)


class Correlation(unittest.TestCase):
    def chart(self, closes, start=0):
        return {"ts": [1_700_000_000 + (start + i) * 86400 for i in range(len(closes))], "close": closes}

    def test_pearson(self):
        self.assertAlmostEqual(s.pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(s.pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertIsNone(s.pearson([1, 1, 1, 1], [1, 2, 3, 4]))  # 常数序列没有相关性
        self.assertIsNone(s.pearson([1, 2], [1, 2]))

    def test_matrix_aligns_dates_and_is_symmetric(self):
        up = [100 * math.exp(math.sin(i) * 0.02 + i * 0.001) for i in range(30)]  # 有波动的走势
        down = [1e4 / x for x in up]  # 倒数：对数收益率正好相反
        # 第三个品种少一天（假日），对齐后仍能算
        syms, m, n = s.corr_matrix({"A": self.chart(up), "B": self.chart(down), "C": self.chart(up[1:], start=1)}, 20)
        self.assertEqual(syms, ["A", "B", "C"])
        self.assertEqual(n, 20)
        self.assertAlmostEqual(m[0][1], -1.0)
        self.assertAlmostEqual(m[0][2], 1.0)
        self.assertEqual(m[1][2], m[2][1])
        self.assertEqual(m[0][0], 1.0)
        with self.assertRaises(s.ApiError):
            s.corr_matrix({"A": self.chart([1, 2, 3])}, 20)


class Alerts(unittest.TestCase):
    def quote(self, **kw):
        base = {"chg1d": 0.5, "vol_ratio": 1.0, "rsi14": 50, "rsi_prev": 50, "new_hi52": False, "new_lo52": False}
        return {**base, **kw}

    def flags(self, item, **q):
        with mock.patch.object(s, "quote_summary", return_value=self.quote(**q)):
            return s.check_item({"sym": "X", "move_pct": 3, "vol_mult": 2, **item})["flags"]

    def test_move_and_volume(self):
        self.assertEqual(self.flags({}, chg1d=-3.5), ["move"])
        self.assertEqual(self.flags({}, vol_ratio=2.4), ["volume"])
        self.assertEqual(self.flags({"move_pct": 0}, chg1d=-9), [])  # 阈值 0 = 关闭

    def test_rsi_cross_only_on_the_day(self):
        self.assertIn("rsi_hi", self.flags({}, rsi14=72, rsi_prev=65))
        self.assertNotIn("rsi_hi", self.flags({}, rsi14=75, rsi_prev=71))  # 昨天已在超买区，不重复提醒
        self.assertNotIn("rsi_hi", self.flags({"rsi_alert": False}, rsi14=72, rsi_prev=65))

    def test_52w(self):
        self.assertIn("hi52", self.flags({}, new_hi52=True))
        self.assertNotIn("hi52", self.flags({"hi52_alert": False}, new_hi52=True))

    def test_price_targets_fire_only_on_the_crossing_day(self):
        self.assertEqual(self.flags({"above": 100}, price=101, prev_close=99), ["above"])
        self.assertEqual(self.flags({"above": 100}, price=100, prev_close=99), ["above"])  # 正好到达也算
        self.assertEqual(self.flags({"above": 100}, price=103, prev_close=101), [])  # 昨天已在上方，不重复
        self.assertEqual(self.flags({"below": 50}, price=49, prev_close=51), ["below"])
        self.assertEqual(self.flags({"below": 50}, price=48, prev_close=49), [])
        self.assertEqual(self.flags({"above": 100, "below": 50}, price=70, prev_close=71), [])
        self.assertEqual(self.flags({"above": 0, "below": None}, price=101, prev_close=99), [])  # 0 / 空 = 未设置
        self.assertEqual(self.flags({"above": 100}, price=101), [])  # 没有昨收（新上市）不判断
        with mock.patch.object(s, "quote_summary", return_value=self.quote(price=1, prev_close=1)):
            r = s.check_item({"sym": "X", "above": 100, "below": 0})
        self.assertEqual((r["above"], r["below"]), (100.0, None))

    def run_with_row(self, changes):
        now = 1772409600
        row = {"sym": "X", "label": "", "flags": ["move"], "price": 110, "chg1d": 10,
               "vol_ratio": 1, "rsi14": 60, "currency": "USD", "last_ts": now - 3600, **changes}
        with mock.patch.object(s.time, "time", return_value=now), \
                mock.patch.dict(s._alert), \
                mock.patch.object(s, "refresh_watchlist", return_value=[row]), \
                mock.patch.object(s, "alert_settings", return_value={"lang": "zh", "sound": False}), \
                mock.patch.object(s, "load_json", side_effect=lambda name, default: default), \
                mock.patch.object(s, "save_json") as save, mock.patch.object(s, "notify") as notify:
            found = s.run_alerts()
            return found, notify.call_count, s._alert["last_error"], save.call_args_list

    def test_stale_quotes_do_not_notify_or_consume_marks(self):
        for changes in ({"stale": True}, {"refreshing": True}, {"market_time": 1772409601}):
            with self.subTest(changes=changes):
                found, notifications, error, writes = self.run_with_row(changes)
                self.assertEqual(found, [])
                self.assertEqual(notifications, 0)
                self.assertIn("已跳过提醒", error)
                self.assertEqual(writes, [mock.call("alert_marks.json", {})])

    def test_market_closed_is_skipped_quietly(self):
        # 周末 / 假日：最新成交超过 24 小时，不提醒、不占用记录，也不算失败，只记为“休市跳过”
        now = 1772409600
        row = {"sym": "X", "label": "", "flags": ["move"], "price": 110, "chg1d": 10, "vol_ratio": 1, "rsi14": 60,
               "currency": "USD", "last_ts": now - 90000, "market_time": now - 86401}
        with mock.patch.object(s.time, "time", return_value=now), mock.patch.dict(s._alert), \
                mock.patch.object(s, "refresh_watchlist", return_value=[row]), \
                mock.patch.object(s, "alert_settings", return_value={"lang": "zh", "sound": False}), \
                mock.patch.object(s, "load_json", side_effect=lambda name, default: default), \
                mock.patch.object(s, "save_json") as save, mock.patch.object(s, "notify") as notify:
            found = s.run_alerts()
            self.assertEqual((found, notify.call_count, s._alert["last_error"], s._alert["skipped"]), ([], 0, None, ["X"]))
            self.assertEqual(save.call_args_list, [mock.call("alert_marks.json", {})])

    def test_fresh_quotes_notify_including_old_daily_bar(self):
        for changes in ({}, {"last_ts": 1772409600 - 90000, "market_time": 1772409600 - 60}):
            with self.subTest(changes=changes):
                found, notifications, error, _ = self.run_with_row(changes)
                self.assertEqual(len(found), 1)
                self.assertEqual(notifications, 1)
                self.assertIsNone(error)


class NewsAccuracy(unittest.TestCase):
    def stamp(self, day, hour=12):
        return datetime.fromisoformat(day).replace(hour=hour, tzinfo=timezone.utc).timestamp()

    def assess(self, hist, days, close, today="2026-04-01"):
        now = datetime.fromisoformat(today).replace(tzinfo=timezone.utc)
        with mock.patch.object(s, "load_json", return_value=hist), \
                mock.patch.object(s, "daily_hist", return_value={"days": days, "close": close}), \
                mock.patch.object(s.time, "time", return_value=now.timestamp()), \
                mock.patch.object(s, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            return next(a for a in s.news_accuracy()["assets"] if a["asset"] == "oil")

    def test_hit_rate_and_base(self):
        hist = {f"2026-03-{i:02d}": {"oil": {"label": label, "ts": self.stamp(f"2026-03-{i:02d}")}}
                for i, label in ((1, "bull"), (2, "bear"), (3, "neutral"))}
        days = [f"2026-03-{d:02d}" for d in range(2, 14)]
        r = self.assess(hist, days, [100 + i for i in range(len(days))])
        self.assertEqual((r["signals"], r["n1"], r["hit1"], r["n5"], r["hit5"]), (2, 2, 1, 2, 1))
        self.assertEqual(r["base1"], 1.0)

    def test_timestamp_controls_entry_and_same_day_price_is_excluded(self):
        hist = {"2026-03-01": {"oil": {"label": "bull", "ts": self.stamp("2026-03-02", 23)}}}
        r = self.assess(hist, ["2026-03-02", "2026-03-03", "2026-03-04"], [100, 110, 90])
        self.assertEqual((r["signals"], r["n1"], r["hit1"]), (1, 1, 0))
        self.assertEqual(r["base1"], 0)

    def test_weekend_and_holiday_samples_use_the_earliest_snapshot(self):
        hist = {  # 故意倒序：周五到周日的快照都从周一收盘开始，只能取周五的偏多信号
            "2026-03-08": {"oil": {"label": "bear", "ts": self.stamp("2026-03-08")}},
            "2026-03-07": {"oil": {"label": "bear", "ts": self.stamp("2026-03-07")}},
            "2026-03-06": {"oil": {"label": "bull", "ts": self.stamp("2026-03-06")}},
        }
        r = self.assess(hist, ["2026-03-06", "2026-03-09", "2026-03-10"], [200, 100, 110])
        self.assertEqual((r["signals"], r["n1"], r["hit1"]), (1, 1, 1))

    def test_invalid_timestamps_are_preserved_but_not_scored(self):
        for ts in (None, "bad", float("nan"), float("inf"), -1, self.stamp("2026-04-02")):
            hist = {"2026-03-01": {"oil": {"label": "bull", "ts": ts}}}
            with self.subTest(ts=ts):
                r = self.assess(hist, ["2026-03-02", "2026-03-03"], [100, 110])
                self.assertEqual((r["days"], r["signals"], r["n1"]), (1, 0, 0))
                self.assertIsNone(r["base1"])

    def test_current_daily_bar_and_unmatured_returns_are_not_scored(self):
        hist = {"2026-03-01": {"oil": {"label": "bull", "ts": self.stamp("2026-03-01")}}}
        r = self.assess(hist, ["2026-03-02", "2026-03-03"], [100, 110], today="2026-03-03")
        self.assertEqual((r["signals"], r["n1"], r["n5"]), (1, 0, 0))
        self.assertIsNone(r["base1"])

    def test_daily_snapshot_is_not_overwritten(self):
        first = {"oil": {"label": "bull", "score": 2, "count": 3}}
        later = {"oil": {"label": "bear", "score": -2, "count": 4}}
        hist = {}
        def store(name, value):
            hist.update(value)
        with mock.patch.dict(s._tilt, last=0), \
                mock.patch.object(s, "load_json", return_value=hist), \
                mock.patch.object(s, "save_json", side_effect=store) as save, \
                mock.patch.object(s.time, "time", side_effect=[self.stamp("2026-03-01"), self.stamp("2026-03-01", 13), self.stamp("2026-03-02")]):
            s.record_news_tilt(first)
            s.record_news_tilt(later)
            s.record_news_tilt(later)
        self.assertEqual(hist["2026-03-01"]["oil"]["label"], "bull")
        self.assertEqual(hist["2026-03-02"]["oil"]["label"], "bear")
        self.assertEqual(save.call_count, 2)


if __name__ == "__main__":
    unittest.main()
