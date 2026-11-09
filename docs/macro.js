// 量化股神 — 宏观利率（FRED；没填 Key 时用 Yahoo 美债收益率）与 EIA 库存周报
// 宏观卡片放在市场总览，EIA 放在商品持仓页；两者都往“市场解读”里追加客观描述

const mc = { data: null, eia: null, eiaAt: 0 };
const PT_KEYS = new Set(["cpi", "unrate"]); // 这两项变化用百分点显示，其余利率类用基点

function chgText(key, v) {
  if (v == null) return "—";
  return PT_KEYS.has(key) ? `${v >= 0 ? "+" : ""}${v.toFixed(2)} pt` : `${v >= 0 ? "+" : ""}${Math.round(v * 100)} bp`;
}
const arrow = (v) => (v == null || Math.abs(v) < 1e-9 ? "" : v > 0 ? "▲" : "▼");

async function loadMacro() {
  try {
    mc.data = await api("/api/macro");
    renderMacro();
  } catch (e) { $("#mc-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
async function loadEia(force = false) {
  if (!force && mc.eia && Date.now() - mc.eiaAt < 3600000) return renderEia();
  if (!mc.eia) $("#eia-grid").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在读取 EIA 库存周报…</p></div>`;
  try {
    mc.eia = await api("/api/eia");
    mc.eiaAt = Date.now();
    renderEia();
  } catch (e) { $("#eia-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}

// ---------------------------------------------------------------- 宏观

function curveSvg(curve) {
  if (curve.length < 2) return `<p class="muted">暂无数据</p>`;
  const W = 300, H = 170, L = 34, R = 12, T = 14, B = 26;
  const vals = curve.flatMap((p) => [p.now, p.prev]).filter((v) => v != null);
  const lo = Math.floor(Math.min(...vals) * 4) / 4 - 0.1, hi = Math.ceil(Math.max(...vals) * 4) / 4 + 0.1;
  const x = (i) => L + (i / (curve.length - 1)) * (W - L - R), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = (k) => curve.map((p, i) => (p[k] == null ? "" : `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[k]).toFixed(1)}`)).join("");
  const grid = [lo, (lo + hi) / 2, hi].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 5}" y="${y(v) + 3}" text-anchor="end">${v.toFixed(2)}</text>`).join("");
  const labels = curve.map((p, i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${p.label}</text><circle cx="${x(i)}" cy="${y(p.now)}" r="3.2" class="pt"/><text x="${x(i)}" y="${y(p.now) - 8}" text-anchor="middle" class="v">${p.now.toFixed(2)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}">${grid}<path d="${path("prev")}" class="prev"/><path d="${path("now")}" class="now"/>${labels}</svg>
    <div class="mc-legend"><span><i class="now"></i>现在</span><span><i class="prev"></i>1 个月前</span></div>`;
}

function renderMacro() {
  const d = mc.data;
  if (!d) return;
  $("#mc-src").textContent = d.source === "fred" ? "FRED" : "Yahoo Finance";
  $("#mc-msg").innerHTML = (d.source !== "fred" ? `<div>未填写 FRED Key：只显示 Yahoo 的美债收益率。到设置页填写免费的 FRED Key 后，会增加 2 年期、联邦基金利率、10 年通胀预期、高收益债利差、CPI 同比和失业率。</div>` : "") +
    (Object.keys(d.errors || {}).length ? `<div>部分数据暂时不可用：${esc(Object.keys(d.errors).join(", "))}</div>` : "");
  const sp = d.spreads || {};
  $("#mc-spreads").innerHTML = [["10Y−3M", sp["10y3m"]], ["10Y−2Y", sp["10y2y"]]].filter(([, v]) => v != null)
    .map(([k, v]) => `<span class="badge q-act" style="--c:${v < 0 ? getVar("--out") : getVar("--in")}" translate="no">${k} ${v >= 0 ? "+" : ""}${v.toFixed(2)}</span>`).join(" ");
  $("#mc-curve").innerHTML = curveSvg(d.curve || []);
  $("#mc-grid").innerHTML = (d.items || []).map((m) => `<div class="q-card">
      <div class="q-h"><b>${esc(m.name)}</b><span class="mono muted">${esc(m.date)}</span></div>
      <div class="q-v"><span class="mono">${m.value.toFixed(2)}%</span><em class="mono muted">${arrow(m.chg1m)} ${chgText(m.key, m.chg1m)}</em></div>
      ${sparkSvg(m.spark, getVar("--accent"), 160, 30)}
      <div class="q-chg"><span>1M <b>${chgText(m.key, m.chg1m)}</b></span><span>1Y <b>${chgText(m.key, m.chg1y)}</b></span></div>
    </div>`).join("");
}

// ---------------------------------------------------------------- EIA

function eiaChart(series) {
  const W = 360, H = 110, T = 6, B = 16;
  const all = series.flatMap((p) => [p.v, p.lo, p.hi]).filter((v) => v != null);
  const min = Math.min(...all), max = Math.max(...all), rng = max - min || 1;
  const x = (i) => (i / (series.length - 1)) * W, y = (v) => T + (1 - (v - min) / rng) * (H - T - B);
  const line = (k) => series.map((p, i) => (p[k] == null ? "" : `${i && series[i - 1][k] != null ? "L" : "M"}${x(i).toFixed(1)} ${y(p[k]).toFixed(1)}`)).join("");
  const band = series.every((p) => p.lo != null)
    ? `<path d="${series.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.hi).toFixed(1)}`).join("")}${series.map((p, i) => `L${x(series.length - 1 - i).toFixed(1)} ${y(series[series.length - 1 - i].lo).toFixed(1)}`).join("")}Z" class="band"/>` : "";
  const months = [];
  series.forEach((p, i) => { if (i && p.d.slice(5, 7) !== series[i - 1].d.slice(5, 7) && ["01", "04", "07", "10"].includes(p.d.slice(5, 7))) months.push(`<text x="${x(i) + 2}" y="${H - 4}">${esc(p.d.slice(2, 7))}</text>`); });
  return `<svg class="cot-chart eia-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${band}${months.join("")}
    <path d="${line("avg")}" class="avg" vector-effect="non-scaling-stroke"/>
    <path d="${line("v")}" fill="none" stroke="var(--accent)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(series.length - 1)}" cy="${y(series[series.length - 1].v)}" r="3" fill="var(--accent)" class="last"/></svg>`;
}

function renderEia() {
  const d = mc.eia;
  if (!d) return;
  const bad = Object.keys(d.errors || {});
  $("#eia-msg").innerHTML = bad.length ? `<div>部分品种获取失败：${esc(Object.values(d.errors)[0])}</div>` : "";
  $("#eia-src").textContent = d.demo ? "公共 DEMO_KEY" : "EIA Key";
  $("#eia-src").title = d.demo ? "未填写 EIA Key，使用公共演示 Key（每小时约 10 次）；数据缓存 12 小时" : "";
  if (d.series[0]) $("#eia-upd").textContent = `数据截至 ${d.series[0].date}`;
  const f = (v) => (v == null ? "—" : fmtNum(v, 1));
  const sgn = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${fmtNum(v, 1)}`);
  $("#eia-grid").innerHTML = d.series.map((m) => {
    const vs = m.vs5, color = vs == null ? getVar("--accent") : vs >= 5 ? getVar("--q-reduce") : vs <= -5 ? getVar("--q-new") : getVar("--accent");
    const pos = m.lo5 != null && m.hi5 > m.lo5 ? Math.max(0, Math.min(100, ((m.value - m.lo5) / (m.hi5 - m.lo5)) * 100)) : null;
    return `<div class="card cot-card eia-card" style="--pc:${color}">
      <div class="card-head"><h3>${esc(m.name)}</h3><span class="spacer"></span><span class="badge q-act" style="--c:${color}">${vs == null ? "—" : vs >= 5 ? "高于往年同期" : vs <= -5 ? "低于往年同期" : "接近往年同期"}</span></div>
      <div class="cot-top">
        <div class="cot-pct"><b>${f(m.value)}</b><small translate="no">${esc(m.unit)}</small></div>
        <dl class="kv">
          <dt>周变化</dt><dd><b class="${updn(m.chg1w)}">${sgn(m.chg1w)}</b></dd>
          <dt>同比</dt><dd><span class="${updn(m.chg_yoy)}">${sgn(m.chg_yoy)}</span></dd>
          <dt>5 年同期均值</dt><dd>${f(m.avg5)}</dd>
          <dt>相对 5 年均值</dt><dd><b>${vs == null ? "—" : pct(vs, 1)}</b></dd>
        </dl>
      </div>
      ${pos == null ? "" : `<div class="cot-bar eia-bar" title="过去 5 年同一周的最低 → 最高"><i style="left:${pos.toFixed(1)}%"></i></div>
      <div class="cot-rng"><span>${f(m.lo5)}</span><span>5 年同期区间</span><span>${f(m.hi5)}</span></div>`}
      ${eiaChart(m.series)}
      <div class="mc-legend"><span><i class="now"></i>近 1 年</span><span><i class="prev"></i>5 年同期均值</span><span><i class="band"></i>5 年同期区间</span></div>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------- 市场解读

READING_HOOKS.push((add) => {
  const sp = mc.data?.spreads || {}, by = Object.fromEntries((mc.data?.items || []).map((m) => [m.key, m]));
  const s = sp["10y3m"];
  if (s != null) add(s < 0 ? "bear" : "flat", "美债利差 10Y−3M", `${s >= 0 ? "+" : ""}${s.toFixed(2)} pt`,
    s < 0 ? "10 年期收益率低于 3 个月期，收益率曲线倒挂" : s < 0.5 ? "收益率曲线较平" : "收益率曲线正常向上倾斜");
  const hy = by.hy;
  if (hy?.chg1m != null && Math.abs(hy.chg1m) >= 0.5) add(hy.chg1m > 0 ? "bear" : "bull", "高收益债利差 · 1M", chgText("hy", hy.chg1m),
    hy.chg1m > 0 ? "高收益债利差一个月内明显走阔，信用风险偏好下降" : "高收益债利差一个月内明显收窄，信用风险偏好上升", hy.chg1m > 0 ? "up" : "down");
  if (by.cpi) add("flat", "CPI 同比", `${by.cpi.value.toFixed(1)}%`, by.cpi.chg1m > 0 ? "通胀同比较上月上升" : by.cpi.chg1m < 0 ? "通胀同比较上月回落" : "通胀同比与上月持平");
  for (const m of mc.eia?.series || []) {
    if (!["crude", "natgas"].includes(m.key) || m.vs5 == null || Math.abs(m.vs5) < 5) continue;
    add("flat", m.key === "crude" ? "EIA 原油库存" : "EIA 天然气库存", pct(m.vs5, 1),
      m.key === "crude" ? (m.vs5 > 0 ? "美国原油库存高于过去 5 年同期均值" : "美国原油库存低于过去 5 年同期均值")
        : (m.vs5 > 0 ? "美国天然气库存高于过去 5 年同期均值" : "美国天然气库存低于过去 5 年同期均值"), m.vs5 > 0 ? "up" : "down");
  }
});

MARKET_HOOKS.push(async (force) => {
  await Promise.all([loadMacro(), loadEia(force)]);
  if (mk.data) renderReadings();
});
const _cotLoader = TAB_LOADERS.cot;
TAB_LOADERS.cot = () => { _cotLoader?.(); loadEia(); };
$("#cot-refresh").addEventListener("click", () => loadEia(true));
RERENDER.push(() => { renderMacro(); renderEia(); });
