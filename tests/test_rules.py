"""新闻规则回归测试：python3 -m unittest discover tests（不联网、不发通知）"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as s  # noqa: E402

STRONG = ("fed_dovish", "fed_hawkish", "opec_cut", "supply_risk", "usd_strong", "inv_build", "inv_draw",
          "weather_cold", "mine_disruption", "geo_escalation")

# 曾经误判过的标题：不应命中任何强影响规则
FALSE_POSITIVES = [
    "Gold falls as traders pare rate cut bets",
    "Gold slips as Fed signals no rush to cut rates",
    "Turkey central bank rate cut",
    "Bank of Japan rate hike lifts yen",
    "Saudi Aramco cuts November crude prices to Asia",
    "Oil prices rise as Red Sea shipping resumes",
    "Oil gains as stocks climb",
    "Oil falls as stocks drop",
    "EU hiring freeze hits Brussels",
    "Plan would undermine shutdown of copper unit",
    "China retaliates with tariffs on US goods",
    "India cut U.S. and Russian oil imports, pivoting to the UAE as tariffs and sanctions reshaped trade",
    "Brent crude oil prices surge Above $117 a barrel",
    "Federal Reserve Board announces approval of application by The Bank of Nova Scotia",
    "3 U.S. Natural Gas Stocks Worth Watching As LNG Demand Builds",
]

# 应该命中的标题
EXPECTED = {
    "Fed signals rate cuts ahead, gold jumps": "fed_dovish",
    "Gold slides as Fed's Powell hints at rate hike": "fed_hawkish",
    "Tanker struck by missile in Strait of Hormuz": "supply_risk",
    "Houthis attack ship in Red Sea": "supply_risk",
    "OPEC+ agrees to extend output cuts": "opec_cut",
    "US crude inventories rise more than expected": "inv_build",
    "U.S. Crude Oil Stockpiles Fall for Fourth Straight Week": "inv_draw",
    "Dollar rallies after strong jobs data": "usd_strong",
    "Dollar slips, gold rises": "usd_weak",
    "Copper jumps as Chile mine strike halts output": "mine_disruption",
    "Natural gas surges on arctic blast forecast": "weather_cold",
    "Missile strikes hit Kyiv as war escalates": "geo_escalation",
    "Oil Climbs on Signs US May Resume Military Strikes Against Iran": "geo_escalation",
}

TECH_EXPECTED = {
    "EU fines Google $3 billion": "regulation",
    "Nvidia beating estimates, raising outlook": "beat",
    "Intel cuts guidance as PC demand slumps": "miss",
    "US tightens chip export controls on China": "export_ctrl",
}


class NewsRules(unittest.TestCase):
    def test_false_positives(self):
        for t in FALSE_POSITIVES:
            hit = [d for d in s.classify(t)["drivers"] if d in STRONG]
            self.assertEqual(hit, [], t)

    def test_expected(self):
        for t, rule in EXPECTED.items():
            self.assertIn(rule, s.classify(t)["drivers"], t)

    def test_tech(self):
        for t, topic in TECH_EXPECTED.items():
            self.assertIn(topic, s.tech_classify(t)["topics"], t)
        self.assertNotIn("regulation", s.tech_classify("OpenAI fine-tunes new model")["topics"])

    def test_dates(self):
        self.assertEqual(s.parse_rss_date("Fri, 30 Oct 2026 12:00:00 -0000"), s.parse_rss_date("Fri, 30 Oct 2026 12:00:00 GMT"))
        self.assertEqual(s.parse_rss_date("2026-10-30T12:00:00Z"), s.parse_rss_date("Fri, 30 Oct 2026 12:00:00 GMT"))
        self.assertEqual(s.parse_rss_date("2026-10-30 12:00:00"), s.parse_rss_date("Fri, 30 Oct 2026 12:00:00 GMT"))

    def test_cpi_yoy_by_date(self):
        # 2025-10 缺数据：2026-10 那一点没有同比，其余按月份配对
        obs = [(f"{y}-{m:02d}-01", 100 + (y - 2024) * 12 + m) for y in (2024, 2025, 2026) for m in range(1, 13) if (y, m) != (2025, 10)]
        p = s.macro_point({"key": "cpi", "name": "CPI", "unit": "%", "yoy": True}, obs)
        self.assertEqual(p["date"], "2026-12-01")
        self.assertAlmostEqual(p["value"], (136 / 124 - 1) * 100, places=6)


if __name__ == "__main__":
    unittest.main()
