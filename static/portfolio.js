// 量化股神 — 持仓盈亏：本机记录的持仓（代码、股数、平均成本）× 行情 → 市值、盈亏、当日盈亏、权重
// 数据来自 /api/portfolio（服务端用自选同一套行情缓存计算；非美元品种按 Yahoo 汇率折成美元合计）

const pf = { data: null, at: 0 };
const money = (v, d = 2) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const signed = (v, d = 2) => (v == null ? "—" : `${v >= 0 ? "+" : "-"}${money(Math.abs(v), d)}`);

async function loadPortfolio(force = false) {
  if (!force && pf.data && Date.now() - pf.at < 120000) return renderPortfolio();
  const btn = $("#pf-refresh");
  btn.disabled = true;
  if (!pf.data) $("#pf-table").innerHTML = `<tr><td><div class="sm-loading"><div class="scanbar"><i></i></div><p>正在获取行情…</p></div></td></tr>`;
  try {
    pf.data = await api("/api/portfolio");
    pf.at = Date.now();
    renderPortfolio();
  } catch (e) {
    $("#pf-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`;
    if (!pf.data) $("#pf-table").innerHTML = "";  // 第一次就失败：别让“正在获取行情”一直转
  }
  btn.disabled = false;
}

function renderPortfolio() {
  const d = pf.data;
  if (!d) return;
  const IN = getVar("--in"), OUT = getVar("--out");
  const u = d.usd, rows = d.positions || [];
  $("#pf-upd").textContent = pf.at ? `更新于 ${fmtTime(pf.at / 1000).slice(11)}` : "";
  $("#pf-count").textContent = rows.length;
  const msgs = [];
  const bad = Object.keys(d.errors || {});
  if (bad.length) msgs.push(`部分品种获取失败：${esc(bad.join(", "))}`);
  if (d.unconverted?.length) msgs.push(`以下币种没有汇率，未计入美元合计：${esc(d.unconverted.join(", "))}`);
  if (d.stale) msgs.push("Yahoo 暂时限流，部分品种显示的是本地缓存数据");
  $("#pf-msg").innerHTML = msgs.map((m) => `<div>${m}</div>`).join("");
  // 汇总卡片（美元口径）
  const tile = (label, val, sub, tone) => `<div class="pf-tile ${tone || ""}"><span>${label}</span><b class="mono">${val}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
  $("#pf-sum").innerHTML = u
    ? tile("总市值（USD）", money(u.value, 0), `${u.n} 个持仓`) + tile("总成本（USD）", money(u.cost, 0), Object.keys(d.fx || {}).length > 1 ? "非美元持仓按当前汇率折算，盈亏不含汇率变动" : "") +
      tile("累计盈亏", signed(u.pnl, 0), u.pnl_pct != null ? pct(u.pnl_pct) : "", updn(u.pnl)) +
      tile("当日盈亏", signed(u.day_pnl, 0), u.day_pct != null ? pct(u.day_pct) : "", updn(u.day_pnl))
    : rows.length ? "" : `<div class="pf-tile wide"><span>还没有持仓</span><b class="muted" style="font-size:14px">在下面输入代码、股数和平均成本。数据只保存在本机，不会上传。</b></div>`;
  // 多币种时列出各币种小计和用到的汇率
  const fxs = Object.entries(d.fx || {}).filter(([c]) => c !== "USD").map(([c, r]) => `1 USD = ${money(r, 3)} ${c}`);
  $("#pf-fx").textContent = fxs.join(" · ");
  const totals = (d.totals || []).length > 1 ? `<tr class="pf-totals"><td colspan="13">${d.totals.map((t) => `<span translate="no"><b>${esc(t.currency)}</b> ${money(t.value, 0)} · <i class="${updn(t.pnl)}">${signed(t.pnl, 0)}</i> · <small>1D</small> <i class="${updn(t.day_pnl)}">${signed(t.day_pnl, 0)}</i></span>`).join("")}</td></tr>` : "";
  $("#pf-table").innerHTML = rows.length
    ? `<tr><th>代码</th><th>名称</th><th class="num">股数</th><th class="num">平均成本</th><th class="num">现价</th><th class="num">1D</th><th class="num">市值</th><th class="num">盈亏</th><th class="num">盈亏 %</th><th class="num">当日盈亏</th><th title="按美元市值占比">权重</th><th>1 个月走势</th><th></th></tr>` +
      rows.map((r) => r.error
        ? `<tr data-sym="${esc(r.sym)}"><td><b class="mono">${esc(r.sym)}</b></td><td colspan="11"><span class="badge no" title="${esc(r.error)}">获取失败</span> <span class="muted">${esc(r.note || "")}</span></td>
           <td class="row-acts"><button type="button" class="small ghost" data-pedit="${esc(r.sym)}">修改</button><button type="button" class="small ghost" data-pdel="${esc(r.sym)}">删除</button></td></tr>`
        : `<tr data-sym="${esc(r.sym)}" title="点击查看详情"><td><b class="mono">${esc(r.sym)}</b>${r.stale ? ` <span class="badge">缓存</span>` : ""}</td><td>${esc(r.name || "")}${r.note ? ` <span class="muted" translate="no">· ${esc(r.note)}</span>` : ""}</td>
           <td class="num mono">${money(r.shares, Number.isInteger(r.shares) ? 0 : 4)}</td><td class="num mono">${fmtPx(r.cost)}</td>
           <td class="num mono">${fmtPx(r.price)} <span class="muted">${esc(r.currency)}</span></td><td class="num mk-chg ${updn(r.chg1d)}">${pct(r.chg1d)}</td>
           <td class="num mono">${money(r.value, 0)}</td><td class="num mono ${updn(r.pnl)}">${signed(r.pnl, 0)}</td><td class="num mk-chg ${updn(r.pnl_pct)}">${pct(r.pnl_pct, 1)}</td>
           <td class="num mono ${updn(r.day_pnl)}">${signed(r.day_pnl, 0)}</td>
           <td>${r.weight != null ? `<div class="pf-w" title="${r.weight.toFixed(1)}%"><i style="width:${Math.min(100, r.weight).toFixed(1)}%"></i><span>${r.weight.toFixed(1)}%</span></div>` : `<span class="muted">—</span>`}</td>
           <td class="spark-td">${sparkSvg(r.spark, (r.chg1d ?? 0) >= 0 ? IN : OUT, 120, 30)}</td>
           <td class="row-acts"><button type="button" class="small ghost" data-pedit="${esc(r.sym)}">修改</button><button type="button" class="small ghost" data-pdel="${esc(r.sym)}">删除</button></td></tr>`).join("") + totals
    : `<tr><td class="muted">还没有持仓，在上面添加。</td></tr>`;
}

$("#pf-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { sym: $("#pf-sym").value, shares: +$("#pf-shares").value, cost: +$("#pf-cost").value, note: $("#pf-note").value };
  try {
    pf.data = await api("/api/portfolio", { method: "POST", body });
    pf.at = Date.now();
    renderPortfolio();
    $("#pf-sym").value = $("#pf-shares").value = $("#pf-cost").value = $("#pf-note").value = "";
    toast("已保存");
  } catch (err) { toast(err.message, 4000); }
});
$("#pf-table").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-pdel]"), ed = e.target.closest("[data-pedit]");
  if (del) {
    if (!confirm("删除这条持仓？")) return;
    try {
      pf.data = await api(`/api/portfolio?sym=${encodeURIComponent(del.dataset.pdel)}`, { method: "DELETE" });
      pf.at = Date.now();
      renderPortfolio();
    } catch (err) { toast(err.message, 4000); }
    return;
  }
  if (ed) {
    const p = pf.data.positions.find((x) => x.sym === ed.dataset.pedit);
    $("#pf-sym").value = p.sym; $("#pf-shares").value = p.shares; $("#pf-cost").value = p.cost; $("#pf-note").value = p.note || "";
    $("#pf-shares").focus();
    return;
  }
  const tr = e.target.closest("tr[data-sym]");
  if (tr && !tr.querySelector(".badge.no")) openDetail(tr.dataset.sym);
});
$("#pf-refresh").addEventListener("click", () => loadPortfolio(true));
TAB_LOADERS.portfolio = () => loadPortfolio();
RERENDER.push(() => pf.data && renderPortfolio());
setInterval(() => { if (!document.hidden && $("#tab-portfolio").classList.contains("active")) loadPortfolio(true); }, 300000);

// 顶栏快速查看：输入任意代码回车打开详情；按 / 聚焦
$("#lookup").addEventListener("submit", (e) => {
  e.preventDefault();
  const sym = $("#lookup-sym").value.trim().toUpperCase();
  if (sym) { openDetail(sym); $("#lookup-sym").value = ""; $("#lookup-sym").blur(); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName) && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); $("#lookup-sym").focus(); }
});
