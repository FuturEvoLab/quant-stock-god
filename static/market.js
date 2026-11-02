// 量化股神 — 市场总览：恐惧与贪婪、指数 / 利率 / 美元、大宗商品、市场解读
// 数据来自 /api/market（服务端汇总 Yahoo Finance chart 接口与 CNN / 本地合成情绪指数）

const FNG_ZONES = [
  { max: 24, key: "xfear", text: "极度恐慌", color: "#ff3b6b" },
  { max: 44, key: "fear", text: "恐慌", color: "#ff9f1c" },
  { max: 55, key: "neutral", text: "中性", color: "#ffd23f" },
  { max: 74, key: "greed", text: "贪婪", color: "#9be15d" },
  { max: 100, key: "xgreed", text: "极度贪婪", color: "#22ffa6" },
];
const fngZone = (v) => FNG_ZONES.find((z) => v <= z.max);
const mk = { data: null, range: 30, at: 0 };
const MARKET_HOOKS = [];   // 其他模块（宏观 / EIA）跟着市场总览一起加载
const READING_HOOKS = [];  // 其他模块往“市场解读”里追加条目：f(add)
// 收益率 / 波动率指数这类“点位即百分比”的品种，变化用绝对值显示更直观
const ABS_UNIT = { "^TNX": "bp", "^VIX": "pt" };
const PARTS_TEXT = { momentum: "动量", volatility: "波动", safe_haven: "避险需求", junk: "垃圾债需求" };

async function loadMarket(force = false, retry = 0) {
  if (!force && mk.data && Date.now() - mk.at < 240000) return renderMarket();
  if (!retry) MARKET_HOOKS.forEach((f) => f(force));
  const btn = $("#mk-refresh");
  btn.disabled = true;
  if (!mk.data) $("#mk-indices").innerHTML = $("#mk-commods").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在获取行情…</p></div>`;
  try {
    mk.data = await api("/api/market");
    mk.at = Date.now();
    renderMarket();
    // 服务端先给了缓存、正在后台刷新：几秒后静默再取一次（最多 3 次）
    if (mk.data.refreshing && retry < 3) setTimeout(() => loadMarket(true, retry + 1), 4000);
  } catch (e) {
    $("#mk-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
  btn.disabled = false;
}

function renderMarket() {
  const d = mk.data;
  if (!d) return;
  renderHudFng();
  renderSources();
  const bad = Object.keys(d.errors || {});
  $("#mk-msg").innerHTML = (bad.length ? `<div>部分数据暂时不可用：${esc(bad.join(", "))}</div>` : "") +
    (d.stale ? `<div>Yahoo 暂时限流，部分品种显示的是本地缓存数据</div>` : "");
  $("#mk-upd").textContent = `更新于 ${fmtTime(mk.at / 1000).slice(11)}`;
  renderGauge(); renderReadings(); renderQuotes("#mk-indices", d.indices); renderQuotes("#mk-commods", d.commods); renderFngChart();
}

function renderHudFng() {
  const f = mk.data?.fng;
  if (!f) return;
  const z = fngZone(f.now), el = $("#hb-fng");
  el.style.setProperty("--fc", z.color);
  flashVal($("#hb-fng b"), String(f.now));
  $("#hb-fng i").textContent = z.text;
}
$("#hb-fng").addEventListener("click", () => switchTab("market"));

// 半圆仪表：五段颜色 + 指针
function renderGauge() {
  const f = mk.data.fng;
  if (!f) return ($("#mk-gauge").innerHTML = `<p class="muted">暂无数据</p>`);
  $("#mk-fng-src").textContent = f.source === "cnn" ? "CNN（非官方）" : "本地合成指数";
  $("#mk-fng-src").title = f.source === "cnn" ? "" : "CNN 接口不可用，改用免费行情计算的同类指数";
  const v = f.now, z = fngZone(v), s = [...f.series].reverse(); // s[0] 为最新
  const cx = 120, cy = 118, R = 96;
  const pt = (val, r) => { const a = Math.PI * (1 - val / 100); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  let lo = 0;
  const arcs = FNG_ZONES.map((zz) => {
    const [x1, y1] = pt(lo + 0.6, R), [x2, y2] = pt(zz.max - 0.6, R);
    lo = zz.max;
    return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)}A${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${zz.color}" class="${zz.key === z.key ? "cur" : ""}"/>`;
  }).join("");
  const ticks = Array.from({ length: 21 }, (_, i) => {
    const [a, b] = [pt(i * 5, R - 14), pt(i * 5, R - (i % 5 ? 18 : 22))];
    return `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>`;
  }).join("");
  const [nx, ny] = pt(v, R - 30);
  const prev = +($("#mk-gauge").dataset.v || 50);
  $("#mk-gauge").dataset.v = v;
  $("#mk-gauge").style.setProperty("--fc", z.color);
  $("#mk-gauge").innerHTML = `<svg viewBox="0 0 240 196" aria-hidden="true">
      <g class="arcs">${arcs}</g><g class="ticks">${ticks}</g>
      <g class="needle" style="--from:${(prev - v) * 1.8}deg"><line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"/><circle cx="${cx}" cy="${cy}" r="6"/></g>
      <text x="22" y="140" class="lbl">0</text><text x="218" y="140" class="lbl" text-anchor="end">100</text>
    </svg>
    <div class="mk-gv"><b>${v}</b><span>${z.text}</span></div>`;
  const cmp = [["昨天", s[1]], ["1 周前", s[5]], ["1 个月前", s[21]]].filter(([, x]) => x);
  $("#mk-cmp").innerHTML = cmp.map(([k, x]) => {
    const zz = fngZone(x.v), dv = v - x.v;
    return `<div><span>${k}</span><b style="color:${zz.color}">${x.v}</b><small>${zz.text}</small><em class="${updn(dv)}">${dv >= 0 ? "▲" : "▼"}${Math.abs(dv)}</em></div>`;
  }).join("");
  $("#mk-parts").innerHTML = f.parts ? Object.entries(f.parts).map(([k, p]) =>
    `<div class="q-part"><span>${PARTS_TEXT[k] || k}</span><div class="q-bar"><i style="width:${p}%;background:${fngZone(p).color}"></i></div><b>${p}</b></div>`).join("") : "";
}

function quoteByS(sym) {
  const d = mk.data;
  return [...(d.indices || []), ...(d.commods || [])].find((x) => x.sym === sym);
}
function chgCell(q, key) {
  const unit = ABS_UNIT[q.sym];
  if (unit === "bp") { const a = q["abs" + key]; return a == null ? "—" : `${a >= 0 ? "+" : ""}${Math.round(a * 100)} bp`; }
  if (unit === "pt") { const a = q["abs" + key]; return a == null ? "—" : `${a >= 0 ? "+" : ""}${a.toFixed(2)}`; }
  return pct(q["chg" + key]);
}

function renderQuotes(sel, list) {
  const IN = getVar("--in"), OUT = getVar("--out");
  $(sel).innerHTML = (list || []).map((q) => {
    const sign = (v) => (ABS_UNIT[q.sym] === "pt" || q.sym === "^VIX" ? -1 : 1) * (v ?? 0); // VIX 上涨对市场是负面，配色反过来
    const val = q.sym === "^TNX" ? `${q.price.toFixed(3)}%` : fmtPx(q.price);
    return `<div class="q-card ${q.stale ? "stale" : ""}" data-sym="${esc(q.sym)}" title="点击查看详情">
      <div class="q-h"><b>${esc(q.name)}</b><span class="mono muted" translate="no">${esc(q.sym)}</span></div>
      <div class="q-v"><span class="mono">${val}</span><em class="mk-chg ${updn(sign(q.chg1d))}">${chgCell(q, "1d")}</em></div>
      ${sparkSvg(q.spark, sign(q.chg1m) >= 0 ? IN : OUT, 160, 36)}
      <div class="q-chg"><span>1D <b class="${updn(sign(q.chg1d))}">${chgCell(q, "1d")}</b></span><span>1W <b class="${updn(sign(q.chg1w))}">${chgCell(q, "1w")}</b></span><span>1M <b class="${updn(sign(q.chg1m))}">${chgCell(q, "1m")}</b></span></div>
    </div>`;
  }).join("") || `<p class="muted">暂无数据</p>`;
}

// 市场解读：只做客观描述，不给方向判断
function renderReadings() {
  const d = mk.data, out = [];
  // tone 决定颜色（对市场偏正面 / 偏负面），dir 决定箭头（数值本身的方向）；不传 dir 时箭头跟 tone 走
  const add = (tone, title, value, text, dir) => out.push({ tone, title, value, text, dir });
  const q = (s) => quoteByS(s);
  if (d.fng) {
    const v = d.fng.now;
    add(v <= 44 ? "bear" : v >= 56 ? "bull" : "flat", "恐惧与贪婪", `${v}`,
      v <= 24 ? "情绪处于极度恐慌区间" : v <= 44 ? "情绪偏向恐慌" : v <= 55 ? "情绪中性" : v <= 74 ? "情绪偏向贪婪" : "情绪处于极度贪婪区间");
    const w = [...d.fng.series].reverse()[5];
    if (w && Math.abs(v - w.v) >= 15) add(v < w.v ? "bear" : "bull", "情绪变化", `${v - w.v > 0 ? "+" : ""}${v - w.v} / 1W`, v < w.v ? "一周内情绪明显转冷" : "一周内情绪明显升温");
  }
  const vix = q("^VIX");
  if (vix) add(vix.price >= 25 ? "bear" : vix.price <= 15 ? "bull" : "flat", "VIX 波动率", vix.price.toFixed(2),
    vix.price >= 30 ? "波动率处于高位，市场避险情绪强" : vix.price >= 25 ? "波动率偏高" : vix.price <= 15 ? "波动率处于低位，市场较平静" : "波动率处于常规水平");
  const spx = q("^GSPC");
  if (spx?.chg1m != null) add(spx.chg1m <= -5 ? "bear" : spx.chg1m >= 5 ? "bull" : "flat", "S&P 500 · 1M", pct(spx.chg1m),
    spx.chg1m <= -5 ? "美股一个月内明显回落" : spx.chg1m >= 5 ? "美股一个月内明显上涨" : "美股一个月内波动不大");
  const tnx = q("^TNX");
  if (tnx?.abs1m != null) {
    const bp = Math.round(tnx.abs1m * 100);
    add(Math.abs(bp) >= 25 ? (bp > 0 ? "bear" : "bull") : "flat", "美债 10Y · 1M", `${bp >= 0 ? "+" : ""}${bp} bp`,
      bp >= 25 ? "长端收益率一个月内明显上行" : bp <= -25 ? "长端收益率一个月内明显下行" : "长端收益率一个月内变化不大", Math.abs(bp) >= 25 ? (bp > 0 ? "up" : "down") : undefined);
  }
  const dxy = q("DX-Y.NYB");
  if (dxy?.chg1m != null) add("flat", "美元指数 · 1M", pct(dxy.chg1m), dxy.chg1m >= 2 ? "美元一个月内明显走强" : dxy.chg1m <= -2 ? "美元一个月内明显走弱" : "美元一个月内基本持平");
  const hsi = q("^HSI");
  if (hsi?.chg1m != null && spx?.chg1m != null && Math.abs(hsi.chg1m - spx.chg1m) >= 5)
    add("flat", "港股 vs 美股 · 1M", `${pct(hsi.chg1m, 1)} / ${pct(spx.chg1m, 1)}`, hsi.chg1m > spx.chg1m ? "港股一个月内明显跑赢美股" : "港股一个月内明显跑输美股");
  const gold = q("GC=F");
  if (gold?.chg1m != null) add(gold.chg1m >= 5 ? "bull" : gold.chg1m <= -5 ? "bear" : "flat", "黄金 · 1M", pct(gold.chg1m),
    gold.chg1m >= 5 ? "金价一个月内明显上涨" : gold.chg1m <= -5 ? "金价一个月内明显回落" : "金价一个月内波动不大");
  const oil = q("CL=F");
  if (oil?.chg1m != null) add(oil.chg1m >= 8 ? "bull" : oil.chg1m <= -8 ? "bear" : "flat", "WTI 原油 · 1M", pct(oil.chg1m),
    oil.chg1m >= 8 ? "油价一个月内明显上涨" : oil.chg1m <= -8 ? "油价一个月内明显下跌" : "油价一个月内波动不大");
  const cu = q("HG=F");
  if (cu?.chg1m != null && gold?.chg1m != null) {
    const r = cu.chg1m - gold.chg1m;
    if (Math.abs(r) >= 4) add(r > 0 ? "bull" : "bear", "铜金比 · 1M", pct(r, 1), r > 0 ? "铜相对黄金走强（常被视为增长预期改善）" : "铜相对黄金走弱（常被视为增长预期转弱）");
  }
  READING_HOOKS.forEach((f) => f(add));
  const icon = { bull: "▲", bear: "▼", flat: "■", up: "▲", down: "▼" };
  $("#mk-read").innerHTML = out.map((r) => `<li class="${r.tone}"><i>${icon[r.dir || r.tone]}</i><div><div class="t"><span>${r.title}</span><b>${esc(r.value)}</b></div><p>${r.text}</p></div></li>`).join("")
    || `<li class="flat"><i>■</i><div><p>暂无数据</p></div></li>`;
}

// 情绪走势：背景按五个区间着色，折线 + 悬停读数
function renderFngChart() {
  const box = $("#mk-chart"), all = mk.data.fng?.series || [];
  const f = all.slice(-mk.range);
  if (f.length < 2) return (box.innerHTML = `<p class="muted">暂无数据</p>`);
  const W = 720, H = 200, L = 30, R = 10, T = 10, B = 22;
  const x = (i) => L + (i / (f.length - 1)) * (W - L - R), y = (v) => T + (1 - v / 100) * (H - T - B);
  let lo = 0;
  const bands = FNG_ZONES.map((z) => { const r = `<rect x="${L}" y="${y(z.max)}" width="${W - L - R}" height="${y(lo) - y(z.max)}" fill="${z.color}" opacity=".06"/>`; lo = z.max; return r; }).join("");
  const grid = [0, 25, 50, 75, 100].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${v}</text>`).join("");
  const line = f.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join("");
  const dots = f.length <= 90 ? f.map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${i === f.length - 1 ? 4 : 2}" fill="${fngZone(p.v).color}" ${i === f.length - 1 ? 'class="last"' : ""}/>`).join("") : "";
  const dates = [0, Math.floor((f.length - 1) / 2), f.length - 1].map((i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === f.length - 1 ? "end" : "middle"}">${fmtTime(f[i].ts, false).slice(2)}</text>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bands}${grid}
    <path d="${line}L${x(f.length - 1)} ${y(0)}L${x(0)} ${y(0)}Z" class="area"/><path d="${line}" class="line"/>${dots}${dates}
    <line class="cursor" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/></svg><div class="mk-tip" hidden></div>`;
  const svg = box.querySelector("svg"), tip = box.querySelector(".mk-tip"), cur = box.querySelector(".cursor");
  svg.onmousemove = (e) => {
    const r = svg.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(f.length - 1, Math.round(((px - L) / (W - L - R)) * (f.length - 1))));
    const p = f[i], z = fngZone(p.v);
    cur.setAttribute("x1", x(i)); cur.setAttribute("x2", x(i)); cur.setAttribute("visibility", "visible");
    tip.innerHTML = `${fmtTime(p.ts, false)} · <b style="color:${z.color}">${p.v}</b> <span>${z.text}</span>`;
    tip.hidden = false;
    tip.style.left = `${Math.min(r.width - 150, Math.max(0, (x(i) / W) * r.width - 70))}px`;
  };
  svg.onmouseleave = () => { tip.hidden = true; cur.setAttribute("visibility", "hidden"); };
}
$("#mk-range").addEventListener("click", (e) => {
  const b = e.target.closest("[data-d]");
  if (!b) return;
  mk.range = +b.dataset.d;
  $$("#mk-range button").forEach((x) => x.classList.toggle("on", x === b));
  renderFngChart();
});

$("#mk-refresh").addEventListener("click", () => loadMarket(true));
TAB_LOADERS.market = () => loadMarket();
RERENDER.push(() => mk.data && renderMarket());
setInterval(() => { if (!document.hidden) loadMarket(true); }, 300000);
