"""港股通南向资金的离线测试：HKEX 日统计文件解析、空文件 / 非交易日、汇总计算。python3 -m unittest discover tests"""

import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as s  # noqa: E402


def link(market, day, buy, sell, top, trading=1):
    head = ["Total Turnover", "Buy Turnover", "Sell Turnover", "Total Trade Count", "Buy Trade Count", "Sell Trade Count", "ETF Turnover"]
    vals = [f"{buy + sell:,.2f}", f"{buy:,.2f}", f"{sell:,.2f}", "1", "1", "1", "0"]
    return {"id": 1, "date": day, "market": market, "tradingDay": trading, "content": [
        {"style": 1, "table": {"classname": "tradingTable", "schema": [head], "tr": [{"td": [[v]]} for v in vals]}},
        {"style": 2, "table": {"classname": "top10Table", "schema": [["Rank", "Stock Code", "Stock Name", "Buy Turnover", "Sell Turnover", "Total Turnover"]],
                               "tr": [{"td": [[str(i + 1), c, n, f"{b:,}", f"{x:,}", f"{b + x:,}"]]} for i, (c, n, b, x) in enumerate(top)]}}]}


def file_text(*markets):
    north = {"id": 0, "date": "2026-11-11", "market": "SSE Northbound", "tradingDay": 1, "content": []}
    return "tabData = " + json.dumps([north, *markets]) + ";"


class Parse(unittest.TestCase):
    def test_both_links_are_summed_in_hkd(self):
        d = s.hkex_parse(file_text(
            link("SSE Southbound", "2026-11-11", 300.0, 100.0, [("00700", "TENCENT", 50_000_000, 20_000_000)]),
            link("SZSE Southbound", "2026-11-11", 50.0, 150.0, [("00700", "TENCENT", 10_000_000, 30_000_000), ("09988", "BABA-W", 5, 1)])))
        self.assertEqual(d["date"], "2026-11-11")
        self.assertAlmostEqual(d["buy"], 350e6)  # 表里的单位是百万港元
        self.assertAlmostEqual(d["net"], 100e6)
        tencent = next(t for t in d["top"] if t["code"] == "00700")
        self.assertEqual((tencent["buy"], tencent["sell"]), (60_000_000, 50_000_000))  # 同一只股票的沪、深两条通道合并

    def test_suspended_link_and_empty_file(self):
        only_sh = s.hkex_parse(file_text(link("SSE Southbound", "2026-10-01", 10.0, 5.0, []), link("SZSE Southbound", "2026-10-01", 0, 0, [], trading=0)))
        self.assertEqual(list(only_sh["links"]), ["sh"])
        self.assertIsNone(s.hkex_parse(file_text(link("SSE Southbound", "2026-10-01", 0, 0, [], trading=0))))
        self.assertIsNone(s.hkex_parse("   "))
        with self.assertRaises(s.ApiError):
            s.hkex_parse("<html>not data</html>")


class Summary(unittest.TestCase):
    def test_streak_sums_and_five_day_ranking(self):
        nets = [-5, 2, -1, 3, 4, 6]  # 最后 3 天都是净买入
        days = [{"date": f"2026-11-0{i + 1}", "net": v * 1e9, "buy": 10e9, "sell": 10e9 - v * 1e9, "links": {"sh": {"buy": 1.0, "sell": 1.0}},
                 "top": [{"code": "00700", "name": "TENCENT", "buy": 2.0 + v, "sell": 2.0}]} for i, v in enumerate(nets)]
        by_date = {date.fromisoformat(x["date"]): x for x in days}
        with mock.patch.object(s, "hkex_day", side_effect=lambda d: by_date.get(d)), \
                mock.patch.object(s, "datetime", wraps=s.datetime) as dt:
            dt.now.return_value = s.datetime(2026, 11, 6, 20, tzinfo=s.HK_TZ)
            r = s.southbound()
        self.assertEqual(r["streak"], 3)
        self.assertAlmostEqual(r["net"], 6e9)
        self.assertAlmostEqual(r["net5"], sum(nets[-5:]) * 1e9)
        self.assertEqual([x["d"] for x in r["series"]][-1], "2026-11-06")
        self.assertEqual(r["top5d"][0]["days"], 5)
        self.assertAlmostEqual(r["top5d"][0]["net"], sum(nets[-5:]))


if __name__ == "__main__":
    unittest.main()
