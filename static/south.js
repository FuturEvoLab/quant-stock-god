// 量化股神 — 港股通南向资金（HKEX 每日成交统计）
// 卡片放在市场总览：每日净买入柱状图、沪 / 深两条通道、近 5 / 20 日合计、连续天数、当日成交额前 10；往“市场解读”里追加客观描述

const sb = { data: null, at: 0 };
const fmtHk = (n, sign = false) => (n == null ? "—" : `${n < 0 ? "-" : sign && n > 0 ? "+" : ""}HK$${fmtNum(Math.abs(n))}`);
const hkSym = (code) => `${String(+code).padStart(4, "0")}.HK`; // HKEX 代码 09988 → Yahoo 代码 9988.HK

async function loadSouth(force = false) {
  if (!force && sb.data && Date.now() - sb.at < 600000) return renderSouth();
  if (!sb.data) $("#sb-body").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在读取港股通南向资金…</p></div>`;
  try {
    sb.data = await api("/api/southbound");
    sb.at = Date.now();
    $("#sb-msg").innerHTML = "";
    renderSouth();
  } catch (e) { $("#sb-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; if (!sb.data) $("#sb-body").innerHTML = ""; }
}

function southChart(series) {
  const W = 720, H = 210, L = 52, R = 8, T = 10, B = 22, n = series.length;
  if (n < 2) return `<p class="muted">暂无数据</p>`;
  const m = Math.max(...series.map((p) => Math.abs(p.net)), 1);
  const x = (i) => L + (i + 0.5) * ((W - L - R) / n), y = (v) => T + (1 - (v + m) / (2 * m)) * (H - T - B);
  const bw = Math.max(2, (W - L - R) / n - 3), IN = getVar("--in"), OUT = getVar("--out");
  const bars = series.map((p, i) => `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${Math.min(y(p.net), y(0)).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, Math.abs(y(p.net) - y(0))).toFixed(1)}" fill="${p.net >= 0 ? IN : OUT}" opacity="${i === n - 1 ? 0.95 : 0.6}"><title>${p.d} · ${fmtHk(p.net, true)}</title></rect>`).join("");
  const grid = [m, 0, -m].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="g"/><text x="${L - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${v ? fmtNum(v) : "0"}</text>`).join("");
  const dates = [0, Math.floor((n - 1) / 2), n - 1].map((i) => `<text x="${x(i).toFixed(1)}" y="${H - 5}" text-anchor="middle">${series[i].d.slice(5)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}">${grid}${bars}${dates}</svg>`;
}

function renderSouth() {
  const d = sb.data;
  if (!d) return;
  $("#sb-date").textContent = `交易日 ${d.date}`;
  const stat = (k, v, cls = "", sub = "") => `<div class="dt-stat"><span>${k}</span><b class="mono ${cls}">${v}</b>${sub ? `<small class="muted">${sub}</small>` : ""}</div>`;
  const st = d.streak;
  const tr = (t, net) => `<tr data-sym="${esc(hkSym(t.code))}" title="点击查看详情"><td class="mono">${esc(t.code)}</td><td>${esc(t.name)}</td>
      ${net === undefined ? `<td class="num mono">${fmtHk(t.buy)}</td><td class="num mono">${fmtHk(t.sell)}</td>` : `<td class="num mono">${t.days}</td>`}
      <td class="num mono ${updn(t.net)}">${fmtHk(t.net, true)}</td></tr>`;
  const top5 = d.top5d.length > 10 ? [...d.top5d.slice(0, 5), ...d.top5d.slice(-5)] : d.top5d;
  $("#sb-body").innerHTML = `
    <div class="dt-grid sb-stats">
      ${stat("当日净买入", fmtHk(d.net, true), updn(d.net), `<span translate="no">SH</span> ${fmtHk(d.links.sh?.net, true)} · <span translate="no">SZ</span> ${fmtHk(d.links.sz?.net, true)}`)}
      ${stat("近 5 日净买入", fmtHk(d.net5, true), updn(d.net5))}
      ${stat("近 20 日净买入", fmtHk(d.net20, true), updn(d.net20))}
      ${stat(st >= 0 ? "连续净买入" : "连续净卖出", `${Math.abs(st)} 日`, st >= 0 ? "up" : "down")}
      ${stat("当日成交额", fmtHk(d.turnover), "", `20 日均值 ${fmtHk(d.turnover20)}`)}
    </div>
    <div class="sb-chart">${southChart(d.series)}</div>
    <div class="sb-tables">
      <div><div class="section-title">当日成交额前 10</div>
        <div class="table-wrap"><table><tr><th>代码</th><th>名称</th><th class="num">买入</th><th class="num">卖出</th><th class="num">净买入</th></tr>${d.top.map((t) => tr(t)).join("")}</table></div></div>
      <div><div class="section-title">近 5 日净买入 / 净卖出</div>
        <div class="table-wrap"><table><tr><th>代码</th><th>名称</th><th class="num">上榜天数</th><th class="num">净买入</th></tr>${top5.map((t) => tr(t, true)).join("")}</table></div></div>
    </div>
    <p class="muted dt-note">个股只统计每天成交额前 10 的股票（HKEX 只公布这 10 只的买卖额），不是全部南向持股变化。金额为港元。</p>`;
}

$("#sb-card").addEventListener("click", (e) => {
  const r = e.target.closest("tr[data-sym]");
  if (r) openDetail(r.dataset.sym);
});

// 市场解读：只描述资金方向和力度，不做判断
READING_HOOKS.push((add) => {
  const d = sb.data;
  if (!d) return;
  if (Math.abs(d.streak) >= 3) add(d.streak > 0 ? "bull" : "bear", "港股通南向资金", `${Math.abs(d.streak)} 日`,
    d.streak > 0 ? "南向资金连续多日净买入港股" : "南向资金连续多日净卖出港股", d.streak > 0 ? "up" : "down");
  if (d.avg_abs20 && Math.abs(d.net) >= 2 * d.avg_abs20) add(d.net > 0 ? "bull" : "bear", "南向资金 · 当日", fmtHk(d.net, true),
    d.net > 0 ? "当日南向净买入明显高于近 20 日平均力度" : "当日南向净卖出明显高于近 20 日平均力度", d.net > 0 ? "up" : "down");
});

MARKET_HOOKS.push(async (force) => {
  await loadSouth(force);
  if (mk.data) renderReadings();
});
RERENDER.push(renderSouth);
