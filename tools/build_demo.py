"""生成 GitHub Pages 在线演示版（静态网页，没有后端）。

用法：
    python3 tools/build_demo.py docs

做的事：
1. 把 static/ 复制到输出目录，在 index.html 里插入 demo.js（拦截 /api/ 请求，用录好的数据快照回答）
2. 用一个全新的临时数据目录直接调用 server.py 的函数录数据：默认自选、默认基金列表、空的提醒记录，
   不读取 data/ 里的任何个人设置、自选、提醒或新闻记录，也不用任何 API Key（EIA 用公共 DEMO_KEY，宏观用 Yahoo 收益率）
3. 聪明钱（SEC）需要联系邮箱，演示版不录，页面会显示“需要填写邮箱”的说明
需要联网，大约 1 分钟。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for k in ("FRED_API_KEY", "EIA_API_KEY", "FINNHUB_API_KEY", "SEC_EMAIL"):  # 演示数据不能用到任何人的 Key / 邮箱
    os.environ.pop(k, None)
sys.path.insert(0, ROOT)
import server as s  # noqa: E402

TICKER = ("^GSPC", "^HSI", "GC=F", "CL=F", "^VIX")  # 和 /api/ticker 一致


def main(out):
    out = os.path.abspath(out)
    tmp = tempfile.mkdtemp(prefix="qsg-demo-")
    s.DATA, s.CACHE = tmp, os.path.join(tmp, "cache")
    os.makedirs(s.CACHE)
    try:
        data = record()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "static"), out, ignore=shutil.ignore_patterns("._*", ".DS_Store"))
    for f in ("demo.js", "demo.css"):
        shutil.copy(os.path.join(ROOT, "demo", f), out)
    html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    html, n = re.subn(r'(<script src="boot\.js[^"]*"></script>)', rf'\1\n<script src="demo.js" data-generated="{data["generated"]}"></script>', html, count=1)
    assert n == 1, "index.html 里找不到 boot.js"
    html = html.replace("<title>量化股神</title>", "<title>量化股神 · Quant Stock God — Demo</title>")
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(out, ".nojekyll"), "w").close()  # 让 GitHub Pages 原样发布，不经过 Jekyll
    json.dump(data, open(os.path.join(out, "demo-data.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    size = os.path.getsize(os.path.join(out, "demo-data.json")) // 1024
    print(f"演示版已生成：{out}（{len(data)} 份接口数据，demo-data.json {size} KB）")


def record():
    now = int(time.time())
    data = {"generated": now}
    print("行情 / 市场总览…")
    data["/api/market"] = s.market()
    data["/api/ticker"] = []
    for sym in TICKER:
        x = s.quote_summary(sym)
        data["/api/ticker"].append({"sym": sym, "name": x["name"], "price": x["price"], "chg1d": x["chg1d"]})
    print("自选（默认列表）…")
    data["/api/watchlist"] = s.watchlist()
    data["/api/watchlist/refresh"] = s.refresh_watchlist()
    print("品种详情…")
    syms = {w["sym"] for w in data["/api/watchlist"]} | set(s.INDICES) | set(s.COMMODS)
    for sym in sorted(syms):
        try:
            data[f"detail|{sym}"] = s.detail(sym)
        except Exception as e:  # noqa: BLE001 — 个别品种失败就不放进演示
            print("  跳过", sym, e)
    print("COT / EIA / 宏观…")
    data["/api/cot"] = s.cot()
    data["/api/eia"] = s.eia()
    data["/api/macro"] = s.macro()
    data["/api/southbound"] = s.southbound()
    print("新闻…")
    data["/api/news"] = s.news()
    data["/api/technews"] = s.tech_news()
    data["/api/news/accuracy"] = s.news_accuracy()
    data["/api/news/alerts"] = s.news_alert_status()
    data["/api/managers"] = s.managers()
    data["/api/status"] = s.source_status()
    data["/api/config"] = {k: False for k in s.KEY_FIELDS}
    data["/api/alerts"] = {**s.alert_settings(), "last_run": None, "last_error": None, "running": False, "skipped": [], "next_run": None, "history": []}
    data["/api/version"] = {"started": now, "server_mtime": now - 60, "static_mtime": now - 60, "port": 8767, "platform": "demo",
                            "autostart": False, "log": "—"}
    return s.finite(data)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
