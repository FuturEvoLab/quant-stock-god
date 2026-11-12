#!/usr/bin/env python3
"""量化股神 — 本地美股 / 港股 / 黄金原油大宗商品监控分析工具（只用 Python 标准库）。

启动:  python3 server.py      然后浏览器打开 http://127.0.0.1:8767（端口可用环境变量 PORT 修改）
数据源: Yahoo Finance chart（行情，非官方）、CNN Fear & Greed（非官方）、SEC EDGAR（Form 4 / 13F）、CFTC COT（Socrata）
仅供个人本地使用，不构成投资建议。
"""

import bisect
import email.utils
import html
import math
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8767"))
ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "cache")
UA = "Mozilla/5.0 (quant-stock-god local tool)"

POOL = ThreadPoolExecutor(max_workers=12)
STARTED = time.time()
BG = ThreadPoolExecutor(max_workers=4)
SEC_POOL = ThreadPoolExecutor(max_workers=6)  # SEC 请求限速慢，单独用一个池，长时间扫描不占用行情 / 提醒的线程  # 后台刷新缓存用，和处理请求的线程池分开，避免互相占满


class ApiError(Exception):
    pass


# ---------------------------------------------------------------- 本地 JSON 存储

_store_lock = threading.Lock()


def load_json(name, default):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(name, value):
    path = os.path.join(DATA, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{threading.get_ident()}.tmp"  # 每个线程用自己的临时文件，并发写同一个文件时不会互相踩
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    if name == "config.json":  # 里面有 API Key 和邮箱：只允许本人读写（exFAT 等不支持权限的磁盘上会被忽略）
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)


def cache_name(kind, key):
    return os.path.join("cache", kind, re.sub(r"[^A-Za-z0-9_.=-]", "_", key) + ".json")


KEY_FIELDS = ("fred_key", "eia_key", "finnhub_key", "sec_email")


def num(v, lo, hi, default=0.0):
    """把请求里的数字转成有限的 float 并限制范围；NaN / inf 会让 JSON 失效，必须挡掉"""
    try:
        x = float(v if v not in (None, "") else default)
    except (TypeError, ValueError):
        raise ApiError(f"数字格式不正确: {v}")
    if not math.isfinite(x):
        raise ApiError(f"数字格式不正确: {v}")
    return max(lo, min(hi, x))


def finite(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [finite(v) for v in o]
    return o


def config():
    cfg = load_json("config.json", {})
    # 环境变量优先，方便临时使用
    for k, env in (("fred_key", "FRED_API_KEY"), ("eia_key", "EIA_API_KEY"), ("finnhub_key", "FINNHUB_API_KEY"), ("sec_email", "SEC_EMAIL")):
        cfg[k] = os.environ.get(env) or cfg.get(k, "")
    return cfg


# ---------------------------------------------------------------- HTTP 工具

_cache = {}
_cache_lock = threading.Lock()


MAX_REMOTE_BYTES = 25_000_000


def parse_xml(text):
    """解析远程 XML（RSS / SEC）。正常的数据不会声明 DTD 实体；有就拒绝，彻底避免“XML 炸弹”之类的实体展开攻击"""
    if re.search(r"<!(ENTITY|DOCTYPE[^>]*\[)", text[:20000], re.I):
        raise ApiError("XML 含实体声明，已拒绝解析")
    return ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))  # 去掉编码声明后按已解码的文本解析


def http_get(url, headers=None, ttl=120, raw=False, timeout=30):
    now = time.time()
    ckey = re.sub(r"(api_key=)[^&]+", r"\1***", url)  # 内存缓存的键里不保留 API Key
    with _cache_lock:
        hit = _cache.get(ckey)
        if hit and now - hit[0] < ttl:
            return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_REMOTE_BYTES + 1)
        if len(body) > MAX_REMOTE_BYTES:  # 数据源被劫持或出错时可能返回超大内容，直接拒绝，避免占满内存
            raise ApiError(f"远程数据过大（超过 {MAX_REMOTE_BYTES // 1_000_000} MB）")
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:160]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(f"网络错误: {getattr(e, 'reason', e)}")
    data = body.decode("utf-8", "replace") if raw else json.loads(body.decode("utf-8"))
    with _cache_lock:
        _cache[ckey] = (now, data)
        if len(_cache) > 600:
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:200]:
                del _cache[k]
    return data


class RateLimiter:
    def __init__(self, per_sec):
        self.interval = 1.0 / per_sec
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self):
        with self.lock:
            delay = self.last + self.interval - time.time()
            if delay > 0:
                time.sleep(delay)
            self.last = time.time()


# ---------------------------------------------------------------- 行情（Yahoo Finance chart 接口，非官方，约 15 分钟延迟）
# 内存缓存 + 磁盘缓存；被限流（429）时进入冷却期，期间只用磁盘上的旧数据

yahoo_limiter = RateLimiter(6)
_yahoo = {"cooldown": 0, "last_error": None, "ok": None}
SWR_MAX_AGE = 1800  # 过期但不超过 30 分钟的缓存先直接返回，同时后台刷新；更旧的就当场等新数据
_flight_locks, _flight_guard, _bg_pending = {}, threading.Lock(), set()


def flight_lock(key):
    """同一个 URL 同时只发一次请求：并发的调用排队，拿到锁后先看缓存是否已被前一个填好"""
    with _flight_guard:
        return _flight_locks.setdefault(key, threading.Lock())


def refresh_later(key, fn, *args):
    with _flight_guard:
        if key in _bg_pending:
            return
        _bg_pending.add(key)

    def run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 — 后台刷新失败就继续用旧数据
            pass
        finally:
            with _flight_guard:
                _bg_pending.discard(key)
    BG.submit(run)

NAMES = {
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^HSI": "恒生指数", "^N225": "日经 225", "^VIX": "VIX", "^TNX": "美债 10Y",
    "DX-Y.NYB": "美元指数", "GC=F": "黄金", "SI=F": "白银", "CL=F": "WTI 原油", "BZ=F": "布伦特原油", "HG=F": "铜", "NG=F": "天然气",
}
INDICES = ["^GSPC", "^IXIC", "^HSI", "^N225", "^VIX", "^TNX", "DX-Y.NYB"]
COMMODS = ["GC=F", "SI=F", "CL=F", "BZ=F", "HG=F", "NG=F"]
SENTI = ["HYG", "IEF", "TLT"]  # 自建情绪指数要用的 ETF（垃圾债 / 中期国债 / 长期国债）


def yahoo_chart(sym, rng="2y", ttl=300, swr=True):
    """swr=True：缓存过期不久时先返回旧数据并在后台刷新（页面秒开）；后台提醒用 swr=False 拿最新数据"""
    sym = sym.strip().upper()
    if not re.match(r"^[A-Z0-9^=.\-]{1,20}$", sym):
        raise ApiError(f"代码格式不正确: {sym}")
    disk_key = cache_name("yahoo", f"{sym}_{rng}")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d&includePrePost=false"
    with _cache_lock:
        hit = _cache.get("parsed:" + url)  # http_get 用 url 本身缓存原始响应，这里另存解析结果
    old = hit[1] if hit else load_json(disk_key, None)
    age = time.time() - old.get("fetched", 0) if old else None
    if old and age < ttl:
        if not hit:
            with _cache_lock:
                _cache["parsed:" + url] = (old["fetched"], old)
        return old
    if old and time.time() < _yahoo["cooldown"]:
        return {**old, "stale": True}
    if old and swr and age < SWR_MAX_AGE:
        refresh_later(url, yahoo_fetch, sym, url, disk_key, old, ttl)
        return {**old, "refreshing": True}
    return yahoo_fetch(sym, url, disk_key, old, ttl)


def yahoo_fetch(sym, url, disk_key, old, ttl):
    with flight_lock(url):
        with _cache_lock:
            hit = _cache.get("parsed:" + url)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        if time.time() < _yahoo["cooldown"]:
            if old:
                return {**old, "stale": True}
            raise ApiError("Yahoo 限流冷却中，请稍后再试")
        return _yahoo_fetch(sym, url, disk_key, old, ttl)


def _yahoo_fetch(sym, url, disk_key, old, ttl):
    data, err = None, None
    for host in ("query1", "query2"):
        yahoo_limiter.wait()
        try:
            data = http_get(url.replace("query1", host), ttl=ttl, timeout=12)
            break
        except ApiError as e:
            err = e
            if "HTTP 404" in str(e):
                raise ApiError(f"找不到代码: {sym}")
    if data is None:
        # 429 限流冷却 90 秒；网络超时 / 断网也冷却 30 秒，避免每个请求都再等一轮超时
        _yahoo["cooldown"] = time.time() + (90 if "HTTP 429" in str(err) else 30)
        _yahoo["ok"], _yahoo["last_error"] = False, str(err)[:120]
        if old:
            return {**old, "stale": True}
        raise ApiError(f"Yahoo 行情获取失败（{sym}）: {err}")
    try:
        r = data["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        raise ApiError(f"找不到代码: {sym}")
    meta = r.get("meta", {})
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    ts, closes, vols = r.get("timestamp") or [], q.get("close") or [], q.get("volume") or []
    rows = [(t, c, (vols[i] if i < len(vols) else None) or 0) for i, (t, c) in enumerate(zip(ts, closes)) if c is not None]
    if not rows:
        raise ApiError(f"没有行情数据: {sym}")
    price = meta.get("regularMarketPrice") or rows[-1][1]
    out = {"sym": sym, "name": meta.get("shortName") or meta.get("longName") or sym, "currency": meta.get("currency"),
           "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"), "type": meta.get("instrumentType"),
           "price": price, "market_time": meta.get("regularMarketTime"),
           "session": (meta.get("currentTradingPeriod") or {}).get("regular"),
           "ts": [x[0] for x in rows], "close": [round(x[1], 6) for x in rows], "volume": [x[2] for x in rows],
           "fetched": time.time()}
    _yahoo["ok"], _yahoo["last_error"] = True, None
    with _cache_lock:
        _cache["parsed:" + url] = (time.time(), out)
    with _store_lock:
        save_json(disk_key, out)
    return out


def chg(closes, n):
    if len(closes) <= n or not closes[-1 - n]:
        return None
    return (closes[-1] / closes[-1 - n] - 1) * 100


def session_fraction(d):
    """常规交易时段已过去的比例；不在盘中（或最后一根日线不是今天这个时段）返回 None。
    期货近 24 小时交易、成交集中在美股时段，按时间线性折算误差太大，所以只处理 10 小时以内的股票类时段"""
    ses, now = d.get("session") or {}, time.time()
    start, end = ses.get("start"), ses.get("end")
    if not start or not end or not (0 < end - start <= 10 * 3600) or not (start <= now < end) or d["ts"][-1] < start - 6 * 3600:
        return None
    return (now - start) / (end - start)


def rsi(closes, n=14):
    """Wilder RSI"""
    if len(closes) <= n:
        return None
    gains = [max(0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def quote_summary(sym, rng="2y", swr=True):
    d = yahoo_chart(sym, rng, swr=swr)
    c, v = d["close"], d["volume"]
    vol_today = v[-1] if v else 0
    prev = [x for x in v[-21:-1] if x]
    avg20 = sum(prev) / len(prev) if prev else None
    # 盘中成交量是累计值，直接比 20 日均量会偏低：按已过去的交易时段比例折算成全天预估量（开盘前 20% 时段不折算，避免早盘放大失真）
    frac = session_fraction(d)
    vol_est = vol_today / frac if frac and frac >= 0.2 and vol_today else vol_today
    y1 = c[-252:]
    hi52, lo52 = max(y1), min(y1)
    prev52 = c[-253:-1] if len(c) >= 253 else None  # 今天之前完整的 252 个交易日；历史不足不判断
    return {"sym": d["sym"], "name": NAMES.get(d["sym"]) or d["name"], "currency": d["currency"], "exchange": d["exchange"],
            "price": c[-1], "chg1d": chg(c, 1),
            "abs1d": c[-1] - c[-2] if len(c) > 1 else None, "abs1w": c[-1] - c[-6] if len(c) > 5 else None, "abs1m": c[-1] - c[-22] if len(c) > 21 else None, "chg1w": chg(c, 5), "chg1m": chg(c, 21), "chg3m": chg(c, 63),
            "spark": c[-44:], "volume": vol_today, "avg20": avg20, "vol_ratio": (vol_est / avg20) if avg20 and vol_est else None,
            "vol_projected": vol_est != vol_today, "rsi14": rsi(c[-120:]), "rsi_prev": rsi(c[-121:-1]), "hi52": hi52, "lo52": lo52,
            "new_hi52": bool(prev52) and c[-1] > max(prev52), "new_lo52": bool(prev52) and c[-1] < min(prev52),
            "pos52": (c[-1] - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None,
            "last_ts": d["ts"][-1], "market_time": d.get("market_time"), "stale": bool(d.get("stale")), "refreshing": bool(d.get("refreshing"))}


def sma(vals, n):
    out, run = [], 0.0
    for i, x in enumerate(vals):
        run += x
        if i >= n:
            run -= vals[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def detail(sym):
    """单个品种的技术面概览：近一年走势 + 均线、RSI、52 周区间、波动率、最大回撤（只做客观描述）"""
    d = yahoo_chart(sym, "2y", ttl=600)
    c, ts = d["close"], d["ts"]
    if len(c) < 30:
        raise ApiError(f"没有行情数据: {sym}")
    ma = {n: sma(c, n) for n in (20, 50, 200)}
    rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1]]
    vol = lambda r: (sum((x - sum(r) / len(r)) ** 2 for x in r) / (len(r) - 1)) ** 0.5 * 252 ** 0.5 * 100 if len(r) > 2 else None
    y1 = c[-252:]
    peak, mdd = y1[0], 0.0
    for x in y1:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    year = datetime.now(timezone.utc).year
    ytd_base = next((c[i - 1] for i, t in enumerate(ts) if i and datetime.fromtimestamp(t, timezone.utc).year == year), None)
    k = max(0, len(c) - 252)
    rsi_series = [rsi(c[max(0, i - 119):i + 1]) for i in range(k, len(c))]
    q = quote_summary(sym, "2y")  # 同一份 2 年数据，不重复请求
    return {**q, "name": NAMES.get(d["sym"]) or d["name"], "type": d["type"],
            "ma20": ma[20][-1], "ma50": ma[50][-1], "ma200": ma[200][-1],
            "vol20": vol(rets[-20:]), "vol1y": vol(rets[-252:]), "mdd1y": mdd * 100,
            "chg6m": chg(c, 126), "chg1y": chg(c, 252), "ytd": (c[-1] / ytd_base - 1) * 100 if ytd_base else None,
            "series": {"ts": ts[k:], "close": c[k:], "volume": d["volume"][k:], "ma20": ma[20][k:], "ma50": ma[50][k:], "ma200": ma[200][k:], "rsi": rsi_series}}


# ---------------------------------------------------------------- 恐惧与贪婪
# 先试 CNN 非官方接口；它会拒绝非浏览器请求（HTTP 418），失败时改用本地合成指数（同类思路，用免费行情计算），并明确标注来源

_cnn = {"retry_at": 0, "error": None}


def cnn_fng():
    old = load_json(cache_name("misc", "cnn_fng"), None)
    if old and time.time() - old["fetched"] < 3600:
        return old
    if time.time() < _cnn["retry_at"]:
        raise ApiError(_cnn["error"] or "CNN 暂不可用")
    try:
        d = http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", ttl=3600)
        hist = [{"ts": int(p["x"] / 1000), "v": round(p["y"])} for p in d["fear_and_greed_historical"]["data"]]
        out = {"source": "cnn", "now": round(d["fear_and_greed"]["score"]), "series": hist[-260:], "fetched": time.time()}
        with _store_lock:
            save_json(cache_name("misc", "cnn_fng"), out)
        return out
    except (ApiError, KeyError, TypeError, ValueError) as e:
        _cnn["retry_at"], _cnn["error"] = time.time() + 6 * 3600, f"CNN: {str(e)[:100]}"
        if old:
            return {**old, "stale": True}
        raise ApiError(_cnn["error"])


def pct_rank(vals, x):
    s = sorted(v for v in vals if v is not None)
    if not s:
        return 50.0
    return bisect.bisect_left(s, x) / len(s) * 100 + (bisect.bisect_right(s, x) - bisect.bisect_left(s, x)) / len(s) * 50


def local_fng():
    """合成情绪指数 0~100：动量（标普 vs 125 日均线）、波动（VIX vs 50 日均线，反向）、
    避险需求（标普 vs 长债 20 日收益差）、垃圾债需求（HYG vs IEF 20 日收益差）。各项按近一年百分位换算后取平均。"""
    spx, vix, tlt, hyg, ief = (yahoo_chart(s, "2y") for s in ("^GSPC", "^VIX", "TLT", "HYG", "IEF"))

    def by_day(d):
        return {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): c for t, c in zip(d["ts"], d["close"])}

    S, V, T, H, I = (by_day(d) for d in (spx, vix, tlt, hyg, ief))
    days = sorted(set(S) & set(V) & set(T) & set(H) & set(I))
    if len(days) < 250 + 125:  # 要 250 天的评分序列，每天的动量项又要往前 125 天
        raise ApiError("历史数据不足，无法计算合成情绪指数")
    s, v, t, h, i = ([X[d] for d in days] for X in (S, V, T, H, I))
    comp = {"momentum": [], "volatility": [], "safe_haven": [], "junk": []}
    for k in range(len(days)):
        comp["momentum"].append(s[k] / (sum(s[k - 124:k + 1]) / 125) - 1 if k >= 124 else None)
        comp["volatility"].append(-(v[k] / (sum(v[k - 49:k + 1]) / 50) - 1) if k >= 49 else None)
        comp["safe_haven"].append((s[k] / s[k - 20] - t[k] / t[k - 20]) if k >= 20 else None)
        comp["junk"].append((h[k] / h[k - 20] - i[k] / i[k - 20]) if k >= 20 else None)
    series, parts_now = [], {}
    start = len(days) - 250
    for k in range(start, len(days)):
        scores = {}
        for name, arr in comp.items():
            window = arr[max(0, k - 251):k + 1]
            scores[name] = pct_rank(window, arr[k])
        val = round(sum(scores.values()) / len(scores))
        series.append({"ts": int(datetime.fromisoformat(days[k]).replace(tzinfo=timezone.utc).timestamp()), "v": val})
        parts_now = scores
    return {"source": "local", "now": series[-1]["v"], "series": series, "parts": {k: round(v) for k, v in parts_now.items()}}


def fear_greed():
    try:
        return cnn_fng()
    except ApiError as e:
        out = local_fng()
        out["cnn_error"] = str(e)
        return out


def market():
    syms = INDICES + COMMODS
    jobs = {s: POOL.submit(quote_summary, s) for s in syms}
    fng_job = POOL.submit(fear_greed)
    out, errors = {"indices": [], "commods": []}, {}
    for s, fut in jobs.items():
        try:
            (out["indices"] if s in INDICES else out["commods"]).append(fut.result(timeout=60))
        except Exception as e:  # noqa: BLE001 — 单个品种失败不影响其他
            errors[s] = str(e)[:160]
    try:
        out["fng"] = fng_job.result(timeout=90)
    except Exception as e:  # noqa: BLE001
        out["fng"] = None
        errors["fng"] = str(e)[:160]
    out["errors"] = errors
    out["stale"] = any(x["stale"] for x in out["indices"] + out["commods"])
    out["refreshing"] = any(x["refreshing"] for x in out["indices"] + out["commods"])
    return out


# ---------------------------------------------------------------- 自选监控 + 后台异动提醒（macOS 通知）

DEFAULT_WATCH = [
    {"sym": "AAPL", "label": "Apple"}, {"sym": "NVDA", "label": "NVIDIA"}, {"sym": "0700.HK", "label": "Tencent"},
    {"sym": "9988.HK", "label": "Alibaba"}, {"sym": "GC=F", "label": "Gold"}, {"sym": "CL=F", "label": "WTI Crude"},
]


def watchlist():
    items = load_json("watchlist.json", None)
    if items is None:
        items = [{**w, "move_pct": 3.0, "vol_mult": 2.0, "added": int(time.time())} for w in DEFAULT_WATCH]
        save_json("watchlist.json", items)
    return items


def check_item(item, swr=True):
    q = quote_summary(item["sym"], swr=swr)
    move, mult = float(item.get("move_pct") or 0), float(item.get("vol_mult") or 0)
    flags = []
    if move > 0 and q["chg1d"] is not None and abs(q["chg1d"]) >= move:
        flags.append("move")
    if mult > 0 and q["vol_ratio"] is not None and q["vol_ratio"] >= mult:
        flags.append("volume")
    # RSI 只在“今天穿越”时提醒（昨天收盘还没进入区间），避免连续多天停在超买 / 超卖区时每天重复提醒
    use_rsi, use_52 = item.get("rsi_alert", True), item.get("hi52_alert", True)
    r, rp = q["rsi14"], q["rsi_prev"]
    if use_rsi and r is not None and rp is not None:
        if r >= 70 > rp:
            flags.append("rsi_hi")
        elif r <= 30 < rp:
            flags.append("rsi_lo")
    if use_52 and q["new_hi52"]:
        flags.append("hi52")
    elif use_52 and q["new_lo52"]:
        flags.append("lo52")
    return {**q, "label": item.get("label") or "", "move_pct": move, "vol_mult": mult, "rsi_alert": use_rsi, "hi52_alert": use_52, "flags": flags}


def refresh_watchlist(swr=True):
    with _store_lock:
        items = watchlist()
    jobs = [(i, POOL.submit(check_item, i, swr)) for i in items]
    rows = []
    for item, fut in jobs:
        try:
            rows.append(fut.result(timeout=60))
        except Exception as e:  # noqa: BLE001
            rows.append({"sym": item["sym"], "label": item.get("label") or "", "error": str(e)[:160],
                         "move_pct": item.get("move_pct"), "vol_mult": item.get("vol_mult"), "flags": []})
    return rows


ALERT_TEXT = {
    "zh": {"title": "量化股神 · 异动提醒", "move": "价格异动", "volume": "放量", "vs": "为 20 日均量",
           "rsi_hi": "RSI 进入超买区", "rsi_lo": "RSI 进入超卖区", "hi52": "创 52 周新高", "lo52": "创 52 周新低", "more": "另有 {n} 条异动，打开量化股神查看",
           "test": "测试通知：后台提醒工作正常"},
    "ja": {"title": "量化株神 · 急変アラート", "move": "価格急変", "volume": "出来高急増", "vs": "（20日平均比）",
           "rsi_hi": "RSI が買われ過ぎ圏へ", "rsi_lo": "RSI が売られ過ぎ圏へ", "hi52": "52 週高値を更新", "lo52": "52 週安値を更新", "more": "他に {n} 件の急変。量化株神で確認してください",
           "test": "テスト通知：バックグラウンド通知は正常です"},
    "en": {"title": "Quant Stock God · Alert", "move": "Price move", "volume": "Volume spike", "vs": "vs 20d avg",
           "rsi_hi": "RSI entered overbought", "rsi_lo": "RSI entered oversold", "hi52": "New 52-week high", "lo52": "New 52-week low", "more": "{n} more alerts — open Quant Stock God",
           "test": "Test notification: background alerts are working"},
}
_alert = {"last_run": None, "last_error": None, "next_run": 0, "running": False, "skipped": []}
_alert_lock = threading.Lock()


def alert_settings():
    cfg = load_json("config.json", {})
    return {"enabled": bool(cfg.get("alert_enabled")), "interval": int(cfg.get("alert_interval") or 15),
            "lang": cfg.get("alert_lang") or "en", "sound": cfg.get("alert_sound", True)}


# Windows 10/11 的系统通知：用 PowerShell 调 Windows.UI.Notifications；标题和正文通过环境变量传入，不拼进脚本，避免转义问题
WIN_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:QS_TITLE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:QS_TEXT)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def notify(title, text, sound=True):
    """系统通知：macOS 用 osascript，Windows 用 PowerShell toast；返回 (是否成功, 错误信息)"""
    try:
        if sys.platform == "darwin":
            q = lambda x: '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'
            script = f"display notification {q(text)} with title {q(title)}" + (' sound name "Glass"' if sound else "")
            r = subprocess.run(["osascript", "-e", script], timeout=10, check=False, capture_output=True)
        elif sys.platform.startswith("win"):
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WIN_TOAST], timeout=15, check=False, capture_output=True,
                               env={**os.environ, "QS_TITLE": str(title), "QS_TEXT": str(text)}, creationflags=0x08000000)
        else:
            return False, f"不支持的系统: {sys.platform}"
        return r.returncode == 0, r.stderr.decode("utf-8", "replace").strip()[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)[:200]


def run_alerts():
    """检查一遍自选列表；同一品种同一交易日的同一类异动只提醒一次"""
    if not _alert_lock.acquire(blocking=False):
        return None  # 后台正在检查，调用方据此提示“检查中”而不是“没有新异动”
    try:
        _alert["running"] = True
        st = alert_settings()
        T = ALERT_TEXT.get(st["lang"], ALERT_TEXT["en"])
        rows = refresh_watchlist(swr=False)  # 提醒要用最新数据，不用后台刷新的旧缓存
        with _store_lock:
            marks = load_json("alert_marks.json", {})
        found, errors, skipped = [], [], []
        for r in rows:
            if r.get("error"):
                errors.append(f"{r['sym']}: {r['error']}")
                continue
            market_time = r.get("market_time") or r["last_ts"]
            age = time.time() - market_time
            # 缓存 / 刷新中的旧数据、时间在未来（时钟或数据异常）：算失败；超过 24 小时没有新成交通常是休市（周末、假日），静默跳过
            if r.get("stale") or r.get("refreshing") or age < 0:
                errors.append(f"{r['sym']}: 行情已过期，已跳过提醒")
                continue
            if age > 86400:
                skipped.append(r["sym"])
                continue
            day = datetime.fromtimestamp(r["last_ts"], timezone.utc).date().isoformat()
            for f in r["flags"]:
                key = f"{r['sym']}:{f}:{day}"
                if key in marks:
                    continue
                marks[key] = int(time.time())
                found.append({"ts": int(time.time()), "sym": r["sym"], "label": r["label"], "type": f, "price": r["price"],
                              "chg1d": r["chg1d"], "vol_ratio": r["vol_ratio"], "rsi14": r["rsi14"], "currency": r["currency"]})
        cutoff = time.time() - 10 * 86400
        marks = {k: v for k, v in marks.items() if v > cutoff}
        with _store_lock:
            save_json("alert_marks.json", marks)
            if found:
                save_json("alerts.json", (found + load_json("alerts.json", []))[:300])
        for r in found[:4]:
            who = f"{r['label']} {r['sym']}" if r["label"] else r["sym"]
            if r["type"] == "move":
                text = f"{who} {T['move']} {r['chg1d']:+.2f}% · {r['price']:,.2f}"
            elif r["type"] == "volume":
                text = f"{who} {T['volume']} ×{r['vol_ratio']:.1f} {T['vs']} · {r['chg1d']:+.2f}%"
            elif r["type"] in ("rsi_hi", "rsi_lo"):
                text = f"{who} {T[r['type']]} · RSI {r['rsi14']:.0f} · {r['price']:,.2f}"
            else:
                text = f"{who} {T[r['type']]} · {r['price']:,.2f} ({r['chg1d']:+.2f}%)"
            notify(T["title"], text, st["sound"])
        if len(found) > 4:
            notify(T["title"], T["more"].format(n=len(found) - 4), False)
        _alert["last_run"] = int(time.time())
        _alert["last_error"] = "; ".join(errors[:3]) or None
        _alert["skipped"] = skipped
        return found
    finally:
        _alert["running"] = False
        _alert_lock.release()


def alert_loop():
    while True:
        time.sleep(20)
        try:
            tilt_loop_tick()
        except Exception:  # noqa: BLE001 — 记录失败不影响提醒
            pass
        try:  # 重大新闻提醒：新闻源缓存 15 分钟，所以每 15 分钟查一次
            if news_alert_settings()["enabled"]:
                now = time.time()
                if not _news_alert["next_run"]:
                    _news_alert["next_run"] = now + 30
                if now >= _news_alert["next_run"]:
                    _news_alert["next_run"] = now + 15 * 60
                    run_news_alerts()
            else:
                _news_alert["next_run"] = 0
        except Exception as e:  # noqa: BLE001
            _news_alert["last_error"] = f"{type(e).__name__}: {e}"
        try:
            st = alert_settings()
            if not st["enabled"]:
                _alert["next_run"] = 0
                continue
            now = time.time()
            if not _alert["next_run"]:
                _alert["next_run"] = now + 30  # 开启后 30 秒做第一次检查
            if now >= _alert["next_run"]:
                _alert["next_run"] = now + st["interval"] * 60
                run_alerts()
        except Exception as e:  # noqa: BLE001 — 后台线程不能因为一次异常就退出
            _alert["last_error"] = f"{type(e).__name__}: {e}"


def alert_status():
    st = alert_settings()
    return {**st, "last_run": _alert["last_run"], "last_error": _alert["last_error"], "running": _alert["running"], "skipped": _alert["skipped"],
            "next_run": int(_alert["next_run"]) or None, "history": load_json("alerts.json", [])[:50]}


# ---------------------------------------------------------------- SEC EDGAR（Form 4 内部人买入 / 13F 机构持仓）
# SEC 要求 User-Agent 里带联系邮箱，且每秒不超过 10 次请求。邮箱在“设置”页填写，只存本机。

sec_limiter = RateLimiter(6)


def sec_ua():
    email = config().get("sec_email", "").strip()
    if not email:
        raise ApiError("SEC EDGAR 需要联系邮箱：请在“设置”页填写（只用于 SEC 要求的 User-Agent，只保存在本机）")
    return f"QuantStockGod/1.0 personal-research {email}"


def sec_get(url, raw=False, ttl=3600):
    headers = {"User-Agent": sec_ua(), "Accept-Encoding": "identity"}
    with _cache_lock:
        hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    for attempt in range(3):
        sec_limiter.wait()
        try:
            return http_get(url, headers=headers, ttl=ttl, raw=raw)
        except ApiError as e:
            if "HTTP 429" in str(e) and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            if "HTTP 403" in str(e):
                raise ApiError("SEC 拒绝访问（HTTP 403）：请确认“设置”里的联系邮箱有效，或稍后再试")
            raise


def cik_map():
    """股票代码 → CIK（SEC company_tickers.json，磁盘缓存 7 天）"""
    name = cache_name("sec", "company_tickers")
    old = load_json(name, None)
    if old and time.time() - old["fetched"] < 7 * 86400:
        return old["map"]
    try:
        d = sec_get("https://www.sec.gov/files/company_tickers.json", ttl=86400)
    except ApiError:
        if old:
            return old["map"]
        raise
    m = {v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]} for v in d.values()}
    with _store_lock:
        save_json(name, {"fetched": time.time(), "map": m})
    return m


def submissions(cik, ttl=3 * 3600):
    return sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", ttl=ttl)


def recent_filings(sub, forms):
    r = sub.get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(r.get("form", [])):
        if f in forms:
            out.append({"form": f, "acc": r["accessionNumber"][i], "date": r["filingDate"][i],
                        "report": r.get("reportDate", [""] * (i + 1))[i], "doc": r["primaryDocument"][i]})
    return out


def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def txt(el, path):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse_form4(cik, f):
    name = cache_name("form4", f["acc"])
    hit = load_json(name, None)
    if hit is not None:
        return hit
    doc = f["doc"].split("/")[-1]  # primaryDocument 带 xsl 渲染目录，原始 XML 在上一级
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/{doc}"
    root = strip_ns(parse_xml(sec_get(url, raw=True, ttl=86400)))
    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        roles = []
        if rel is not None:
            if txt(rel, "isDirector") in ("1", "true"):
                roles.append("董事")
            if txt(rel, "isOfficer") in ("1", "true"):
                roles.append(txt(rel, "officerTitle") or "高管")
            if txt(rel, "isTenPercentOwner") in ("1", "true"):
                roles.append("10% 股东")
        owners.append({"name": txt(o, "reportingOwnerId/rptOwnerName"), "cik": txt(o, "reportingOwnerId/rptOwnerCik"), "roles": roles})
    buys = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if txt(t, "transactionCoding/transactionCode") != "P" or txt(t, "transactionAmounts/transactionAcquiredDisposedCode/value") != "A":
            continue
        try:
            sh = float(txt(t, "transactionAmounts/transactionShares/value") or 0)
            px = float(txt(t, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        if sh > 0 and px > 0:
            buys.append({"date": txt(t, "transactionDate/value")[:10], "shares": sh, "price": px})
    out = {"acc": f["acc"], "filed": f["date"], "owners": owners, "buys": buys}
    with _store_lock:
        save_json(name, out)
    return out


def close_on_or_after(hist, day):
    """day 当天或之后第一个交易日的收盘价"""
    i = bisect.bisect_left(hist["days"], day)
    if i >= len(hist["days"]):
        return None, None
    # day 早于行情历史起点时 bisect 会落到第一根 K 线，那不是当时的价格；相差一周以上就当作没有数据
    if (date.fromisoformat(hist["days"][i]) - date.fromisoformat(day)).days > 7:
        return None, None
    return hist["days"][i], hist["close"][i]


def daily_hist(sym):
    d = yahoo_chart(sym, "10y", ttl=6 * 3600)
    return {"days": [datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in d["ts"]], "close": d["close"]}


def insider_buys(ticker, limit=150):
    ticker = ticker.strip().upper()
    info = cik_map().get(ticker)
    if not info:
        raise ApiError(f"SEC 没有这个美股代码: {ticker}（港股内部人披露在 v2 计划中）")
    sub = submissions(info["cik"])
    filings = recent_filings(sub, {"4"})[: max(10, min(int(limit), 400))]
    parsed, errors = [], 0
    for fut in [SEC_POOL.submit(parse_form4, info["cik"], f) for f in filings]:
        try:
            parsed.append(fut.result(timeout=120))
        except Exception:  # noqa: BLE001 — 个别申报解析失败就跳过
            errors += 1
    hist, spx = daily_hist(ticker), daily_hist("^GSPC")
    today = date.today().isoformat()
    events = []
    for p in parsed:
        if not p["buys"]:
            continue
        sh = sum(b["shares"] for b in p["buys"])
        cost = sum(b["shares"] * b["price"] for b in p["buys"])
        day = min(b["date"] for b in p["buys"])
        owner = p["owners"][0] if p["owners"] else {"name": "?", "roles": []}
        ev = {"acc": p["acc"], "filed": p["filed"], "date": day, "owner": owner["name"], "roles": owner["roles"],
              "shares": sh, "avg_price": cost / sh, "value": cost}
        d0, c0 = close_on_or_after(hist, day)
        _, s0 = close_on_or_after(spx, day)
        for n in (30, 90):
            target = (date.fromisoformat(day) + timedelta(days=n)).isoformat()
            ev[f"r{n}"] = ev[f"x{n}"] = None
            if c0 and target <= today:
                _, c1 = close_on_or_after(hist, target)
                _, s1 = close_on_or_after(spx, target)
                if c1:
                    ev[f"r{n}"] = (c1 / c0 - 1) * 100
                    if s0 and s1:
                        ev[f"x{n}"] = ev[f"r{n}"] - (s1 / s0 - 1) * 100
        events.append(ev)
    events.sort(key=lambda e: e["date"], reverse=True)
    people = {}
    for e in events:
        p = people.setdefault(e["owner"], {"owner": e["owner"], "roles": e["roles"], "buys": 0, "value": 0.0, "r30": [], "r90": [], "x90": [], "last": e["date"]})
        p["buys"] += 1
        p["value"] += e["value"]
        for k in ("r30", "r90", "x90"):
            if e[k] is not None:
                p[k].append(e[k])
    rows = []
    for p in people.values():
        avg = lambda a: sum(a) / len(a) if a else None
        rows.append({"owner": p["owner"], "roles": p["roles"], "buys": p["buys"], "value": p["value"], "last": p["last"],
                     "avg30": avg(p["r30"]), "avg90": avg(p["r90"]), "excess90": avg(p["x90"]), "scored": len(p["r90"]),
                     "hit90": (sum(1 for x in p["r90"] if x > 0) / len(p["r90"])) if p["r90"] else None})
    rows.sort(key=lambda r: (r["scored"] > 0, r["hit90"] or 0, r["value"]), reverse=True)
    scored = [e for e in events if e["r90"] is not None]
    span = (filings[-1]["date"], filings[0]["date"]) if filings else (None, None)
    return {"ticker": ticker, "cik": info["cik"], "company": info["title"], "price": hist["close"][-1] if hist["close"] else None,
            "filings_scanned": len(filings), "parse_errors": errors, "span": span, "events": events[:200], "insiders": rows,
            "hit90": (sum(1 for e in scored if e["r90"] > 0) / len(scored)) if scored else None,
            "avg90": (sum(e["r90"] for e in scored) / len(scored)) if scored else None}


# ---- 13F

DEFAULT_MANAGERS = [
    {"cik": 1067983, "name": "Berkshire Hathaway"}, {"cik": 1649339, "name": "Scion (Michael Burry)"},
    {"cik": 1336528, "name": "Pershing Square"}, {"cik": 1656456, "name": "Appaloosa"},
    {"cik": 1536411, "name": "Duquesne Family Office"}, {"cik": 1061768, "name": "Baupost Group"},
    {"cik": 1040273, "name": "Third Point"}, {"cik": 1167483, "name": "Tiger Global"},
]


def managers():
    m = load_json("managers.json", None)
    if m is None:
        m = DEFAULT_MANAGERS
        with _store_lock:
            save_json("managers.json", m)
    return m


def info_table(cik, f):
    name = cache_name("13f", f["acc"])
    hit = load_json(name, None)
    if hit is not None:
        return hit
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}"
    idx = sec_get(base + "/index.json", ttl=86400)
    xmls = [i["name"] for i in idx.get("directory", {}).get("item", []) if i["name"].lower().endswith(".xml")]
    table = next((x for x in xmls if "primary_doc" not in x.lower()), None)
    if not table:
        raise ApiError(f"13F 申报里没有持仓表: {f['acc']}")
    root = strip_ns(parse_xml(sec_get(f"{base}/{table}", raw=True, ttl=86400)))
    scale = 1000 if f["report"] and f["report"] < "2022-12-31" else 1  # 2023 年前的申报单位是千美元
    pos = {}
    for it in root.iter("infoTable"):
        if txt(it, "putCall"):
            continue  # 期权另算，这里只看股票持仓
        cusip = txt(it, "cusip").upper()
        try:
            val = float(txt(it, "value") or 0) * scale
            sh = float(txt(it, "shrsOrPrnAmt/sshPrnamt") or 0)
        except ValueError:
            continue
        p = pos.setdefault(cusip, {"cusip": cusip, "name": txt(it, "nameOfIssuer"), "cls": txt(it, "titleOfClass"), "value": 0.0, "shares": 0.0})
        p["value"] += val
        p["shares"] += sh
    out = {"acc": f["acc"], "report": f["report"], "filed": f["date"], "positions": list(pos.values())}
    with _store_lock:
        save_json(name, out)
    return out


def manager_13f(m):
    sub = submissions(m["cik"])
    fs = [f for f in recent_filings(sub, {"13F-HR"}) if f["report"]]
    seen, quarters = set(), []
    for f in fs:  # 只看原始 13F-HR；修正申报（13F-HR/A）暂不处理，同一季度有多份时取最新那份
        if f["report"] not in seen:
            seen.add(f["report"])
            quarters.append(f)
        if len(quarters) == 2:
            break
    if not quarters:
        raise ApiError("没有找到 13F-HR 申报")
    cur = info_table(m["cik"], quarters[0])
    prev = info_table(m["cik"], quarters[1]) if len(quarters) > 1 else {"positions": [], "report": None}
    P = {p["cusip"]: p for p in prev["positions"]}
    total = sum(p["value"] for p in cur["positions"]) or 1
    changes = []
    for p in cur["positions"]:
        o = P.pop(p["cusip"], None)
        if not o:
            act = "new"
        elif p["shares"] > o["shares"] * 1.02:
            act = "add"
        elif p["shares"] < o["shares"] * 0.98:
            act = "reduce"
        else:
            act = "hold"
        changes.append({**p, "act": act, "weight": p["value"] / total * 100, "prev_shares": o["shares"] if o else 0,
                        "share_chg": ((p["shares"] / o["shares"] - 1) * 100) if o and o["shares"] else None})
    for o in P.values():
        changes.append({**o, "act": "exit", "value": 0.0, "shares": 0.0, "weight": 0.0, "prev_shares": o["shares"], "prev_value": o["value"], "share_chg": -100.0})
    changes.sort(key=lambda c: (c["value"] or c.get("prev_value", 0)), reverse=True)
    count = {a: sum(1 for c in changes if c["act"] == a) for a in ("new", "add", "reduce", "exit", "hold")}
    return {"cik": m["cik"], "name": m["name"], "entity": sub.get("name"), "report": cur["report"], "prev_report": prev["report"],
            "filed": cur["filed"], "total": total, "positions": len(cur["positions"]), "count": count, "changes": changes}


def all_13f():
    ms = managers()
    jobs = [(m, SEC_POOL.submit(manager_13f, m)) for m in ms]
    funds, errors = [], {}
    for m, fut in jobs:
        try:
            funds.append(fut.result(timeout=180))
        except Exception as e:  # noqa: BLE001
            errors[m["name"]] = str(e)[:160]
    return {"funds": funds, "errors": errors}


# ---------------------------------------------------------------- CFTC 持仓报告（COT，Disaggregated Futures Only，Socrata 公共接口）

COT_MARKETS = [
    {"key": "gold", "name": "黄金", "code": "088691", "sym": "GC=F"},
    {"key": "silver", "name": "白银", "code": "084691", "sym": "SI=F"},
    {"key": "crude", "name": "WTI 原油", "code": "067651", "sym": "CL=F"},
    {"key": "copper", "name": "铜", "code": "085692", "sym": "HG=F"},
    {"key": "natgas", "name": "天然气", "code": "023651", "sym": "NG=F"},
]


def cot_market(m):
    since = (date.today() - timedelta(days=3 * 365 + 14)).isoformat()
    q = urllib.parse.urlencode({
        "$select": "report_date_as_yyyy_mm_dd,m_money_positions_long_all,m_money_positions_short_all,open_interest_all",
        "$where": f"cftc_contract_market_code='{m['code']}' AND report_date_as_yyyy_mm_dd >= '{since}'",
        "$order": "report_date_as_yyyy_mm_dd ASC", "$limit": "400"})
    name = cache_name("cot", m["key"])
    url = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?" + q

    def fetch():
        got = http_get(url, ttl=6 * 3600)
        with _store_lock:
            save_json(name, {"fetched": time.time(), "rows": got})
        return got

    old = load_json(name, None)
    if old and time.time() - old["fetched"] < 6 * 3600:
        rows = old["rows"]
    elif old:  # COT 每周才更新一次：旧数据先用，后台去拿新的
        refresh_later(url, fetch)
        rows = old["rows"]
    else:
        rows = fetch()
    series = []
    for r in rows:
        lo, sh = int(float(r["m_money_positions_long_all"])), int(float(r["m_money_positions_short_all"]))
        series.append({"d": r["report_date_as_yyyy_mm_dd"][:10], "long": lo, "short": sh, "net": lo - sh, "oi": int(float(r["open_interest_all"]))})
    if not series:
        raise ApiError(f"CFTC 没有数据: {m['name']}")
    nets = [s["net"] for s in series]
    cur = series[-1]
    lo, hi = min(nets), max(nets)
    return {**m, "date": cur["d"], "long": cur["long"], "short": cur["short"], "net": cur["net"], "oi": cur["oi"],
            "net_oi": cur["net"] / cur["oi"] * 100 if cur["oi"] else None,
            "chg1w": cur["net"] - series[-2]["net"] if len(series) > 1 else None,
            "chg4w": cur["net"] - series[-5]["net"] if len(series) > 4 else None,
            "pctile": sum(1 for x in nets if x < cur["net"]) / max(1, len(nets) - 1) * 100,
            "cot_index": (cur["net"] - lo) / (hi - lo) * 100 if hi > lo else 50, "min": lo, "max": hi, "weeks": len(series),
            "series": [{"d": s["d"], "net": s["net"]} for s in series]}


def cot():
    jobs = [(m, POOL.submit(cot_market, m)) for m in COT_MARKETS]
    out, errors = [], {}
    for m, fut in jobs:
        try:
            out.append(fut.result(timeout=60))
        except Exception as e:  # noqa: BLE001
            errors[m["key"]] = str(e)[:160]
    return {"markets": out, "errors": errors}


# ---------------------------------------------------------------- EIA 库存周报（原油 / 汽油 / 馏分油 / 库欣 / 天然气）
# 优先用设置里的 EIA Key；没填时用 api.data.gov 公开的 DEMO_KEY（每小时约 10 次），数据每周才更新，缓存 12 小时足够

EIA_SERIES = [
    {"key": "crude", "name": "原油库存（不含 SPR）", "series": "WCESTUS1", "route": "petroleum/stoc/wstk", "unit": "Mbbl", "scale": 1e-3},
    {"key": "gasoline", "name": "汽油库存", "series": "WGTSTUS1", "route": "petroleum/stoc/wstk", "unit": "Mbbl", "scale": 1e-3},
    {"key": "distillate", "name": "馏分油库存", "series": "WDISTUS1", "route": "petroleum/stoc/wstk", "unit": "Mbbl", "scale": 1e-3},
    {"key": "cushing", "name": "库欣原油库存", "series": "W_EPC0_SAX_YCUOK_MBBL", "route": "petroleum/stoc/wstk", "unit": "Mbbl", "scale": 1e-3},
    {"key": "natgas", "name": "天然气库存（48 州）", "series": "NW2_EPG0_SWO_R48_BCF", "route": "natural-gas/stor/wkly", "unit": "Bcf", "scale": 1},
]
EIA_TTL = 12 * 3600
_eia_cooldown = {}  # route → 失败后多久内不再请求（公共 DEMO_KEY 额度很小，别反复撞限流）


def eia_route(route, series):
    key = config().get("eia_key") or "DEMO_KEY"
    since = (date.today() - timedelta(days=6 * 365 + 30)).isoformat()
    q = [("api_key", key), ("frequency", "weekly"), ("data[0]", "value"), ("start", since),
         ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", "5000")] + [("facets[series][]", x) for x in series]
    name = cache_name("eia", route.replace("/", "_"))
    # 磁盘文件名按 route 命名、http_get 的内存缓存键会抹掉 api_key，Key 不会落到缓存里
    url = f"https://api.eia.gov/v2/{route}/data/?" + urllib.parse.urlencode(q)

    def fetch():
        if time.time() < _eia_cooldown.get(route, 0):
            raise ApiError("EIA 暂时不可用（上次请求失败，稍后自动重试）")
        try:
            d = http_get(url, ttl=EIA_TTL)
        except ApiError as e:
            _eia_cooldown[route] = time.time() + (3600 if "HTTP 429" in str(e) else 600)
            msg = str(e).replace(key, "***")
            if "HTTP 429" in msg:
                msg = "EIA 请求过于频繁（公共 DEMO_KEY 每小时约 10 次），请稍后再试，或在设置里填写自己的 EIA Key" if key == "DEMO_KEY" else msg
            raise ApiError(msg)
        rows = (d.get("response") or {}).get("data")
        if rows is None:
            raise ApiError(f"EIA 返回格式异常: {str(d)[:120]}".replace(key, "***"))
        with _store_lock:
            save_json(name, {"fetched": time.time(), "demo": key == "DEMO_KEY", "rows": rows})
        return rows

    old = load_json(name, None)
    if old and time.time() - old["fetched"] < EIA_TTL:
        return old["rows"], old.get("demo")
    if old:
        refresh_later("eia:" + route, fetch)
        return old["rows"], old.get("demo")
    return fetch(), key == "DEMO_KEY"


def eia_stat(m, rows):
    pts = sorted((r["period"], float(r["value"])) for r in rows if r.get("series") == m["series"] and r.get("value") not in (None, ""))
    if len(pts) < 60:
        raise ApiError(f"EIA 没有数据: {m['name']}")
    days = [date.fromisoformat(p) for p, _ in pts]
    vals = [v * m["scale"] for _, v in pts]

    def same_week(i, years=5):
        """前 N 年同一周（日期相差 4 天以内）的值，用来算“5 年同期均值”"""
        out = []
        for y in range(1, years + 1):
            target = days[i] - timedelta(days=round(365.25 * y))
            j = bisect.bisect_left(days, target - timedelta(days=4))
            if j < len(days) and abs((days[j] - target).days) <= 4:
                out.append(vals[j])
        return out

    hist = same_week(len(vals) - 1)
    avg5 = sum(hist) / len(hist) if len(hist) >= 3 else None
    start = max(0, len(vals) - 53)
    band = []
    for i in range(start, len(vals)):
        h = same_week(i)
        band.append({"d": pts[i][0], "v": vals[i], "avg": sum(h) / len(h) if len(h) >= 3 else None,
                     "lo": min(h) if len(h) >= 3 else None, "hi": max(h) if len(h) >= 3 else None})
    yago = same_week(len(vals) - 1, 1)
    return {"key": m["key"], "name": m["name"], "unit": m["unit"], "date": pts[-1][0], "value": vals[-1],
            "chg1w": vals[-1] - vals[-2], "chg_yoy": vals[-1] - yago[0] if yago else None,
            "avg5": avg5, "vs5": (vals[-1] / avg5 - 1) * 100 if avg5 else None,
            "lo5": min(hist) if len(hist) >= 3 else None, "hi5": max(hist) if len(hist) >= 3 else None, "series": band}


def eia():
    routes = {}
    for m in EIA_SERIES:
        routes.setdefault(m["route"], []).append(m["series"])
    jobs = {r: POOL.submit(eia_route, r, ss) for r, ss in routes.items()}
    out, errors, demo = [], {}, False
    for m in EIA_SERIES:
        try:
            rows, d = jobs[m["route"]].result(timeout=60)
            demo = demo or bool(d)
            out.append(eia_stat(m, rows))
        except Exception as e:  # noqa: BLE001
            errors[m["key"]] = str(e)[:200]
    return {"series": out, "errors": errors, "demo": demo}


# ---------------------------------------------------------------- 宏观利率（FRED；没填 Key 时用 Yahoo 的美债收益率指数代替）

FRED_SERIES = [
    {"key": "y3m", "id": "DGS3MO", "name": "美债 3 个月", "unit": "%"},
    {"key": "y2", "id": "DGS2", "name": "美债 2 年", "unit": "%"},
    {"key": "y5", "id": "DGS5", "name": "美债 5 年", "unit": "%"},
    {"key": "y10", "id": "DGS10", "name": "美债 10 年", "unit": "%"},
    {"key": "y30", "id": "DGS30", "name": "美债 30 年", "unit": "%"},
    {"key": "ffr", "id": "DFF", "name": "联邦基金利率", "unit": "%"},
    {"key": "be10", "id": "T10YIE", "name": "10 年通胀预期", "unit": "%"},
    {"key": "hy", "id": "BAMLH0A0HYM2", "name": "高收益债利差", "unit": "%"},
    {"key": "cpi", "id": "CPIAUCSL", "name": "CPI 同比", "unit": "%", "yoy": True},
    {"key": "unrate", "id": "UNRATE", "name": "失业率", "unit": "%"},
]
YAHOO_CURVE = [("y3m", "^IRX", "美债 3 个月"), ("y5", "^FVX", "美债 5 年"), ("y10", "^TNX", "美债 10 年"), ("y30", "^TYX", "美债 30 年")]


def fred_series(m, key):
    name = cache_name("fred", m["id"])
    since = (date.today() - timedelta(days=3 * 365)).isoformat()
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(
        {"series_id": m["id"], "api_key": key, "file_type": "json", "observation_start": since})

    def fetch():
        try:
            d = http_get(url, ttl=6 * 3600)
        except ApiError as e:
            raise ApiError(str(e).replace(key, "***"))
        obs = [(o["date"], float(o["value"])) for o in d.get("observations", []) if o.get("value") not in (None, "", ".")]
        with _store_lock:
            save_json(name, {"fetched": time.time(), "obs": obs})
        return obs

    old = load_json(name, None)
    if old and time.time() - old["fetched"] < 6 * 3600:
        return old["obs"]
    if old:
        refresh_later("fred:" + m["id"], fetch)
        return old["obs"]
    return fetch()


def macro_point(m, obs):
    if m.get("yoy"):  # 月度指数 → 同比
        by_month = {d[:7]: v for d, v in obs}  # 按“同一月份”配对；缺数据的月份（如停摆期间）直接跳过，不按位置错位
        obs = [(d, (v / by_month[f"{int(d[:4]) - 1}{d[4:7]}"] - 1) * 100) for d, v in obs if f"{int(d[:4]) - 1}{d[4:7]}" in by_month]
    if len(obs) < 2:
        raise ApiError(f"数据不足: {m['name']}")
    days = [d for d, _ in obs]

    def ago(n_days):
        target = (date.fromisoformat(days[-1]) - timedelta(days=n_days)).isoformat()
        i = bisect.bisect_right(days, target) - 1
        return obs[i][1] if i >= 0 else None

    v = obs[-1][1]
    m1, y1 = ago(30), ago(365)
    step = max(1, len(obs) // 120)
    return {"key": m["key"], "name": m["name"], "unit": m["unit"], "date": days[-1], "value": v,
            "chg1m": v - m1 if m1 is not None else None, "chg1y": v - y1 if y1 is not None else None,
            "prev1m": m1, "spark": [round(x, 4) for _, x in obs[-260::step]] if not m.get("yoy") else [round(x, 3) for _, x in obs[-36:]]}


def macro():
    key = config().get("fred_key")
    out, errors = [], {}
    if key:
        jobs = [(m, POOL.submit(fred_series, m, key)) for m in FRED_SERIES]
        for m, fut in jobs:
            try:
                out.append(macro_point(m, fut.result(timeout=60)))
            except Exception as e:  # noqa: BLE001
                errors[m["key"]] = str(e)[:200]
        source = "fred"
    else:
        jobs = [(k, n, POOL.submit(yahoo_chart, sym)) for k, sym, n in YAHOO_CURVE]
        for k, n, fut in jobs:
            try:
                d = fut.result(timeout=60)
                obs = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), c) for t, c in zip(d["ts"], d["close"])]
                out.append(macro_point({"key": k, "name": n, "unit": "%"}, obs))
            except Exception as e:  # noqa: BLE001
                errors[k] = str(e)[:200]
        source = "yahoo"
    by = {x["key"]: x for x in out}
    curve = [{"key": k, "label": lab, "now": by[k]["value"], "prev": by[k]["prev1m"]}
             for k, lab in (("y3m", "3M"), ("y2", "2Y"), ("y5", "5Y"), ("y10", "10Y"), ("y30", "30Y")) if k in by]
    spreads = {}
    if "y10" in by and "y3m" in by:
        spreads["10y3m"] = by["y10"]["value"] - by["y3m"]["value"]
    if "y10" in by and "y2" in by:
        spreads["10y2y"] = by["y10"]["value"] - by["y2"]["value"]
    return {"source": source, "items": out, "curve": curve, "spreads": spreads, "errors": errors}


# ---------------------------------------------------------------- 港股通南向资金（HKEX 每日成交统计，免费公开）
# 每个交易日一个文件：沪 / 深港通南向的买入、卖出成交额（百万港元）和成交额前 10 的股票。非交易日返回 404。
# 过去的日子不会再变，解析结果永久缓存；当天和前一天的文件可能还没发布，只缓存 1 小时

HK_TZ = timezone(timedelta(hours=8))
SOUTH_DAYS = 45  # 往回看的自然日，约 30 个交易日
hkex_limiter = RateLimiter(4)


def hkex_num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def hkex_parse(text):
    """解析 data_tab_daily_YYYYMMDDe.js（`tabData = [...]`），只取两条南向通道"""
    if not text.strip():
        return None  # 偶尔有交易日返回空文件（数据还没补上），当作暂时没有数据
    i = text.find("[")
    if i < 0:
        raise ApiError("HKEX 返回格式异常")
    out = {"date": None, "links": {}, "top": {}}
    for m in json.loads(text[i:].strip().rstrip(";")):
        link = {"SSE Southbound": "sh", "SZSE Southbound": "sz"}.get(m.get("market"))
        if not link or m.get("tradingDay") != 1:  # 内地假期时港股通暂停，那条通道 tradingDay 为 0
            continue
        out["date"] = m.get("date")
        for c in m.get("content", []):
            t = c.get("table") or {}
            head = (t.get("schema") or [[]])[0]
            rows = [r["td"][0] for r in t.get("tr", []) if r.get("td")]
            if t.get("classname") == "tradingTable":
                vals = dict(zip(head, (r[0] for r in rows)))
                out["links"][link] = {"buy": hkex_num(vals.get("Buy Turnover")), "sell": hkex_num(vals.get("Sell Turnover"))}
            elif t.get("classname") == "top10Table":
                col = {h: k for k, h in enumerate(head)}
                for r in rows:
                    code = r[col["Stock Code"]].strip()
                    buy, sell = hkex_num(r[col["Buy Turnover"]]), hkex_num(r[col["Sell Turnover"]])
                    if not code or buy is None or sell is None:
                        continue
                    x = out["top"].setdefault(code, {"code": code, "name": r[col["Stock Name"]].strip(), "buy": 0.0, "sell": 0.0})
                    x["buy"] += buy
                    x["sell"] += sell
    if not out["links"]:
        return None
    out["buy"] = sum(v["buy"] or 0 for v in out["links"].values()) * 1e6  # 百万港元 → 港元
    out["sell"] = sum(v["sell"] or 0 for v in out["links"].values()) * 1e6
    out["net"] = out["buy"] - out["sell"]
    out["top"] = sorted(out["top"].values(), key=lambda x: x["buy"] + x["sell"], reverse=True)
    return out


def hkex_day(d):
    key = d.strftime("%Y%m%d")
    name = cache_name("hkex", key)
    old = load_json(name, None)
    recent = (datetime.now(HK_TZ).date() - d).days < 2
    ttl = 3600 if recent else 6 * 3600 if old and old.get("empty") else None  # None = 不再变化，永久使用
    if old is not None and (ttl is None or time.time() - old["fetched"] < ttl):
        return old["day"]
    hkex_limiter.wait()
    empty = False
    try:
        text = http_get(f"https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{key}e.js", raw=True, ttl=600, timeout=20)
        empty = not text.strip()
        day = hkex_parse(text)
    except ApiError as e:
        if "HTTP 404" not in str(e):
            raise
        day = None  # 非交易日（或当天还没发布）
    with _store_lock:
        save_json(name, {"fetched": time.time(), "day": day, "empty": empty})
    return day


def southbound():
    today = datetime.now(HK_TZ).date()
    dates = [today - timedelta(days=k) for k in range(SOUTH_DAYS) if (today - timedelta(days=k)).weekday() < 5]
    jobs = [(d, POOL.submit(hkex_day, d)) for d in dates]
    days, errors = [], {}
    for d, fut in jobs:
        try:
            x = fut.result(timeout=90)
            if x:
                days.append(x)
        except Exception as e:  # noqa: BLE001 — 个别日子失败不影响其他
            errors[d.isoformat()] = str(e)[:160]
    if not days:
        raise ApiError("HKEX 南向资金数据暂时不可用" + (f"：{next(iter(errors.values()))}" if errors else ""))
    days.sort(key=lambda x: x["date"])
    nets = [x["net"] for x in days]
    streak = 0
    for v in reversed(nets):
        if streak == 0 or (v > 0) == (streak > 0):
            streak += 1 if v > 0 else -1
        else:
            break
    agg5 = {}
    for x in days[-5:]:  # 近 5 日在成交额前 10 里出现过的股票：只覆盖每天最活跃的那 10 只，不是全部
        for t in x["top"]:
            a = agg5.setdefault(t["code"], {"code": t["code"], "name": t["name"], "net": 0.0, "days": 0})
            a["net"] += t["buy"] - t["sell"]
            a["days"] += 1
    last = days[-1]
    turnover20 = [x["buy"] + x["sell"] for x in days[-20:]]
    return {"date": last["date"], "net": last["net"], "buy": last["buy"], "sell": last["sell"],
            "links": {k: {"net": ((v["buy"] or 0) - (v["sell"] or 0)) * 1e6} for k, v in last["links"].items()},
            "net5": sum(nets[-5:]), "net20": sum(nets[-20:]), "avg_abs20": sum(abs(v) for v in nets[-20:]) / len(nets[-20:]),
            "turnover": last["buy"] + last["sell"], "turnover20": sum(turnover20) / len(turnover20), "streak": streak,
            "series": [{"d": x["date"], "net": x["net"]} for x in days],
            "top": [{**t, "net": t["buy"] - t["sell"]} for t in last["top"]],
            "top5d": sorted(agg5.values(), key=lambda a: a["net"], reverse=True), "errors": errors}


# ---------------------------------------------------------------- 新闻影响（免费 RSS + 关键词规则）
# 从公开 RSS 抓最近 72 小时的标题，用透明的关键词规则识别“驱动因素”，给出该因素通常对各商品的影响方向。
# 这只是新闻里常见因果关系的归纳，不是价格预测；标题保留英文原文。

NEWS_ASSETS = ["oil", "natgas", "gold", "silver", "copper"]


def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"})


NEWS_FEEDS = [
    {"id": "gn_oil", "name": "Google News", "url": gnews("crude oil OR OPEC OR Brent")},
    {"id": "gn_gas", "name": "Google News", "url": gnews('"natural gas" prices OR LNG OR "Henry Hub"')},
    {"id": "gn_gold", "name": "Google News", "url": gnews("gold price OR bullion OR silver price")},
    {"id": "gn_copper", "name": "Google News", "url": gnews("copper price OR copper mine OR copper smelter")},
    {"id": "gn_macro", "name": "Google News", "url": gnews('"Federal Reserve" rates OR inflation OR "dollar index"')},
    {"id": "fed", "name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"id": "eia", "name": "EIA", "url": "https://www.eia.gov/rss/todayinenergy.xml"},
    {"id": "investing", "name": "Investing.com", "url": "https://www.investing.com/rss/news_11.rss"},
    {"id": "oilprice", "name": "OilPrice.com", "url": "https://oilprice.com/rss/main"},
    {"id": "mining", "name": "Mining.com", "url": "https://www.mining.com/feed/"},
]

# 标题里提到哪些商品（直接相关）
ASSET_WORDS = {
    "oil": r"\b(oil|crude|brent|wti|opec\+?|barrels?|petroleum|gasoline|diesel|refiner(y|ies)|tankers?)\b",
    "natgas": r"\b(natural gas|natgas|lng|henry hub|gas storage|gas prices?)\b",
    "gold": r"\b(gold|bullion)\b",
    "silver": r"\bsilver\b",
    "copper": r"\bcopper\b",
}

# 驱动因素规则：pattern 命中即触发；eff 为 +2..-2（"mix" 表示方向不确定）；need 表示只在标题提到这些商品时才算；
# unless 命中则不触发（比如“解除制裁”不算“制裁”）。why 是通常的传导逻辑。
# 货币政策类规则要求标题里有央行 / 利率语境，避免 “pivoting to the UAE” 之类误判
MONETARY = r"\b(fed|fed's|federal reserve|fomc|powell|u\.?s\.? central bank)\b"

NEWS_RULES = [
    {"id": "supply_risk", "label": "供应中断风险", "eff": {"oil": 2, "natgas": 1, "gold": 1},
     "pat": r"(hormuz|red sea|houthi|bab el-mandeb).{0,50}(attack|seiz|strike|struck|hit|fire|missile|drone|mines?\b|threat|clos|block|disrupt|halt|divert)|(attack|seiz|strike|missile|drone|threat|clos|block|disrupt).{0,40}(hormuz|red sea|houthi)|houthis? (attack|target|fire|launch)|tanker (attack|seiz|struck|hit)|attack(s|ed)? on (saudi|oil|tanker|refiner)|(pipeline|oil field|oilfield|terminal|export).{0,30}(attack|explosion|outage|shut|halt|disrupt)|drone.{0,25}(refiner|oil|facilit)|force majeure",
     "unless": r"resum|reopen|ease[sd]? .{0,20}(tension|threat)",
     "why": "产油区或航道受威胁，原油供应风险溢价上升；中东局势紧张也常带动避险买盘"},
    {"id": "geo_escalation", "label": "地缘冲突升级", "eff": {"gold": 1, "silver": 1, "oil": 1},
     "pat": r"\bwar\b|missile|invasion|escalat|air ?strikes?|military (strike|action|operation)|retaliat|troops|\battack(s|ed)? (on|against)|strikes? against",
     "unless": r"ceasefire|truce|peace|wrapped up|end(ing)? the war|trade war|price war|tariff", "why": "冲突升级推高避险需求，若涉及产油区还会推高原油风险溢价"},
    {"id": "deescalation", "label": "局势缓和 / 停火", "eff": {"oil": -1, "gold": -1, "silver": -1},
     "pat": r"ceasefire|truce|peace (deal|talks|agreement|plan)|de-?escalat|wrapped up soon|end(ing)? the war",
     "why": "冲突缓和会压低原油风险溢价，避险资金也可能流出黄金"},
    {"id": "opec_cut", "label": "OPEC+ 减产 / 延长减产", "eff": {"oil": 2}, "need": ["oil"],
     "pat": r"(opec\+?|saudi|output|production).{0,40}(cut|curb|reduc|extend(s|ed|ing)? (the )?cuts|lower output)",
     "unless": r"(raise|boost|increase|hike|unwind|ramp up)|\bosps?\b|selling price|prices? (to|for) (asia|europe|u\.?s)|price cuts?|cuts? .{0,20}prices", "why": "主动减少供应，通常支撑油价"},
    {"id": "opec_hike", "label": "OPEC+ 增产", "eff": {"oil": -2}, "need": ["oil"],
     "pat": r"(opec\+?|saudi|output|production).{0,40}(raise|boost|increase|hike|unwind|ramp up|add)|(output|production) (hike|increase|boost)",
     "why": "供应增加，通常压制油价"},
    {"id": "sanctions", "label": "能源制裁收紧", "eff": {"oil": 1, "natgas": 1},
     "pat": r"sanction.{0,40}(iran|russia|venezuela|oil|crude|tanker|lng)|(iran|russia|russian|venezuela).{0,40}sanction",
     "unless": r"lift(s|ed|ing)? sanction|eas(e|es|ed|ing) sanction|sanctions? relief|waiver", "why": "受制裁国的出口受限，可交易的供应减少"},
    {"id": "sanctions_relief", "label": "制裁放松", "eff": {"oil": -1},
     "pat": r"lift(s|ed|ing)? sanction|eas(e|es|ed|ing) sanction|sanctions? relief|sanctions? waiver", "why": "更多受制裁国的原油可以回到市场"},
    {"id": "inv_build", "label": "库存增加", "eff": {"oil": -1, "natgas": -1}, "need": ["oil", "natgas"],
     "pat": r"(inventor(y|ies)|stockpiles?|(crude|oil|gasoline|distillate|gas) stocks|storage).{0,30}(build|rise|rose|jump|climb|increase|swell|surge)|(build|rise|jump|increase) in (crude )?(inventor|stockpile|stocks|storage)|storage (injection|build)",
     "unless": r"stocks? (to|worth)|shares",
     "why": "库存增加说明供应相对需求偏多，通常压制价格（只作用于标题提到的品种）"},
    {"id": "inv_draw", "label": "库存下降", "eff": {"oil": 1, "natgas": 1}, "need": ["oil", "natgas"],
     "pat": r"(inventor(y|ies)|stockpiles?|(crude|oil|gasoline|distillate|gas) stocks|storage).{0,30}(draw|fell|fall|drop|declin|shrink|slump)|(draw|drop|decline) in (crude )?(inventor|stockpile|stocks|storage)",
     "unless": r"stocks? (to|worth)|shares",
     "why": "库存下降说明需求相对供应偏强，通常支撑价格（只作用于标题提到的品种）"},
    {"id": "fed_hawkish", "label": "美联储偏鹰 / 加息预期", "eff": {"gold": -2, "silver": -2, "copper": -1},
     "pat": r"rate hikes?|hike (interest )?rates|hawkish|higher[- ]for[- ]longer|raise (interest )?rates|tighten(ing)? (cycle|policy)|fewer (rate )?cuts|cut bets? (fade|recede)",
     "ctx": MONETARY, "unless": r"dovish", "why": "实际利率上升会提高持有黄金等无息资产的机会成本，美元也常随之走强"},
    {"id": "fed_dovish", "label": "美联储偏鸽 / 降息预期", "eff": {"gold": 2, "silver": 2, "copper": 1},
     "pat": r"rate cuts?|cut (interest )?rates|dovish|lower (interest )?rates|easing cycle|(fed|policy) pivot",
     "ctx": MONETARY,
     "unless": r"fewer (rate )?cuts|cut bets? (fade|recede)|hawkish|no (rate )?cut|\b(pare|pares|pared|trim|trims|scale back|scales back|dial back|no rush|in no hurry|dim|dims|dash|dashes|delay)\b", "why": "降息预期压低实际利率和美元，通常利好黄金白银，也改善工业金属需求预期"},
    {"id": "fomc", "label": "美联储会议 / 官方公告", "eff": {"gold": "mix", "silver": "mix"},
     "pat": r"\bfomc\b|minutes of the federal open market|fed (holds|keeps|leaves) rates|rate decision", "why": "官方利率决议或会议纪要，方向取决于具体内容，需看原文"},
    {"id": "inflation_hot", "label": "通胀偏热", "eff": {"gold": "mix", "silver": "mix"},
     "pat": r"(inflation|\bcpi\b|\bpce\b|consumer prices).{0,30}(hot|accelerat|higher than expected|above (expectations|forecast)|jump|surge|sticky|rise|rose)|inflation (concern|worr|fear)",
     "why": "黄金长期抗通胀，但通胀偏热会推高加息预期、短期压制金价，方向不确定"},
    {"id": "usd_strong", "label": "美元走强", "eff": {"gold": -1, "silver": -1, "copper": -1, "oil": -1},
     "pat": r"(dollar|greenback|dxy)[^,;]{0,12}\b(rise|rises|rally|rallies|strengthen|jump|gain|surge|firm|climb|hits? .{0,10}high)", "why": "大宗商品以美元计价，美元走强通常压制以美元计的价格"},
    {"id": "usd_weak", "label": "美元走弱", "eff": {"gold": 1, "silver": 1, "copper": 1, "oil": 1},
     "pat": r"(dollar|greenback|dxy)[^,;]{0,12}\b(fall|falls|slide|slides|slip|slips|weaken|drop|slump|tumble|retreat|hits? .{0,10}low)", "why": "美元走弱通常推高以美元计价的大宗商品"},
    {"id": "china_stimulus", "label": "中国刺激政策", "eff": {"copper": 2, "oil": 1, "silver": 1},
     "pat": r"(china|chinese|beijing|pboc).{0,40}(stimulus|rate cut|cuts? rates|easing|support measures|infrastructure spending|rrr)", "why": "中国是铜和原油最大的消费国，刺激政策改善需求预期"},
    {"id": "china_weak", "label": "中国需求偏弱", "eff": {"copper": -1, "oil": -1},
     "pat": r"(china|chinese).{0,40}(slow|weak|contract|slump|deflation|property crisis|demand (worr|concern))", "why": "中国需求走弱会拖累铜和原油的消费预期"},
    {"id": "trade_war", "label": "关税 / 贸易摩擦", "eff": {"copper": -1, "oil": -1, "gold": 1},
     "pat": r"tariffs?|trade war|trade tension|export (ban|curb|control)", "why": "贸易摩擦打压全球增长和工业品需求预期，同时增加避险需求"},
    {"id": "recession", "label": "衰退 / 需求担忧", "eff": {"oil": -1, "copper": -1, "gold": 1},
     "pat": r"recession|slowdown|demand (concern|worr|fear|weak)|weak demand|economic (gloom|downturn)", "why": "经济放缓压低能源和工业金属需求，资金可能转向黄金避险"},
    {"id": "hurricane", "label": "飓风 / 墨西哥湾天气", "eff": {"oil": 1, "natgas": 1},
     "pat": r"hurricane|tropical storm|gulf of mexico.{0,30}(storm|shut|evacuat)", "why": "墨西哥湾油气平台可能停产，短期供应受影响"},
    {"id": "weather_cold", "label": "寒潮 / 热浪（用气需求增加）", "eff": {"natgas": 2},
     "pat": r"cold (snap|blast|weather|front)|\b(freeze|freezing) (weather|temperatures|conditions)|deep freeze|hard freeze|winter storm|arctic blast|polar vortex|heat ?wave|hotter than", "why": "取暖或制冷需求上升，天然气消耗增加"},
    {"id": "weather_mild", "label": "天气温和（用气需求减少）", "eff": {"natgas": -2},
     "pat": r"mild (weather|winter|temperatures)|warm(er)? (weather|winter)|weak heating demand", "why": "取暖需求偏弱，天然气消耗减少"},
    {"id": "lng_export", "label": "LNG 出口变化", "eff": {"natgas": "mix"}, "need": ["natgas"],
     "pat": r"\blng\b.{0,40}(export|outage|shutdown|halt|restart|record|fire|terminal)", "why": "美国 LNG 出口受阻会让国内天然气过剩（偏空 Henry Hub），出口增加则相反，需看原文"},
    {"id": "mine_disruption", "label": "矿山 / 冶炼供应中断", "eff": {"copper": 2, "silver": 1},
     "pat": r"\b(mine|mines|smelter|smelters|mining)\b.{0,40}(strike|halt|shut|outage|accident|flood|protest|suspend|force majeure|landslide)|(strike|halt|suspend).{0,30}\b(mine|mines|smelter)\b", "why": "铜精矿或冶炼供应减少，通常支撑铜价"},
    {"id": "cb_gold", "label": "央行购金", "eff": {"gold": 2}, "need": ["gold"],
     "pat": r"central banks?.{0,40}(buy|purchas|add|accumulat)|(pboc|reserve bank).{0,30}(gold (purchas|buy)|adds? gold)", "why": "官方持续买入是金价的重要支撑"},
    {"id": "etf_flow", "label": "黄金 ETF 资金流", "eff": {"gold": "mix"}, "need": ["gold"],
     "pat": r"\betfs?\b.{0,30}(inflow|outflow|holdings)", "why": "ETF 流入表示投资需求增加、流出则相反，需看原文方向"},
    {"id": "spr_release", "label": "美国战略储备释放", "eff": {"oil": -1},
     "pat": r"(strategic petroleum reserve|\bspr\b).{0,40}(release|sell|sale|drawdown|tap)", "why": "政府释放储备增加短期供应"},
    {"id": "spr_refill", "label": "美国战略储备回补", "eff": {"oil": 1},
     "pat": r"(strategic petroleum reserve|\bspr\b).{0,40}(refill|buy|purchase|replenish)", "why": "政府采购增加需求"},
]
for _r in NEWS_RULES:
    _r["re"] = re.compile(_r["pat"], re.I)
    _r["unless_re"] = re.compile(_r["unless"], re.I) if _r.get("unless") else None
    _r["ctx_re"] = re.compile(_r["ctx"], re.I) if _r.get("ctx") else None
ASSET_RE = {k: re.compile(v, re.I) for k, v in ASSET_WORDS.items()}
PRICE_REPORT_RE = re.compile(r"\b(price|prices|futures|rate)\b.{0,40}\b(today|rises?|falls?|slips?|drops?|gains?|climbs?|hits?|tumbles?|rall(y|ies)|surges?|plunges?|steady|edges?|record|forecast)\b|\bprice (forecast|prediction|today)\b", re.I)


def parse_rss_date(s):
    if not s:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:  # “-0000”或没写时区：按 UTC，而不是本机时间
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, IndexError):
        pass
    try:  # ISO 8601（Atom / dc:date）
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())
    except ValueError:
        pass
    try:  # Investing.com 的格式：2026-10-30 16:30:54（UTC）
        return int(datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def fetch_feed(f):
    name = cache_name("news", f["id"])

    def fetch():
        text = http_get(f["url"], ttl=900, raw=True, timeout=20)
        root = parse_xml(text)
        items = []
        for it in root.iter("item"):
            title = html.unescape((it.findtext("title") or "").strip())
            src = it.find("source")
            source = (src.text or "").strip() if src is not None and src.text else f["name"]
            if "news.google.com" in f["url"] and source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]  # Google News 标题末尾带“ - 媒体名”
            if title:
                link = (it.findtext("link") or "").strip()
                if not re.match(r"^https?://", link, re.I):
                    link = ""  # 只保留 http(s) 链接，防止 RSS 里塞 javascript: 之类的地址
                items.append({"title": title, "link": link, "ts": parse_rss_date(it.findtext("pubDate")),
                              "source": source, "feed": f["id"]})
        fetched = time.time()
        with _store_lock:
            save_json(name, {"fetched": fetched, "items": items})
        return items, fetched

    old = load_json(name, None)
    age = time.time() - old["fetched"] if old else None
    if old and age < 900:
        return old["items"], old["fetched"]
    if old and age < 2 * 3600:
        refresh_later("news:" + f["id"], fetch)
        return old["items"], old["fetched"]
    try:  # 太旧（比如电脑关了几天）：当场取新的，失败了再退回旧数据
        return fetch()
    except Exception:  # noqa: BLE001
        if old:
            return old["items"], old["fetched"]
        raise


def classify(title):
    mentioned = [a for a, r in ASSET_RE.items() if r.search(title)]
    drivers, effects = [], {}
    for r in NEWS_RULES:
        if not r["re"].search(title) or (r["unless_re"] and r["unless_re"].search(title)) or (r["ctx_re"] and not r["ctx_re"].search(title)):
            continue
        if r.get("need") and not any(a in mentioned for a in r["need"]):
            continue
        eff = {}
        for a, v in r["eff"].items():
            if r.get("need") and a not in mentioned:
                continue  # 库存类规则只作用于标题里提到的商品
            eff[a] = v
        if not eff:
            continue
        drivers.append(r["id"])
        for a, v in eff.items():
            w = 1.0 if a in mentioned or not mentioned else 0.5  # 标题没提到这个商品时算“间接影响”，权重减半
            effects.setdefault(a, []).append({"rule": r["id"], "v": v, "w": w})
    return {"assets": mentioned, "drivers": drivers, "effects": effects,
            "price_report": not drivers and bool(PRICE_REPORT_RE.search(title))}


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:90]


def news():
    jobs = [(f, POOL.submit(fetch_feed, f)) for f in NEWS_FEEDS]
    now = time.time()
    items, seen, errors, data_ts = [], set(), {}, now
    for f, fut in jobs:
        try:
            got, ft = fut.result(timeout=40)
            data_ts = min(data_ts, ft)
        except Exception as e:  # noqa: BLE001 — 个别源失败不影响其他
            errors[f["id"]] = str(e)[:160]
            continue
        for it in got:
            if not it["ts"] or now - it["ts"] > 72 * 3600 or it["ts"] > now + 3600:
                continue
            k = norm_title(it["title"])
            if k in seen:
                continue
            seen.add(k)
            c = classify(it["title"])
            if not c["assets"] and not c["drivers"]:
                continue  # 和这几种商品都无关的标题（比如矿业公司财报、光伏）不显示
            items.append({**it, **c})
    items.sort(key=lambda x: x["ts"], reverse=True)
    # 汇总：时间衰减（半衰期 24 小时）；同一驱动因素对同一商品最多计 4 条，避免多家媒体重复报道同一事件被放大
    rules = {r["id"]: r for r in NEWS_RULES}
    summary = {}
    for a in NEWS_ASSETS:
        score, pos, neg, mix, by_rule, count = 0.0, 0.0, 0.0, 0, {}, 0
        for it in items:
            for e in it["effects"].get(a, []):
                n = by_rule.setdefault(e["rule"], {"n": 0, "score": 0.0, "mix": e["v"] == "mix"})
                n["n"] += 1
                count += 1
                if n["n"] > 4 or e["v"] == "mix":
                    mix += e["v"] == "mix"
                    continue
                s = e["v"] * e["w"] * 0.5 ** ((now - it["ts"]) / 86400)
                n["score"] += s
                score += s
                pos += max(s, 0)
                neg += min(s, 0)
        tops = sorted(by_rule.items(), key=lambda kv: (-abs(kv[1]["score"]), -kv[1]["n"]))[:4]
        label = "neutral"
        if pos >= 1.5 and -neg >= 1.5 and abs(score) < 1.5:
            label = "mixed"
        elif score >= 1.5:
            label = "bull"
        elif score <= -1.5:
            label = "bear"
        summary[a] = {"score": round(score, 2), "pos": round(pos, 2), "neg": round(neg, 2), "label": label, "count": count, "mix": mix,
                      "drivers": [{"rule": k, "label": rules[k]["label"], "n": v["n"], "score": round(v["score"], 2), "mix": v["mix"]} for k, v in tops]}
    if items and not errors.keys() >= {f["id"] for f in NEWS_FEEDS}:
        record_news_tilt(summary)
    return {"items": items[:300], "summary": summary, "errors": errors, "rules": [{"id": r["id"], "label": r["label"], "why": r["why"], "eff": r["eff"]} for r in NEWS_RULES],
            "fetched": int(now), "data_ts": int(data_ts)}


# ---------------------------------------------------------------- AI / 科技股新闻（标签分类）
# 两个维度打标签：公司（上市公司带代码，OpenAI 等未上市只做实体标签）和话题（AI 芯片、资本开支、财报、出口管制……）。
# 话题的 tone 是这类消息对被点名公司“通常”的含义（+1 偏正面 / -1 偏负面 / 0 中性），不是股价预测。

TECH_FEEDS = [
    {"id": "gt_chips", "name": "Google News", "url": gnews("Nvidia OR TSMC OR AMD OR Broadcom OR semiconductor stocks")},
    {"id": "gt_ai", "name": "Google News", "url": gnews('OpenAI OR Anthropic OR "artificial intelligence" stocks OR "AI spending"')},
    {"id": "gt_bigtech", "name": "Google News", "url": gnews("Microsoft OR Alphabet OR Meta OR Amazon OR Apple stock")},
    {"id": "gt_china", "name": "Google News", "url": gnews("Tencent OR Alibaba OR Baidu OR Xiaomi OR SMIC stock")},
    {"id": "gt_policy", "name": "Google News", "url": gnews('chip "export controls" OR "AI regulation" OR antitrust tech')},
    {"id": "cnbc_tech", "name": "CNBC", "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html"},
    {"id": "techcrunch", "name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
]

# (代码或实体名, 显示名, 正则)；代码为 None 的是未上市公司
TECH_COMPANIES = [
    ("NVDA", "Nvidia", r"nvidia|\bnvda\b|jensen huang|blackwell"), ("AMD", "AMD", r"\bamd\b|advanced micro devices"),
    ("TSM", "TSMC", r"\btsmc\b|taiwan semiconductor"), ("AVGO", "Broadcom", r"broadcom|\bavgo\b"),
    ("MSFT", "Microsoft", r"microsoft|\bmsft\b|\bazure\b"), ("GOOGL", "Alphabet", r"alphabet|google|\bgemini\b|deepmind|waymo"),
    ("META", "Meta", r"\bmeta\b|facebook|instagram|zuckerberg"), ("AMZN", "Amazon", r"amazon|\baws\b|\bamzn\b"),
    ("AAPL", "Apple", r"\bapple\b|iphone|\baapl\b"), ("TSLA", "Tesla", r"tesla|\btsla\b"),
    ("PLTR", "Palantir", r"palantir|\bpltr\b"), ("ORCL", "Oracle", r"\boracle\b|\borcl\b"),
    ("INTC", "Intel", r"\bintel\b|\bintc\b"), ("ARM", "Arm", r"arm holdings|\barm (ltd|plc|stock|shares|chips?)\b"),
    ("ASML", "ASML", r"\basml\b"), ("MU", "Micron", r"micron"), ("SMCI", "Super Micro", r"super ?micro|\bsmci\b"),
    ("0700.HK", "Tencent", r"tencent"), ("9988.HK", "Alibaba", r"alibaba|\bqwen\b"), ("9888.HK", "Baidu", r"baidu|\bernie\b"),
    ("1810.HK", "Xiaomi", r"xiaomi"), ("0981.HK", "SMIC", r"\bsmic\b|semiconductor manufacturing international"),
    (None, "OpenAI", r"openai|chatgpt|\bgpt-?\d"), (None, "Anthropic", r"anthropic|\bclaude\b"), (None, "xAI", r"\bxai\b|\bgrok\b"),
]
TECH_TOPICS = [
    {"id": "ai_chips", "label": "AI 芯片 / 算力", "tone": 0, "pat": r"\bgpus?\b|\bchips?\b|semiconductor|accelerator|blackwell|\brubin\b|\bhbm\b|\btpus?\b|compute capacity"},
    {"id": "ai_capex", "label": "AI 资本开支", "tone": 0,
     "pat": r"capex|capital (expenditure|spending)|data ?cent(er|re)s?.{0,30}(spend|invest|build|billion)|(spend|invest|pour)\w*.{0,30}billion|\bai (spending|investment|infrastructure|buildout)"},
    {"id": "ai_model", "label": "AI 模型 / 产品发布", "tone": 0,
     "pat": r"(launch|unveil|release|introduc|debut|roll(s|ed|ing)? out)\w*.{0,40}(model|\bai\b|chatbot|agent|assistant|\bgpt|gemini|claude|llama)|new (ai )?model"},
    {"id": "ai_power", "label": "AI 用电 / 能源", "tone": 0,
     "pat": r"\b(power|electricity|energy|nuclear|grid|gas turbines?)\b.{0,30}(\bai\b|data ?cent)|(\bai\b|data ?cent\w*).{0,30}\b(power|electricity|energy|nuclear|grid)\b"},
    {"id": "earnings", "label": "财报 / 业绩", "tone": 0, "pat": r"earnings|quarterly (results|revenue|profit|sales)|\bq[1-4]\b.{0,20}(results|earnings|revenue|sales)|revenue|profit"},
    {"id": "beat", "label": "业绩超预期 / 上调指引", "tone": 1,
     "pat": r"(beats?|beating) (estimates|expectations|forecasts|views)|tops? (estimates|expectations|forecasts)|(raising|lifting) (its )?(guidance|forecast|outlook)|record (revenue|profit|sales)|(raises?|lifts?|boosts?) (its )?(guidance|forecast|outlook)|(strong|upbeat|bullish) (guidance|forecast|outlook)"},
    {"id": "miss", "label": "业绩不及预期 / 下调指引", "tone": -1,
     "pat": r"miss(es)? (estimates|expectations|forecasts)|falls? short|(cuts?|lowers?|slashes?) (its )?(guidance|forecast|outlook)|(weak|disappointing|soft) (guidance|forecast|outlook|results)|profit warning"},
    {"id": "export_ctrl", "label": "出口管制 / 中美科技", "tone": -1,
     "pat": r"export (control|curb|ban|restriction|licen[cs]e)|chip (ban|curb|restriction)|entity list|(china|chinese|beijing).{0,40}(ban|restrict|probe|bars?).{0,30}(chips?|nvidia|semiconductor)|tariffs? on (chips|semiconductors)"},
    {"id": "regulation", "label": "监管 / 反垄断 / 诉讼", "tone": -1,
     "pat": r"antitrust|regulators?|\bftc\b|\bdoj\b|lawsuit|\bsues?\b|\bsued\b|\bfined\b|\bfines?\b(?!-)|probe|investigation|european commission|\beu\b.{0,20}(rules|act|fine)"},
    {"id": "mna", "label": "并购 / 融资 / IPO", "tone": 0,
     "pat": r"acqui(re|res|red|sition)|merger|takeover|funding round|raises? \$|\bvaluation\b|\bipo\b|(buys?|takes?|acquires?|sells?) .{0,15}stake"},
    {"id": "partner", "label": "合作 / 大单", "tone": 1,
     "pat": r"partner(s|ship)?\b|deal with|agreement with|\bcontract\b|supply deal|multi-?billion.{0,20}(deal|order)|collaborat"},
    {"id": "supply", "label": "供应链 / 产能", "tone": 0, "pat": r"capacity|shortage|supply (chain|constraint)|\bfabs?\b|foundry|advanced packaging|cowos"},
    {"id": "analyst_up", "label": "分析师上调", "tone": 1, "pat": r"upgrade|(raises?|lifts?|hikes?) (price )?target|(to|an?) outperform|outperform rating|overweight|buy rating|bullish calls?"},
    {"id": "analyst_down", "label": "分析师下调", "tone": -1, "pat": r"downgrade|(cuts?|lowers?|slashes?) (price )?target|(to|an?) underperform|underperform rating|underweight|sell rating"},
    {"id": "bubble", "label": "估值 / 泡沫担忧", "tone": -1, "pat": r"\bbubble\b|overvalued|frothy|valuation (concern|worr|fear)|ai (trade|stocks?) (sell-?off|rout|slump)"},
    {"id": "people", "label": "裁员 / 管理层变动", "tone": 0, "pat": r"layoffs?|job cuts|cuts? [\d,]+ jobs|steps? down|resign|new ceo|names .{0,20}ceo"},
    {"id": "incident", "label": "故障 / 安全事件", "tone": -1, "pat": r"outage|breach|hack(ed|ers)?|cyberattack|recall|vulnerabilit"},
    {"id": "move_up", "label": "行情：大涨", "tone": 0, "pat": r"\b(stocks?|shares|nasdaq)\b.{0,30}\b(soar|surge|skyrocket|jump|rall(y|ies)|gain)\w*|\b(soar|surge|skyrocket|jump)\w*.{0,15}\b(stocks?|shares)\b|record high|all-time high"},
    {"id": "move_down", "label": "行情：大跌", "tone": 0, "pat": r"\b(plunge|tumble|sink|slump|crater|sell-?off)\w*|worst day"},
]
for _c in TECH_TOPICS:
    _c["re"] = re.compile(_c["pat"], re.I)
TECH_CO_RE = [(t, n, re.compile(p, re.I)) for t, n, p in TECH_COMPANIES]


def tech_classify(title):
    cos = [{"ticker": t, "name": n} for t, n, r in TECH_CO_RE if r.search(title)]
    topics = [c["id"] for c in TECH_TOPICS if c["re"].search(title)]
    tones = [c["tone"] for c in TECH_TOPICS if c["id"] in topics and c["tone"]]
    return {"companies": cos, "topics": topics, "tone": max(-1, min(1, sum(tones)))}


def tech_news():
    jobs = [(f, POOL.submit(fetch_feed, f)) for f in TECH_FEEDS]
    now = time.time()
    items, seen, errors, data_ts = [], set(), {}, now
    for f, fut in jobs:
        try:
            got, ft = fut.result(timeout=40)
            data_ts = min(data_ts, ft)
        except Exception as e:  # noqa: BLE001
            errors[f["id"]] = str(e)[:160]
            continue
        for it in got:
            if not it["ts"] or now - it["ts"] > 72 * 3600 or it["ts"] > now + 3600:
                continue
            k = norm_title(it["title"])
            if k in seen:
                continue
            seen.add(k)
            c = tech_classify(it["title"])
            if not c["companies"] and not c["topics"]:
                continue
            if not c["companies"] and not re.search(r"\bai\b|artificial intelligence|tech|chip|semiconductor", it["title"], re.I):
                continue  # 没点名公司、也和 AI / 科技无关的标题（例如普通的诉讼新闻）不要
            items.append({**it, **c})
    items.sort(key=lambda x: x["ts"], reverse=True)
    topic_count = {c["id"]: 0 for c in TECH_TOPICS}
    cos = {}
    for it in items:
        for t in it["topics"]:
            topic_count[t] += 1
        w = 0.5 ** ((now - it["ts"]) / 86400)
        for c in it["companies"]:
            key = c["ticker"] or c["name"]
            e = cos.setdefault(key, {"ticker": c["ticker"], "name": c["name"], "count": 0, "tone": 0.0, "pos": 0, "neg": 0, "topics": {}})
            e["count"] += 1
            e["tone"] += it["tone"] * w
            e["pos"] += it["tone"] > 0
            e["neg"] += it["tone"] < 0
            for t in it["topics"]:
                e["topics"][t] = e["topics"].get(t, 0) + 1
    ranked = sorted(cos.values(), key=lambda e: -e["count"])[:16]
    quotes = {e["ticker"]: POOL.submit(quote_summary, e["ticker"]) for e in ranked if e["ticker"]}
    for e in ranked:
        e["tone"] = round(e["tone"], 2)
        e["topics"] = [k for k, _ in sorted(e["topics"].items(), key=lambda kv: -kv[1])[:4]]
        q = quotes.get(e["ticker"])
        try:
            r = q.result(timeout=30) if q else None
            e["price"] = {"price": r["price"], "chg1d": r["chg1d"], "chg1w": r["chg1w"], "currency": r["currency"]} if r else None
        except Exception:  # noqa: BLE001 — 行情失败不影响新闻
            e["price"] = None
    return {"items": items[:300], "companies": ranked, "topics": [{"id": c["id"], "label": c["label"], "tone": c["tone"], "count": topic_count[c["id"]]} for c in TECH_TOPICS],
            "errors": errors, "fetched": int(now), "data_ts": int(data_ts)}


# ---------------------------------------------------------------- 新闻倾向事后验证
# 每个 UTC 日保留首次新闻倾向；以信号日期之后首个交易日收盘作基准，对照后续 1 / 5 个交易日涨跌。
# 同一基准交易日只取最早的快照，避免周末 / 假日重复计样；当天未完成的日线不参与评估。

NEWS_SYM = {"oil": "CL=F", "natgas": "NG=F", "gold": "GC=F", "silver": "SI=F", "copper": "HG=F"}
_tilt = {"last": 0}


def record_news_tilt(summary):
    now = time.time()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    with _store_lock:
        if now - _tilt["last"] < 600:  # 最多 10 分钟检查一次
            return
        hist = load_json("news_tilt.json", {})
        if day not in hist:
            hist[day] = {a: {"label": v["label"], "score": v["score"], "count": v["count"], "ts": int(now)} for a, v in summary.items()}
            save_json("news_tilt.json", hist)
        _tilt["last"] = now


def news_accuracy():
    hist = load_json("news_tilt.json", {})
    today = datetime.now(timezone.utc).date().isoformat()
    out = []
    for a, sym in NEWS_SYM.items():
        row = {"asset": a, "sym": sym, "days": sum(1 for d in hist if a in hist[d]), "signals": 0, "n1": 0, "hit1": 0, "n5": 0, "hit5": 0,
               "base1": None, "base5": None, "since": min(hist) if hist else None}
        try:
            h = daily_hist(sym)
        except Exception:  # noqa: BLE001 — 行情取不到就只显示记录天数
            out.append(row)
            continue
        end = bisect.bisect_left(h["days"], today)
        days, close = h["days"][:end], h["close"][:end]
        ups1 = ups5 = tot1 = tot5 = 0
        samples = {}
        for d in hist:
            v = hist[d].get(a)
            if not v:
                continue
            try:
                ts = float(v.get("ts", 0))
                if not math.isfinite(ts) or not 0 < ts <= time.time():
                    continue
                signal_day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                continue  # 旧记录缺少有效时间戳时保留，但不计入命中率
            i = bisect.bisect_right(days, signal_day)
            if i >= len(days) or not close[i]:
                continue
            if i not in samples or ts < samples[i][0]:
                samples[i] = (ts, v)
        for i, (_, v) in sorted(samples.items()):
            r1 = close[i + 1] / close[i] - 1 if i + 1 < len(close) else None
            r5 = close[i + 5] / close[i] - 1 if i + 5 < len(close) else None
            tot1 += r1 is not None
            ups1 += bool(r1 and r1 > 0)
            tot5 += r5 is not None
            ups5 += bool(r5 and r5 > 0)
            if not v or v["label"] not in ("bull", "bear"):
                continue
            row["signals"] += 1
            sign = 1 if v["label"] == "bull" else -1
            if r1 is not None:
                row["n1"] += 1
                row["hit1"] += r1 * sign > 0
            if r5 is not None:
                row["n5"] += 1
                row["hit5"] += r5 * sign > 0
        row["base1"] = ups1 / tot1 if tot1 else None
        row["base5"] = ups5 / tot5 if tot5 else None
        out.append(row)
    return {"assets": out, "days": len(hist), "since": min(hist) if hist else None}


def tilt_loop_tick():
    """后台每小时记录一次新闻倾向（网页没开也会积累数据）"""
    if time.time() - _tilt["last"] >= 3600:
        news()


# ---------------------------------------------------------------- 重大新闻提醒
# “重大”= 通常影响强（▲▲ / ▼▼）的驱动因素，标题直接提到该商品，且 6 小时内至少 N 家不同媒体报道。
# 同一“因素 + 商品”12 小时内只提醒一次；每次检查最多推送 3 条。和自选异动提醒分开开关、分开记录。

NEWS_ALERT_TEXT = {
    "zh": {"title": "量化股神 · 重大新闻", "src": "家媒体", "more": "另有 {n} 条重大新闻，打开量化股神查看",
           "assets": {"oil": "原油", "natgas": "天然气", "gold": "黄金", "silver": "白银", "copper": "铜"}},
    "ja": {"title": "量化株神 · 重要ニュース", "src": "媒体", "more": "他に重要ニュース {n} 件。量化株神で確認してください",
           "assets": {"oil": "原油", "natgas": "天然ガス", "gold": "金", "silver": "銀", "copper": "銅"}},
    "en": {"title": "Quant Stock God · Major news", "src": "outlets", "more": "{n} more major news items — open Quant Stock God",
           "assets": {"oil": "Crude", "natgas": "Natgas", "gold": "Gold", "silver": "Silver", "copper": "Copper"}},
}
# 只有强影响因素会触发提醒，所以只需要这几条的日文 / 英文名称
NEWS_LABEL_I18N = {
    "supply_risk": ("供給途絶リスク", "Supply disruption risk"), "opec_cut": ("OPEC+ 減産", "OPEC+ cut"),
    "opec_hike": ("OPEC+ 増産", "OPEC+ output increase"), "fed_hawkish": ("FRB タカ派", "Hawkish Fed"),
    "fed_dovish": ("FRB ハト派", "Dovish Fed"), "china_stimulus": ("中国の景気刺激策", "China stimulus"),
    "weather_cold": ("寒波 / 熱波", "Cold snap / heat wave"), "weather_mild": ("温暖な天候", "Mild weather"),
    "mine_disruption": ("鉱山 / 製錬の供給途絶", "Mine / smelter disruption"), "cb_gold": ("中央銀行の金購入", "Central-bank gold buying"),
}
_news_alert = {"last_run": None, "last_error": None, "next_run": 0, "running": False}
_news_alert_lock = threading.Lock()


def news_alert_settings():
    cfg = load_json("config.json", {})
    assets = [a for a in (cfg["news_assets"] if "news_assets" in cfg else NEWS_ASSETS) if a in NEWS_ASSETS]
    return {"enabled": bool(cfg.get("news_alert")), "assets": assets, "min_src": int(cfg.get("news_min_src") or 2),
            "since": cfg.get("news_alert_since") or 0, "lang": cfg.get("alert_lang") or "en", "sound": cfg.get("alert_sound", True)}


def run_news_alerts():
    if not _news_alert_lock.acquire(blocking=False):
        return None
    try:
        _news_alert["running"] = True
        st = news_alert_settings()
        T = NEWS_ALERT_TEXT.get(st["lang"], NEWS_ALERT_TEXT["en"])
        now = time.time()
        data = news()
        rules = {r["id"]: r for r in NEWS_RULES}
        # 用“第一次见到这条标题的时间”判断新旧，而不是发布时间：新闻源有缓存、Google News 收录也会晚几分钟到几小时，
        # 按发布时间和上次检查时间比较会把晚到的消息永远漏掉
        with _store_lock:
            seen = load_json("news_alert_seen.json", {})
        baseline = not seen  # 刚开启（或第一次）时没有记录：发布时间在 since（开启时往前 3 小时）之后的算新消息
        fresh_keys = set()
        for it in data["items"]:
            k = norm_title(it["title"])
            if k not in seen:
                seen[k] = int(now)
                if not baseline or it["ts"] >= st["since"]:
                    fresh_keys.add(k)
        clusters = {}
        for it in data["items"]:
            if it["ts"] < now - 6 * 3600:
                continue
            for a, es in it["effects"].items():
                if a not in st["assets"] or a not in it["assets"]:
                    continue  # 只看标题直接提到的商品
                for e in es:
                    if e["v"] == "mix" or abs(e["v"]) < 2:
                        continue
                    c = clusters.setdefault((e["rule"], a), {"items": [], "sources": set(), "v": e["v"], "fresh": []})
                    c["items"].append(it)
                    c["sources"].add(it["source"].lower())
                    if norm_title(it["title"]) in fresh_keys:
                        c["fresh"].append(it)
        with _store_lock:
            marks = load_json("news_alert_marks.json", {})
        found = []
        for (rule, a), c in clusters.items():
            key = f"{rule}:{a}"
            # 至少要有一条这次新出现的标题，否则只是旧消息又被统计了一遍
            if len(c["sources"]) < st["min_src"] or not c["fresh"] or now - marks.get(key, 0) < 12 * 3600:
                continue
            newest = max(c["fresh"], key=lambda x: x["ts"])
            marks[key] = int(now)
            found.append({"ts": int(now), "asset": a, "rule": rule, "label": rules[rule]["label"], "v": c["v"],
                          "n": len(c["items"]), "sources": len(c["sources"]), "title": newest["title"], "link": newest["link"],
                          "source": newest["source"], "news_ts": newest["ts"]})
        found.sort(key=lambda f: (-f["sources"], -f["news_ts"]))
        marks = {k: v for k, v in marks.items() if v > now - 7 * 86400}
        seen = {k: v for k, v in seen.items() if v > now - 4 * 86400}
        with _store_lock:
            save_json("news_alert_marks.json", marks)
            save_json("news_alert_seen.json", seen)
            if found:
                save_json("news_alerts.json", (found + load_json("news_alerts.json", []))[:200])
            cfg = load_json("config.json", {})
            cfg["news_alert_since"] = int(now)
            save_json("config.json", cfg)
        li = {"ja": 0, "en": 1}.get(st["lang"])
        for f in found[:3]:
            label = NEWS_LABEL_I18N[f["rule"]][li] if li is not None and f["rule"] in NEWS_LABEL_I18N else f["label"]
            arrow = "▲▲" if f["v"] > 0 else "▼▼"
            notify(f"{T['title']} · {T['assets'][f['asset']]} {arrow}", f"{label} · {f['title'][:110]} ({f['sources']} {T['src']})", st["sound"])
        if len(found) > 3:
            notify(T["title"], T["more"].format(n=len(found) - 3), False)
        _news_alert["last_run"] = int(now)
        _news_alert["last_error"] = "; ".join(f"{k}: {v}" for k, v in list(data["errors"].items())[:2]) or None
        return found
    finally:
        _news_alert["running"] = False
        _news_alert_lock.release()


def news_alert_status():
    st = news_alert_settings()
    return {**{k: v for k, v in st.items() if k != "since"}, "last_run": _news_alert["last_run"], "last_error": _news_alert["last_error"],
            "running": _news_alert["running"], "next_run": int(_news_alert["next_run"]) or None, "history": load_json("news_alerts.json", [])[:30]}


# ---------------------------------------------------------------- 服务信息 / 重启（改了代码后在网页上一键生效）

def autostart_status():
    if sys.platform == "darwin":
        return os.path.exists(os.path.expanduser("~/Library/LaunchAgents/com.quantstockgod.server.plist"))
    if sys.platform.startswith("win"):
        return os.path.exists(os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup\QuantStockGod.lnk"))
    return False


def code_version():
    """服务端代码和界面文件的最后修改时间：网页据此提示“需要重启 / 需要刷新”"""
    def newest(paths):
        return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)
    static = [os.path.join(dp, f) for dp, _, fs in os.walk(STATIC) for f in fs if f.endswith((".js", ".css", ".html")) and not f.startswith("._")]
    return {"started": int(STARTED), "server_mtime": int(newest([os.path.join(ROOT, "server.py")])), "static_mtime": int(newest(static)),
            "port": PORT, "platform": sys.platform, "autostart": autostart_status(),
            "log": os.path.expanduser("~/Library/Logs/QuantStockGod/server.log") if sys.platform == "darwin" and autostart_status() else os.path.join(DATA, "server.log")}


def restart_soon():
    """先把响应发出去，0.5 秒后用同样的参数重新执行自己（开机自启的服务也一样适用）"""
    def go():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Timer(0.5, go).start()


# ---------------------------------------------------------------- 数据源状态

def source_status():
    cfg = config()
    return {"yahoo": {"ok": _yahoo["ok"], "error": _yahoo["last_error"], "cooldown": _yahoo["cooldown"] > time.time()},
            "cnn": {"ok": False if _cnn["error"] else (True if load_json(cache_name("misc", "cnn_fng"), None) else None), "error": _cnn["error"]},
            "sec": {"ok": bool(cfg.get("sec_email"))}, "cftc": {"ok": True},
            "eia": {"key": bool(cfg.get("eia_key"))}, "fred": {"key": bool(cfg.get("fred_key"))},
            "keys": {k: bool(cfg.get(k)) for k in KEY_FIELDS}}


# ---------------------------------------------------------------- HTTP 服务

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    # 浏览器侧加固：禁止被其他网站嵌入（防点击劫持）、禁止内联脚本和外部资源（万一有注入也执行不了）、
    # 禁止 MIME 嗅探、不把本机地址作为 Referer 发给外部网站、其他网站不能把这里的 JSON 当资源引用
    SECURITY_HEADERS = {
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                   "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        for k, v in self.SECURITY_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def list_directory(self, path):  # 不列目录
        self.send_error(404, "Not found")
        return None

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):  # 出错时 args[0] 是 HTTPStatus 而不是请求行
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        try:
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except ValueError:  # 计算结果里偶尔有 NaN / inf：换成 null，浏览器才能解析
            body = json.dumps(finite(obj), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 1_000_000:
            raise ApiError("请求体太大")
        b = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        if not isinstance(b, dict):
            raise ApiError("请求参数格式不正确: not a JSON object")
        return b

    def route(self, method):
        url = urllib.parse.urlparse(self.path)
        # 只接受本机页面的请求：Host 必须是本机地址（防 DNS 重绑定，静态文件也一样）
        port = self.server.server_address[1]
        local = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in local:
            return self.send_json({"error": "forbidden"}, 403)
        if not url.path.startswith("/api/"):
            if method == "GET":
                return super().do_GET()
            return self.send_json({"error": "not found"}, 404)
        # 跨站页面带来的 Origin 一律拒绝；所有写操作还必须带自定义请求头 X-QS-Client 并且是 JSON——
        # 跨站页面要加自定义请求头必须先经过浏览器预检，而本服务不响应预检，所以伪造不了（双重防 CSRF）
        origin = self.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] not in local:
            return self.send_json({"error": "forbidden"}, 403)
        if method != "GET":
            if self.headers.get("X-QS-Client") != "1":
                return self.send_json({"error": "forbidden"}, 403)
            if int(self.headers.get("Content-Length") or 0) > 0 and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self.send_json({"error": "forbidden"}, 403)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            self.send_json(self.api(method, url.path, q))
        except ApiError as e:
            self.send_json({"error": str(e)}, 400)
        except (ValueError, TypeError, KeyError) as e:  # 请求体不是 JSON、数字字段填了文字等
            self.send_json({"error": f"请求参数格式不正确: {type(e).__name__}"}, 400)
        except Exception as e:  # noqa: BLE001 — 本地工具，把异常直接显示在页面上
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def api(self, method, path, q):
        if path == "/api/market":
            return market()
        if path == "/api/quote":
            return quote_summary(q.get("sym", ""))
        if path == "/api/detail":
            return detail(q.get("sym", ""))
        if path == "/api/ticker":
            out = []
            for s in ("^GSPC", "^HSI", "GC=F", "CL=F", "^VIX"):
                try:
                    x = quote_summary(s)
                    out.append({"sym": s, "name": x["name"], "price": x["price"], "chg1d": x["chg1d"]})
                except ApiError:
                    pass
            return out
        if path == "/api/status":
            return source_status()
        if path == "/api/version":
            return code_version()
        if path == "/api/restart" and method == "POST":
            restart_soon()
            return {"ok": True}

        if path == "/api/watchlist":
            with _store_lock:
                items = watchlist()
                if method == "POST":
                    b = self.body_json()
                    sym = (b.get("sym") or "").strip().upper()
                    if not sym:
                        raise ApiError("请输入代码")
                    if not re.match(r"^[A-Z0-9^=.\-]{1,20}$", sym):
                        raise ApiError(f"代码格式不正确: {sym[:20]}")
                    item = {"sym": sym, "label": str(b.get("label") or "").strip()[:40], "move_pct": num(b.get("move_pct"), 0, 100),
                            "vol_mult": num(b.get("vol_mult"), 0, 100), "rsi_alert": bool(b.get("rsi_alert", True)),
                            "hi52_alert": bool(b.get("hi52_alert", True)), "added": int(time.time())}
                    old = next((i for i in items if i["sym"] == sym), None)
                    if old:
                        old.update({k: item[k] for k in ("label", "move_pct", "vol_mult", "rsi_alert", "hi52_alert")})
                    else:
                        items.append(item)
                    save_json("watchlist.json", items)
                elif method == "DELETE":
                    items = [i for i in items if i["sym"] != q.get("sym")]
                    save_json("watchlist.json", items)
            if method == "POST":
                quote_summary(sym)  # 验证代码有效；无效时报错（条目仍保留，便于修改）
            return items
        if path == "/api/watchlist/refresh":
            return refresh_watchlist()

        if path == "/api/alerts":
            if method == "POST":
                b = self.body_json()
                with _store_lock:
                    cfg = load_json("config.json", {})
                    if "enabled" in b:
                        cfg["alert_enabled"] = bool(b["enabled"])
                        _alert["next_run"] = 0
                    if "interval" in b:
                        cfg["alert_interval"] = int(num(b["interval"], 1, 240, 15))
                        _alert["next_run"] = 0
                    if b.get("lang") in ALERT_TEXT:
                        cfg["alert_lang"] = b["lang"]
                    if "sound" in b:
                        cfg["alert_sound"] = bool(b["sound"])
                    save_json("config.json", cfg)
            return alert_status()
        if path == "/api/alerts/test" and method == "POST":
            st = alert_settings()
            T = ALERT_TEXT.get(st["lang"], ALERT_TEXT["en"])
            ok, err = notify(T["title"], T["test"], st["sound"])
            if not ok:
                raise ApiError(f"系统通知失败: {err or '未知错误'}")
            return {"ok": True}
        if path == "/api/alerts/run" and method == "POST":
            found = run_alerts()
            return {"found": found or [], "busy": found is None, **alert_status()}

        if path == "/api/insider":
            return insider_buys(q.get("ticker", ""), q.get("limit", 150))
        if path == "/api/13f":
            return all_13f()
        if path == "/api/managers":
            with _store_lock:
                ms = managers()
                if method == "POST":
                    b = self.body_json()
                    try:
                        cik = int(str(b.get("cik", "")).strip().lstrip("0") or 0)
                    except ValueError:
                        raise ApiError("CIK 必须是数字")
                    if not cik:
                        raise ApiError("请输入 CIK")
                    name = str(b.get("name") or "").strip()[:60] or f"CIK {cik}"
                    ms = [m for m in ms if m["cik"] != cik] + [{"cik": cik, "name": name}]
                    save_json("managers.json", ms)
                elif method == "DELETE":
                    ms = [m for m in ms if str(m["cik"]) != q.get("cik")]
                    save_json("managers.json", ms)
            return ms
        if path == "/api/cot":
            return cot()
        if path == "/api/eia":
            return eia()
        if path == "/api/southbound":
            return southbound()
        if path == "/api/macro":
            return macro()
        if path == "/api/news":
            return news()
        if path == "/api/technews":
            return tech_news()
        if path == "/api/news/accuracy":
            return news_accuracy()
        if path == "/api/news/alerts":
            if method == "POST":
                b = self.body_json()
                with _store_lock:
                    cfg = load_json("config.json", {})
                    if "enabled" in b:
                        on = bool(b["enabled"])
                        if on and not cfg.get("news_alert"):
                            cfg["news_alert_since"] = int(time.time() - 3 * 3600)  # 开启时把最近 3 小时的重大新闻也算进来
                            save_json("news_alert_seen.json", {})
                        cfg["news_alert"] = on
                        _news_alert["next_run"] = 0
                    if isinstance(b.get("assets"), list):
                        cfg["news_assets"] = [a for a in b["assets"] if a in NEWS_ASSETS]
                    if "min_src" in b:
                        cfg["news_min_src"] = int(num(b["min_src"], 1, 5, 2))
                    if b.get("lang") in NEWS_ALERT_TEXT:
                        cfg["alert_lang"] = b["lang"]
                    save_json("config.json", cfg)
            return news_alert_status()
        if path == "/api/news/alerts/run" and method == "POST":
            found = run_news_alerts()
            return {"found": found or [], "busy": found is None, **news_alert_status()}

        if path == "/api/config":
            if method == "POST":
                b = self.body_json()
                with _store_lock:
                    cfg = load_json("config.json", {})
                    for k in KEY_FIELDS:
                        if k in b:
                            v = str(b[k]).strip()[:200]
                            if k == "sec_email" and v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                                raise ApiError("邮箱格式不正确")
                            cfg[k] = v
                    save_json("config.json", cfg)
            cfg = config()
            return {k: bool(cfg.get(k)) for k in KEY_FIELDS}  # 只返回是否已配置，不回显内容
        raise ApiError(f"未知接口: {method} {path}")

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")


def prune_cache(days=30):
    """清理 30 天没更新过的缓存（换掉的自选、过期的新闻源等）；Form 4 / 13F 解析结果不会变，保留"""
    cutoff, removed = time.time() - days * 86400, 0
    for sub in ("yahoo", "news", "eia", "fred", "cot", "misc", "sec"):
        d = os.path.join(CACHE, sub)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            try:
                if f.startswith("._") or os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    return removed


def prewarm():
    """启动时在后台清理旧缓存、预取常用数据，打开网页时多半已经在缓存里"""
    try:
        prune_cache()
    except Exception:  # noqa: BLE001
        pass
    for fn in (market, refresh_watchlist, cot, eia, macro, southbound, news):
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


def main():
    os.makedirs(CACHE, exist_ok=True)
    # 无控制台运行（Windows 的 pythonw、开机自启）时 stdout / stderr 是 None，请求日志一写就报错：改写到 data/server.log
    if sys.stdout is None or sys.stderr is None:
        log = open(os.path.join(DATA, "server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=alert_loop, daemon=True).start()
    BG.submit(prewarm)
    print(f"量化股神已启动: http://{HOST}:{PORT}   （Ctrl+C 停止）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
