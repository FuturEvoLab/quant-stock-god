// 量化股神 — 品种详情：点击自选列表的行或市场总览的卡片打开。近一年走势 + 均线 + 成交量 + RSI，以及技术面要点（只做客观描述）
// 数据来自 /api/detail（服务端用 Yahoo 2 年日线计算）

const dt = { sym: null, data: null, range: 252 };
const DT_RANGES = [[63, "3M"], [126, "6M"], [252, "1Y"]];
const MA_COLORS = { ma20: "--gold", ma50: "--q-new", ma200: "--between" };

function openDetail(sym) {
  if (!sym) return;
  dt.sym = sym; dt.data = null;
  const el = $("#detail");
  el.hidden = false;
  document.body.classList.add("dt-open");
  $("#dt-title").innerHTML = `<b translate="no">${esc(sym)}</b>`;
  $("#dt-body").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在获取行情…</p></div>`;
  api(`/api/detail?sym=${encodeURIComponent(sym)}`).then((d) => {
    if (dt.sym !== sym) return;
    dt.data = d;
    renderDetail();
  }).catch((e) => { if (dt.sym === sym) $("#dt-body").innerHTML = `<div class="err">${esc(e.message)}</div>`; });
}
function closeDetail() {
  $("#detail").hidden = true;
  document.body.classList.remove("dt-open");
  dt.sym = dt.data = null;
}
$("#detail").addEventListener("click", (e) => {
  if (e.target.id === "detail" || e.target.closest("[data-dt-close]")) closeDetail();
  const act = e.target.closest("[data-dt-act]");
  if (act && dt.sym) {  // 从详情直接跳到相关页面并把代码填好
    const sym = dt.sym;
    closeDetail();
    if (act.dataset.dtAct === "quant") { switchTab("quant"); $("#ql-sym").value = sym; runQuant(); }
    else if (act.dataset.dtAct === "watch") { switchTab("watch"); $("#w-sym").value = sym; $("#w-sym").focus(); $("#watch-form").scrollIntoView({ block: "center" }); }
    else if (act.dataset.dtAct === "portfolio") { switchTab("portfolio"); $("#pf-sym").value = sym; $("#pf-shares").focus(); }
    return;
  }
  const r = e.target.closest("[data-dt-range]");
  if (r) { dt.range = +r.dataset.dtRange; renderDetail(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#detail").hidden) closeDetail(); });

function renderDetail() {
  const d = dt.data;
  if (!d) return;
  const unit = ABS_UNIT[d.sym];
  const px = d.sym === "^TNX" ? `${d.price.toFixed(3)}%` : fmtPx(d.price);
  $("#dt-title").innerHTML = `<b>${esc(d.name)}</b> <span class="mono muted" translate="no">${esc(d.sym)}</span>
    <span class="dt-px mono">${px} <small class="muted">${esc(d.currency || "")}</small></span>
    <em class="mk-chg ${updn(d.chg1d)}">${unit ? chgCell(d, "1d") : pct(d.chg1d)}</em>${d.stale ? ` <span class="badge">缓存</span>` : ""}`;
  const stat = (k, v, cls = "") => `<div class="dt-stat"><span>${k}</span><b class="mono ${cls}">${v}</b></div>`;
  const vsMa = (ma) => (ma ? (d.price / ma - 1) * 100 : null);
  $("#dt-body").innerHTML = `
    <div class="dt-tools">${DT_RANGES.map(([n, l]) => `<button type="button" class="chip-btn ${dt.range === n ? "on" : ""}" data-dt-range="${n}">${l}</button>`).join("")}
      <span class="dt-legend"><i style="--c:var(--accent)"></i>收盘价${Object.entries(MA_COLORS).map(([k, c]) => `<i style="--c:var(${c})"></i>${k.slice(2)} 日均线`).join("")}</span></div>
    <div id="dt-chart" class="dt-chart"></div>
    <div class="dt-grid">
      ${stat("1W", pct(d.chg1w), updn(d.chg1w))}${stat("1M", pct(d.chg1m), updn(d.chg1m))}${stat("3M", pct(d.chg3m), updn(d.chg3m))}
      ${stat("6M", pct(d.chg6m), updn(d.chg6m))}${stat("1Y", pct(d.chg1y), updn(d.chg1y))}${stat("YTD", pct(d.ytd), updn(d.ytd))}
      ${stat("RSI(14)", d.rsi14 == null ? "—" : d.rsi14.toFixed(1), d.rsi14 >= 70 ? "down" : d.rsi14 <= 30 ? "up" : "")}
      ${stat("52 周区间位置", d.pos52 == null ? "—" : `${d.pos52.toFixed(0)}%`)}
      ${stat("52 周高点", `${fmtPx(d.hi52)} <small>(${pct((d.price / d.hi52 - 1) * 100, 1)})</small>`)}
      ${stat("52 周低点", `${fmtPx(d.lo52)} <small>(${pct((d.price / d.lo52 - 1) * 100, 1)})</small>`)}
      ${stat("距 20 日均线", pct(vsMa(d.ma20), 1), updn(vsMa(d.ma20)))}${stat("距 50 日均线", pct(vsMa(d.ma50), 1), updn(vsMa(d.ma50)))}
      ${stat("距 200 日均线", pct(vsMa(d.ma200), 1), updn(vsMa(d.ma200)))}
      ${stat("20 日波动率（年化）", d.vol20 == null ? "—" : `${d.vol20.toFixed(1)}%`)}${stat("1 年波动率（年化）", d.vol1y == null ? "—" : `${d.vol1y.toFixed(1)}%`)}
      ${stat("1 年最大回撤", pct(d.mdd1y, 1), "down")}
      ${stat("成交量 / 20 日均量", d.vol_ratio == null ? "—" : `×${d.vol_ratio.toFixed(2)}`)}
    </div>
    ${d.vol_projected ? `<p class="muted dt-note">盘中成交量已按交易时段进度折算成全天预估量</p>` : ""}
    <div class="section-title">技术面要点</div>
    <ul class="mk-list dt-points">${detailPoints(d).map(([tone, text, val]) => `<li class="${tone}"><i>${{ bull: "▲", bear: "▼", flat: "■" }[tone]}</i><div><div class="t"><span>${text}</span><b>${val}</b></div></div></li>`).join("")}</ul>
    <p class="muted dt-note">按日收盘价计算，只是客观描述，不构成投资建议。</p>`;
  drawDetailChart();
}

// 客观描述：均线位置、均线排列、RSI 区间、52 周区间、波动率高低
function detailPoints(d) {
  const out = [];
  if (d.ma200) {
    const x = (d.price / d.ma200 - 1) * 100;
    out.push([x >= 0 ? "bull" : "bear", x >= 0 ? "价格位于 200 日均线上方" : "价格位于 200 日均线下方", pct(x, 1)]);
  }
  if (d.ma50 && d.ma200) out.push(d.ma50 >= d.ma200 ? ["bull", "50 日均线在 200 日均线上方", ""] : ["bear", "50 日均线在 200 日均线下方", ""]);
  if (d.rsi14 != null) {
    const r = d.rsi14;
    out.push(r >= 70 ? ["bear", "RSI 处于超买区间（≥70）", r.toFixed(1)] : r <= 30 ? ["bull", "RSI 处于超卖区间（≤30）", r.toFixed(1)] : ["flat", "RSI 处于中性区间", r.toFixed(1)]);
  }
  if (d.pos52 != null) {
    if (d.pos52 >= 95) out.push(["bull", "接近 52 周高点", pct((d.price / d.hi52 - 1) * 100, 1)]);
    else if (d.pos52 <= 5) out.push(["bear", "接近 52 周低点", pct((d.price / d.lo52 - 1) * 100, 1)]);
  }
  if (d.vol20 && d.vol1y) {
    const r = d.vol20 / d.vol1y;
    if (r >= 1.3) out.push(["bear", "近期波动明显高于一年平均", `×${r.toFixed(2)}`]);
    else if (r <= 0.7) out.push(["flat", "近期波动明显低于一年平均", `×${r.toFixed(2)}`]);
  }
  if (d.vol_ratio != null && d.vol_ratio >= 2) out.push(["flat", "成交量明显高于 20 日均量", `×${d.vol_ratio.toFixed(2)}`]);
  return out;
}

function drawDetailChart() {
  const d = dt.data, box = $("#dt-chart");
  if (!d || !box) return;
  const S = d.series, n = Math.min(dt.range, S.close.length), k0 = S.close.length - n;
  const cut = (a) => (a || []).slice(k0);
  const close = cut(S.close), vol = cut(S.volume), ts = cut(S.ts), rsiS = cut(S.rsi);
  const mas = Object.fromEntries(Object.keys(MA_COLORS).map((m) => [m, cut(S[m])]));
  const W = 760, PH = 230, VH = 46, RH = 70, G = 10, L = 6, R = 54;
  const H = PH + G + VH + G + RH + 18;
  const all = [...close, ...Object.values(mas).flat().filter((x) => x != null)];
  const lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.06 || 1;
  const x = (i) => L + (i / Math.max(1, n - 1)) * (W - L - R);
  const y = (v) => 6 + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (PH - 12);
  const path = (arr, fy) => arr.map((v, i) => (v == null ? null : [x(i), fy(v)])).reduce((s, p, i, a) => (p ? s + `${s && a[i - 1] ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}` : s), "");
  const vmax = Math.max(...vol, 1), vy0 = PH + G;
  const ry0 = PH + G + VH + G, ry = (v) => ry0 + (1 - v / 100) * RH;
  const bw = Math.max(1, (W - L - R) / n - 1);
  const ticks = Array.from({ length: 5 }, (_, i) => lo - pad + ((hi - lo + 2 * pad) * (i + 0.5)) / 5);
  const months = [];
  ts.forEach((t, i) => { const m = new Date(t * 1000).getMonth(); if (i && m !== new Date(ts[i - 1] * 1000).getMonth()) months.push([i, t]); });
  const step = Math.ceil(months.length / 8);
  const ACC = getVar("--accent"), IN = getVar("--in"), OUT = getVar("--out");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="dt-svg">
    <g class="dt-grid-l">${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text x="${W - R + 6}" y="${(y(v) + 3).toFixed(1)}">${fmtPx(v)}</text>`).join("")}
      ${[30, 70].map((v) => `<line class="rsi-band" x1="${L}" x2="${W - R}" y1="${ry(v)}" y2="${ry(v)}"/><text x="${W - R + 6}" y="${ry(v) + 3}">${v}</text>`).join("")}
      ${months.filter((_, j) => j % step === 0).map(([i, t]) => { const dd = new Date(t * 1000); return `<text x="${x(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">${dd.getFullYear() % 100}/${dd.getMonth() + 1}</text>`; }).join("")}</g>
    <path d="${path(close, y)}L${x(n - 1).toFixed(1)} ${PH}L${x(0).toFixed(1)} ${PH}Z" fill="${ACC}" opacity=".07"/>
    ${Object.entries(mas).map(([m, a]) => `<path d="${path(a, y)}" fill="none" stroke="${getVar(MA_COLORS[m])}" stroke-width="1.1" opacity=".85" vector-effect="non-scaling-stroke"/>`).join("")}
    <path d="${path(close, y)}" fill="none" stroke="${ACC}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
    <g>${vol.map((v, i) => { const h = (v / vmax) * VH; return `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${(vy0 + VH - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${i && close[i] < close[i - 1] ? OUT : IN}" opacity=".45"/>`; }).join("")}</g>
    <text class="dt-lbl" x="${L + 2}" y="${vy0 + 9}">VOL</text>
    <path d="${path(rsiS, ry)}" fill="none" stroke="${getVar("--gold")}" stroke-width="1.2" vector-effect="non-scaling-stroke"/>
    <text class="dt-lbl" x="${L + 2}" y="${ry0 + 9}">RSI 14</text>
    <g class="dt-hover" hidden><line class="dt-cross" y1="0" y2="${H - 16}"/><circle r="3.5" fill="${ACC}"/></g>
    <rect class="dt-hit" x="${L}" y="0" width="${W - L - R}" height="${H - 16}" fill="transparent"/>
  </svg><div class="dt-tip" hidden></div>`;
  const svg = box.querySelector("svg"), hov = svg.querySelector(".dt-hover"), tip = box.querySelector(".dt-tip");
  svg.querySelector(".dt-hit").addEventListener("mousemove", (e) => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const i = Math.max(0, Math.min(n - 1, Math.round(((p.x - L) / (W - L - R)) * (n - 1))));
    hov.hidden = false;
    hov.querySelector("line").setAttribute("x1", x(i)); hov.querySelector("line").setAttribute("x2", x(i));
    hov.querySelector("circle").setAttribute("cx", x(i)); hov.querySelector("circle").setAttribute("cy", y(close[i]));
    tip.hidden = false;
    tip.innerHTML = `<b>${fmtTime(ts[i], false)}</b><span>${fmtPx(close[i])}</span>${Object.keys(MA_COLORS).map((m) => mas[m][i] == null ? "" : `<span style="color:var(${MA_COLORS[m]})">MA${m.slice(2)} ${fmtPx(mas[m][i])}</span>`).join("")}${rsiS[i] != null ? `<span>RSI ${rsiS[i].toFixed(1)}</span>` : ""}<span class="muted">VOL ${fmtNum(vol[i])}</span>`;
    const r = box.getBoundingClientRect();
    tip.style.left = `${Math.min(r.width - 150, Math.max(0, e.clientX - r.left + 14))}px`;
  });
  svg.querySelector(".dt-hit").addEventListener("mouseleave", () => { hov.hidden = true; tip.hidden = true; });
}
RERENDER.push(() => { if (dt.data) renderDetail(); });

// 入口：自选列表的行、市场总览的卡片
$("#watch-table").addEventListener("click", (e) => {
  if (e.target.closest("button")) return;
  const tr = e.target.closest("tr[data-sym]");
  if (tr) openDetail(tr.dataset.sym);
});
["#mk-indices", "#mk-commods"].forEach((s) => $(s).addEventListener("click", (e) => {
  const c = e.target.closest("[data-sym]");
  if (c) openDetail(c.dataset.sym);
}));
