"""核心计算的离线测试：涨跌幅、RSI、异动判定、输入校验、新闻倾向事后验证。python3 -m unittest discover tests"""

import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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


class QuantLab(unittest.TestCase):
    def series(self, n=400, drift=0.0, wiggle=0.0):
        c = [100.0]
        for i in range(1, n):
            c.append(c[-1] * math.exp(drift + wiggle * math.sin(i / 3)))
        return c, [1_600_000_000 + i * 86400 for i in range(n)]

    def test_buy_and_hold_matches_benchmark_and_fees_apply(self):
        c, ts = self.series(drift=0.001)
        r = s.run_backtest(c, ts, "buyhold", fee_bp=0)
        self.assertAlmostEqual(r["stats"]["total"], r["bh"]["total"])
        self.assertAlmostEqual(r["stats"]["total"], (c[-1] / c[0] - 1) * 100, places=6)
        self.assertEqual((r["trades"], r["exposure"], r["in_position"]), (0, 100.0, True))
        self.assertIsNotNone(r["open_trade"])
        self.assertEqual(r["stats"]["mdd"], 0.0)  # 单边上涨没有回撤
        self.assertEqual(len(r["halves"]), 2)

    def test_trend_following_on_a_v_shape(self):
        # 先跌 220 天再涨 220 天：200 日趋势策略应在下跌段空仓，交易次数很少
        c = [100 * math.exp(-0.004 * i) for i in range(420)]  # 前 200 天是预热期，之后还有 220 天下跌
        c += [c[-1] * math.exp(0.004 * i) for i in range(1, 221)]
        ts = [1_600_000_000 + i * 86400 for i in range(len(c))]
        r = s.run_backtest(c, ts, "trend200", fee_bp=10)
        self.assertLess(r["exposure"], 60)
        self.assertGreater(r["stats"]["mdd"], r["bh"]["mdd"])  # 回撤比买入持有小（数值更接近 0）
        self.assertLessEqual(r["trades"] + (1 if r["open_trade"] else 0), 3)
        with self.assertRaises(s.ApiError):
            s.run_backtest(c[:230], ts[:230], "trend200")  # 预热后不足 60 天
        with self.assertRaises(s.ApiError):
            s.run_backtest(c, ts, "nope")

    def test_rsi_mean_reversion_round_trips(self):
        c = [100.0]
        for i in range(1, 600):
            c.append(c[-1] * math.exp(0.01 * math.sin(i / 15)))  # 约 94 天一个周期的大幅震荡：RSI 会反复进出超买 / 超卖
        ts = [1_600_000_000 + i * 86400 for i in range(600)]
        r = s.run_backtest(c, ts, "rsi_mr", fee_bp=5)
        self.assertGreater(r["trades"], 3)
        self.assertTrue(0 <= r["win_rate"] <= 100)
        self.assertEqual(len(r["recent_trades"]), min(12, r["trades"]))
        self.assertLessEqual(len(r["series"]["ts"]), 310)

    def test_perf_stats_and_drawdown(self):
        self.assertAlmostEqual(s.max_drawdown([1, 2, 1, 1.5, 3]), -50.0)
        eq = [1 + i * 0.001 for i in range(253)]
        st = s.perf_stats(eq, [1_600_000_000 + i * 86400 for i in range(253)])
        self.assertAlmostEqual(st["total"], 25.2)
        self.assertGreater(st["sharpe"], 10)  # 几乎无波动的稳定上涨
        self.assertIsNone(s.perf_stats([1, 1], [0, 1]))

    def test_vol_cone_is_symmetric_and_calibrated(self):
        c, ts = self.series(n=600, wiggle=0.02)
        f = s.vol_cone(c, target=c[-1])
        b = f["bands"][0]
        self.assertAlmostEqual(b["lo1"] * b["hi1"], c[-1] ** 2, places=6)  # 对数对称
        self.assertLess(f["bands"][0]["sigma"], f["bands"][-1]["sigma"])  # 区间随期限变宽
        self.assertAlmostEqual(f["bands"][3]["sigma"] / f["bands"][0]["sigma"], (60 / 5) ** 0.5, places=6)
        for p in f["prob"]:
            self.assertAlmostEqual(p["end"], 50.0)  # 目标价 = 现价：到期在上方的概率 50%
            self.assertEqual(p["touch"], 100.0)
        f2 = s.vol_cone(c, target=c[-1] * 1.5)
        self.assertLess(f2["prob"][0]["end"], f2["prob"][-1]["end"])  # 期限越长越可能到达
        self.assertIn(20, f2["coverage"])
        self.assertTrue(0 <= f2["coverage"][20]["c1"] <= 100)
        self.assertEqual(s.norm_cdf(0), 0.5)
        with self.assertRaises(s.ApiError):
            s.vol_cone(c[:30])


class Signals(unittest.TestCase):
    def walk(self, n, fn):
        c = [100.0]
        for i in range(1, n):
            c.append(c[-1] * math.exp(fn(i, c)))
        return c, [1_400_000_000 + i * 86400 for i in range(n)]

    def test_solve_quantile_and_logit(self):
        self.assertEqual([round(x, 6) for x in s.solve([[2, 1], [1, 3]], [3, 5])], [0.8, 1.4])
        self.assertEqual((s.quantile([1, 2, 3, 4], 0.5), s.quantile([1, 2, 3, 4], 0.25), s.quantile([], 0.5)), (2.5, 1.75, None))
        # 可分数据：第一个特征决定标签 → 该权重为正且远大于噪声特征
        import random
        random.seed(1)
        X, y = [], []
        for _ in range(400):
            a, b = random.gauss(0, 1), random.gauss(0, 1)
            X.append([1.0, a, b])
            y.append(1 if a + random.gauss(0, 0.3) > 0 else 0)
        w = s.logit_fit(X, y)
        self.assertGreater(w[1], 1.0)
        self.assertLess(abs(w[2]), 0.5)
        self.assertGreater(s.predict(w, [1.0, 2.0, 0.0]), 0.9)

    def test_features_state_and_analogs(self):
        c, ts = self.walk(900, lambda i, c: 0.01 * math.sin(i / 30))
        rows = s.feature_rows(c)
        self.assertIsNone(rows[259])
        self.assertTrue(all(k in rows[-1] for k in s.FEATURES))
        st = s.state_of({"ma200": 0.1, "r20": -0.01, "rsi": 0.3, "volr": 0.0})
        self.assertEqual(st, {"trend": "above", "mom": "down", "rsi": "overbought", "vol": "normal"})
        a = s.analog_stats(c, rows, rows[-1])
        self.assertGreaterEqual(a["n"], 40)
        self.assertEqual([h["h"] for h in a["horizons"]], list(s.SIG_H))
        for h in a["horizons"]:
            self.assertTrue(0 <= h["hit"] <= 100 and 0 <= h["base_hit"] <= 100)
            self.assertLessEqual(h["p25"], h["median"])
            self.assertLessEqual(h["median"], h["p75"])

    def test_model_eval_finds_a_real_pattern_and_rejects_noise(self):
        import random
        random.seed(7)
        # 强均值回归：价格偏离 100 越远越往回走 → 20 日后方向可预测
        c, ts = self.walk(1500, lambda i, c: -0.08 * math.log(c[-1] / 100) + random.gauss(0, 0.01))
        m = s.model_eval(c, s.feature_rows(c))
        self.assertGreater(m["accuracy"], m["base_accuracy"] + 5)
        self.assertLess(m["brier"], m["brier_base"])
        self.assertTrue(m["useful"])
        self.assertTrue(0 <= m["p_now"] <= 100)
        self.assertEqual(sum(b["n"] for b in m["calibration"]), m["test_n"])
        self.assertEqual(len(m["weights"]), len(s.FEATURES))
        # 纯随机游走：不应该“有效”
        c2, _ = self.walk(1500, lambda i, c: random.gauss(0, 0.012))
        m2 = s.model_eval(c2, s.feature_rows(c2))
        self.assertFalse(m2["useful"] and m2["accuracy"] > m2["base_accuracy"] + 8)
        with self.assertRaises(s.ApiError):
            s.model_eval(c[:500], s.feature_rows(c[:500]))

    def test_training_labels_do_not_leak_into_the_test_period(self):
        c, _ = self.walk(1200, lambda i, c: 0.01 * math.sin(i / 25))
        rows = s.feature_rows(c)
        with mock.patch.object(s, "logit_fit", wraps=s.logit_fit) as fit:
            m = s.model_eval(c, rows)
        n, h = len(c), m["h"]
        split = n - h - 252
        train_rows = fit.call_args_list[0].args[0]
        # 第一次拟合用训练期：样本数应等于 split - h 之前的带特征天数，即训练标签都在检验期开始前已知
        self.assertEqual(len(train_rows), sum(1 for i in range(260, split - h) if rows[i]))
        self.assertEqual(m["train_n"], len(train_rows))

    def test_lab_chart_slices_a_shared_10y_series(self):
        chart = {"sym": "X", "name": "X", "currency": "USD", "close": list(range(1, 3001)), "ts": list(range(3000)), "volume": [1] * 3000}
        with mock.patch.object(s, "yahoo_chart", return_value=chart) as yc:
            self.assertEqual(len(s.lab_chart("X", "2y")["close"]), 504)
            self.assertEqual(len(s.lab_chart("X", "5y")["close"]), 1260)
            self.assertEqual(len(s.lab_chart("X", "10y")["close"]), 3000)
            self.assertEqual(s.lab_chart("X", "2y")["close"][-1], 3000)  # 截取的是最近的部分
        self.assertTrue(all(call.args[1] == "10y" for call in yc.call_args_list))  # 不管哪个区间都只请求 10 年那一份

    def test_seasonality(self):
        # 每月 1 日涨 10%、其余日子不动 → 每个月的月收益都是正的
        ts, c, day = [], [100.0], datetime(2020, 1, 1, tzinfo=timezone.utc)
        while day.year < 2024:
            ts.append(int(day.timestamp()))
            c.append(c[-1] * (1.1 if day.day == 1 else 1.0))
            day += timedelta(days=1)
        c = c[1:]
        se = s.seasonality(c, ts)
        self.assertEqual(len(se["months"]), 12)
        self.assertTrue(all(m["hit"] == 100.0 for m in se["months"] if m["n"]))
        self.assertEqual(len(se["weekdays"]), 5)


class Portfolio(unittest.TestCase):
    QUOTES = {"AAPL": {"name": "Apple", "currency": "USD", "price": 200.0, "abs1d": 2.0, "chg1d": 1.0, "spark": [1, 2]},
              "0700.HK": {"name": "Tencent", "currency": "HKD", "price": 400.0, "abs1d": -4.0, "chg1d": -1.0, "spark": [1]},
              "HKD=X": {"price": 8.0}}

    def quote(self, sym, *a, **k):
        if sym not in self.QUOTES:
            raise s.ApiError(f"找不到代码: {sym}")
        return self.QUOTES[sym]

    def test_math_and_fx(self):
        import tempfile
        old = s.DATA
        s.DATA = tempfile.mkdtemp()
        try:
            s.save_json("positions.json", [{"sym": "AAPL", "shares": 10, "cost": 150.0}, {"sym": "0700.HK", "shares": 100, "cost": 500.0}, {"sym": "NOPE", "shares": 1, "cost": 1}])
            with mock.patch.object(s, "quote_summary", side_effect=self.quote):
                p = s.portfolio()
            by = {r["sym"]: r for r in p["positions"]}
            a, t = by["AAPL"], by["0700.HK"]
            self.assertEqual((a["value"], a["cost_total"], a["pnl"], a["day_pnl"]), (2000.0, 1500.0, 500.0, 20.0))
            self.assertAlmostEqual(a["pnl_pct"], 33.3333, places=3)
            self.assertEqual((t["value"], t["pnl"], t["day_pnl"], t["currency"]), (40000.0, -10000.0, -400.0, "HKD"))
            self.assertEqual(t["value_usd"], 5000.0)  # 40000 HKD / 8
            self.assertAlmostEqual(a["weight"] + t["weight"], 100.0)
            self.assertEqual(p["usd"]["value"], 7000.0)
            self.assertEqual(p["usd"]["day_pnl"], 20.0 - 50.0)
            self.assertEqual([x["currency"] for x in p["totals"]], ["HKD", "USD"])  # 按市值排序
            self.assertIn("NOPE", p["errors"])
            self.assertEqual(p["unconverted"], [])
            self.assertEqual([r["sym"] for r in p["positions"]][:2], ["0700.HK", "AAPL"])  # 按美元市值降序，失败的在最后
        finally:
            s.DATA = old

    def test_validation(self):
        with self.assertRaises(s.ApiError):
            s.position_from({"sym": "AAPL", "shares": 0, "cost": 1})
        with self.assertRaises(s.ApiError):
            s.position_from({"sym": "../x", "shares": 1, "cost": 1})
        with self.assertRaises(s.ApiError):
            s.position_from({"sym": "AAPL", "shares": "abc"})
        it = s.position_from({"sym": "aapl", "shares": "10", "cost": "150.5", "note": "x" * 100, "added": "bad"})
        self.assertEqual((it["sym"], it["shares"], it["cost"], len(it["note"])), ("AAPL", 10.0, 150.5, 60))
        self.assertGreater(it["added"], 1_700_000_000)


class Digest(unittest.TestCase):
    def test_text(self):
        mk = {"indices": [{"sym": "^GSPC", "price": 5000, "chg1d": 0.84}, {"sym": "^VIX", "price": 15.23, "chg1d": -3}, {"sym": "^HSI", "price": 1, "chg1d": None}],
              "commods": [{"sym": "GC=F", "price": 2000, "chg1d": -0.46}], "fng": {"now": 62}}
        rows = [{"sym": "NVDA", "chg1d": 4.21}, {"sym": "AAPL", "chg1d": -1.1}, {"sym": "BAD", "error": "x"}]
        title, text = s.digest_text(mk, rows, "en")
        self.assertEqual(title, "Quant Stock God · Daily digest")
        self.assertEqual(text, "SPX +0.8% · VIX 15.2 · GOLD -0.5% · F&G 62 Greed · Watch best NVDA +4.2% · Watch worst AAPL -1.1%")
        title, text = s.digest_text({"indices": [], "commods": []}, [{"sym": "X", "chg1d": 1}], "zh")
        self.assertEqual(text, "自选最强 X +1.0%")  # 只有一个品种时不重复显示最弱
        self.assertEqual(s.digest_text({}, [], "xx")[0], "Quant Stock God · Daily digest")  # 未知语言用英文

    def test_tick_runs_once_a_day_after_the_set_time(self):
        import tempfile
        old = s.DATA
        s.DATA = tempfile.mkdtemp()
        try:
            s.save_json("config.json", {"digest_enabled": True, "digest_time": "08:30"})
            calls = []
            with mock.patch.object(s, "run_digest", side_effect=lambda: calls.append(1)):
                early = datetime(2026, 3, 2, 8, 29)
                with mock.patch.object(s, "datetime", mock.Mock(now=lambda: early, fromtimestamp=datetime.fromtimestamp)):
                    s.digest_tick()
                self.assertEqual(calls, [])
                late = datetime(2026, 3, 2, 8, 30)
                with mock.patch.object(s, "datetime", mock.Mock(now=lambda: late, fromtimestamp=datetime.fromtimestamp)):
                    s.digest_tick()
                self.assertEqual(calls, [1])
                s.save_json("digest.json", {"day": "2026-03-02"})  # 真正的 run_digest 会写这个
                with mock.patch.object(s, "datetime", mock.Mock(now=lambda: late, fromtimestamp=datetime.fromtimestamp)):
                    s.digest_tick()
                self.assertEqual(calls, [1])  # 当天已发过
                s.save_json("config.json", {"digest_enabled": False})
                with mock.patch.object(s, "datetime", mock.Mock(now=lambda: late, fromtimestamp=datetime.fromtimestamp)):
                    s.digest_tick()
                self.assertEqual(calls, [1])
        finally:
            s.DATA = old

    def test_relative_strength(self):
        import tempfile
        old = s.DATA
        s.DATA = tempfile.mkdtemp()
        try:
            s.save_json("watchlist.json", [{"sym": "A"}, {"sym": "B"}])
            quotes = {"A": {"chg1m": 5.0}, "B": {"chg1m": None}, "^GSPC": {"chg1m": 2.0}}
            with mock.patch.object(s, "check_item", side_effect=lambda i, swr=True: {"sym": i["sym"], "flags": [], **quotes[i["sym"]]}), \
                 mock.patch.object(s, "quote_summary", side_effect=lambda sym, *a, **k: quotes[sym]):
                rows = s.refresh_watchlist()
            self.assertEqual([r["rs1m"] for r in rows], [3.0, None])
        finally:
            s.DATA = old


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

    def test_ma_cross_fires_only_on_the_crossing_day(self):
        self.assertEqual(self.flags({}, ma20=101, ma50=100, ma20_prev=99, ma50_prev=100), ["golden"])
        self.assertEqual(self.flags({}, ma20=99, ma50=100, ma20_prev=100, ma50_prev=100), ["death"])  # 昨天相等也算穿越
        self.assertEqual(self.flags({}, ma20=103, ma50=100, ma20_prev=101, ma50_prev=100), [])  # 昨天已在上方
        self.assertEqual(self.flags({"ma_alert": False}, ma20=101, ma50=100, ma20_prev=99, ma50_prev=100), [])
        self.assertEqual(self.flags({}, ma20=101, ma50=None, ma20_prev=99, ma50_prev=None), [])  # 历史不足

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
