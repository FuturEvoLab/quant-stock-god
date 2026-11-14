// 量化股神 — 聪明钱：SEC Form 4 内部人公开市场买入（代码 P）与 13F 机构持仓季度变化
// 内部人：每笔买入后 30 / 90 天收益（及相对 S&P 500 的超额），按人统计命中率
// 13F：本季度 vs 上季度 → 新建仓 / 加仓 / 减仓 / 清仓，画成基金 ↔ 股票关系图

// 关系图实例放在 sm.cy 里，不能用 window.cy13：页面里有 id="cy13" 的容器，window.cy13 在画图前就是那个 div，调 destroy / resize 会报错
const sm = { sub: "insider", ins: null, f13: null, fund: null, cy: null, layout: null };
const ACT_TEXT = { new: "新建仓", add: "加仓", reduce: "减仓", exit: "清仓", hold: "持平" };
const actColor = (a) => ({ new: getVar("--q-new"), add: getVar("--in"), reduce: getVar("--q-reduce"), exit: getVar("--out"), hold: getVar("--q-hold") }[a]);
const secIndex = (cik, acc) => esc(`https://www.sec.gov/Archives/edgar/data/${cik}/${String(acc).replace(/-/g, "")}/${acc}-index.htm`);  // 已转义，只能放进属性
const rcell = (v) => (v == null ? `<span class="muted">—</span>` : `<span class="${updn(v)}">${pct(v, 1)}</span>`);
const roleText = (roles) => (roles || []).map((r) => `<span class="badge">${esc(r)}</span>`).join(" ");

$("#sm-sub").addEventListener("click", (e) => {
  const b = e.target.closest("[data-s]");
  if (!b) return;
  sm.sub = b.dataset.s;
  $$("#sm-sub button").forEach((x) => x.classList.toggle("on", x === b));
  $("#sm-insider").hidden = sm.sub !== "insider";
  $("#sm-13f").hidden = sm.sub !== "13f";
  if (sm.sub === "13f") { loadManagers(); if (sm.cy) setTimeout(() => { sm.cy.resize(); sm.cy.fit(undefined, 30); }, 50); }
});

function needEmail() {
  if (state.cfg.sec_email) return false;
  $("#sm-msg").innerHTML = `<div class="sm-need"><b>请先在设置页填写联系邮箱</b><span>SEC EDGAR 需要联系邮箱：请先到“设置”页填写（只用于 SEC 要求的 User-Agent，只保存在本机）。</span><button type="button" class="primary small" data-goto="settings">前往设置</button></div>`;
  return true;
}

// ---------------------------------------------------------------- 内部人买入

function renderQuick() {
  const us = state.watch.map((w) => w.sym).filter((s) => /^[A-Z.]{1,6}$/.test(s) && !s.endsWith(".HK"));
  const list = [...new Set([...us, "JPM", "KO", "PFE", "INTC"])].slice(0, 10);
  $("#ins-quick").innerHTML = `<span class="muted">快速选择：</span>` + list.map((s) => `<button type="button" class="chip-btn" data-ins="${esc(s)}">${esc(s)}</button>`).join("");
}
$("#ins-quick").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ins]");
  if (b) { $("#ins-sym").value = b.dataset.ins; analyzeInsider(); }
});
$("#ins-form").addEventListener("submit", (e) => { e.preventDefault(); analyzeInsider(); });

async function analyzeInsider() {
  const sym = $("#ins-sym").value.trim().toUpperCase();
  if (!sym || needEmail()) return;
  $("#sm-msg").innerHTML = "";
  $("#ins-result").innerHTML = `<div class="card sm-loading"><svg class="reactor loader-reactor" viewBox="0 0 32 32" aria-hidden="true"><circle class="ring" cx="16" cy="16" r="12" fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-dasharray="5 2.6"/><circle class="core" cx="16" cy="16" r="5" fill="var(--accent)"/></svg>
    <div class="scanbar"><i></i></div><p>正在读取 SEC Form 4 申报（首次较慢，之后有本地缓存）…</p></div>`;
  try {
    sm.ins = await api(`/api/insider?ticker=${encodeURIComponent(sym)}&limit=${$("#ins-limit").value}`);
    renderInsider();
  } catch (e) {
    $("#ins-result").innerHTML = "";
    $("#sm-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

function renderInsider() {
  const d = sm.ins;
  if (!d) return;
  const k = (key, v, sub) => `<div class="kpi"><div class="k">${key}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  const scored = d.events.filter((e) => e.r90 != null).length;
  $("#ins-result").innerHTML = `
  <div class="kpis sm-kpis">
    ${k(esc(d.ticker), `<span class="mono">${d.price != null ? fmtPx(d.price) : "—"}</span>`, esc(d.company))}
    ${k("扫描申报", d.filings_scanned, d.span[0] ? `${esc(d.span[0])} ~ ${esc(d.span[1])}` : "")}
    ${k("公开市场买入", d.events.length, `${d.insiders.length} 位内部人`)}
    ${k("90 天命中率", d.hit90 == null ? "—" : `<span class="${d.hit90 >= 0.5 ? "up" : "down"}">${Math.round(d.hit90 * 100)}%</span>`, `${scored} 笔已满 90 天`)}
    ${k("90 天平均收益", rcell(d.avg90), "买入日收盘价起算")}
  </div>
  <div class="card">
    <div class="card-head"><h3>内部人命中率</h3><span class="spacer"></span><span class="muted">命中 = 买入后 90 天上涨</span></div>
    <div class="table-wrap"><table><tr><th>内部人</th><th>身份</th><th class="num">买入次数</th><th class="num">买入金额</th><th class="num">30 天平均</th><th class="num">90 天平均</th><th class="num">相对 S&P 500</th><th class="num">90 天命中率</th><th>最近买入</th></tr>
    ${d.insiders.map((p) => `<tr><td><b>${esc(p.owner)}</b></td><td>${roleText(p.roles)}</td><td class="num">${p.buys}</td><td class="num">${fmtUsd(p.value)}</td>
      <td class="num">${rcell(p.avg30)}</td><td class="num">${rcell(p.avg90)}</td><td class="num">${rcell(p.excess90)}</td>
      <td class="num">${p.hit90 == null ? `<span class="muted">—</span>` : `<b class="${p.hit90 >= 0.5 ? "up" : "down"}">${Math.round(p.hit90 * 100)}%</b> <span class="muted">${p.scored}</span>`}</td><td>${esc(p.last)}</td></tr>`).join("")
      || `<tr><td class="muted">扫描范围内没有公开市场买入记录（内部人卖出、期权行权、授予等不计入）。</td></tr>`}</table></div>
  </div>
  <div class="card">
    <div class="card-head"><h3>买入明细</h3><span class="chip">${d.events.length}</span></div>
    <div class="table-wrap tall"><table><tr><th>交易日</th><th>申报日</th><th>内部人</th><th>身份</th><th class="num">股数</th><th class="num">均价</th><th class="num">金额</th><th class="num">30 天</th><th class="num">90 天</th><th class="num">90 天超额</th><th>原文</th></tr>
    ${d.events.map((e) => `<tr><td class="mono">${esc(e.date)}</td><td class="mono muted">${esc(e.filed)}</td><td>${esc(e.owner)}</td><td>${roleText(e.roles)}</td>
      <td class="num">${fmtNum(e.shares, 0)}</td><td class="num mono">${fmtPx(e.avg_price)}</td><td class="num">${fmtUsd(e.value)}</td>
      <td class="num">${rcell(e.r30)}</td><td class="num">${rcell(e.r90)}</td><td class="num">${rcell(e.x90)}</td>
      <td><a href="${secIndex(d.cik, e.acc)}" target="_blank" rel="noopener">SEC ↗</a></td></tr>`).join("") || `<tr><td class="muted">暂无</td></tr>`}</table></div>
  </div>
  <p class="muted sm-note"><span>说明：只统计 Form 4 非衍生品表中交易代码为 P（公开市场或私下买入）的记录，同一份申报内的多笔合并为一笔；收益按 Yahoo 日收盘价计算，未计股息；不足 30 / 90 天的显示“—”。</span>${d.parse_errors ? `<span>有 ${d.parse_errors} 份申报解析失败已跳过。</span>` : ""}<span>仅供参考，不构成投资建议。</span></p>`;
}

// ---------------------------------------------------------------- 13F

async function loadManagers() {
  try {
    const ms = await api("/api/managers");
    $("#mg-count").textContent = ms.length;
    $("#mg-list").innerHTML = ms.map((m) => `<span class="mg-chip"><b>${esc(m.name)}</b><small class="mono">CIK ${m.cik}</small><button type="button" data-mgdel="${m.cik}" title="删除">×</button></span>`).join("");
  } catch (e) { toast(e.message, 4000); }
}
$("#mg-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/managers", { method: "POST", body: { cik: $("#mg-cik").value, name: $("#mg-name").value } });
    $("#mg-cik").value = $("#mg-name").value = "";
    loadManagers();
  } catch (err) { toast(err.message, 4000); }
});
$("#mg-list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-mgdel]");
  if (b && confirm("不再跟踪这只基金？")) { await api(`/api/managers?cik=${b.dataset.mgdel}`, { method: "DELETE" }); loadManagers(); }
});

$("#f13-load").addEventListener("click", load13f);
async function load13f() {
  if (needEmail()) return;
  const b = $("#f13-load");
  b.disabled = true;
  $("#sm-msg").innerHTML = "";
  $("#f13-upd").textContent = "正在读取 13F（首次较慢）…";
  try {
    sm.f13 = await api("/api/13f");
    sm.f13.at = Date.now();
    sm.fund = sm.fund && sm.f13.funds.some((f) => f.cik === sm.fund) ? sm.fund : sm.f13.funds[0]?.cik;
    render13f();
  } catch (e) { $("#sm-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  $("#f13-upd").textContent = sm.f13?.at ? `更新于 ${fmtTime(sm.f13.at / 1000).slice(11)}` : "";
  b.disabled = false;
}

function render13f() {
  const d = sm.f13;
  if (!d) return;
  const bad = Object.entries(d.errors || {});
  if (bad.length) $("#sm-msg").innerHTML = `<div>部分基金获取失败：${esc(bad.map(([k, v]) => `${k}（${v}）`).join("；"))}</div>`;
  drawGraph13();
  renderFund();
}

// Cytoscape 有 370 KB，只有 13F 关系图用到：第一次画图时再加载，不拖慢首屏（动态插入的同源脚本符合 CSP）
let cyLoading = null;
function loadCytoscape() {
  if (window.cytoscape) return Promise.resolve();
  cyLoading ||= new Promise((ok, fail) => {
    const el = document.createElement("script");
    el.src = "vendor/cytoscape.min.js?v=3.30";
    el.onload = ok;
    el.onerror = () => { cyLoading = null; fail(new Error("cytoscape.min.js")); };
    document.head.appendChild(el);
  });
  return cyLoading;
}

async function drawGraph13() {
  if (!window.cytoscape) {
    $("#g13-empty").hidden = true;
    try { await loadCytoscape(); } catch (e) { $("#sm-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    if (!sm.f13) return;
  }
  const d = sm.f13, showHold = $("#g13-hold").checked;
  const nodes = new Map(), edges = [];
  for (const f of d.funds) {
    nodes.set("f" + f.cik, { data: { id: "f" + f.cik, name: f.name, kind: "fund", size: 46, color: getVar("--accent") } });
    const top = new Set(f.changes.filter((c) => c.act !== "exit").slice(0, 12).map((c) => c.cusip));
    const picked = f.changes.filter((c) => top.has(c.cusip) || c.act === "new" || c.act === "exit").slice(0, 40);
    for (const c of picked) {
      if (c.act === "hold" && !showHold) continue;
      const sid = "s" + c.cusip;
      const val = c.value || c.prev_value || 0;
      const n = nodes.get(sid) || { data: { id: sid, name: c.name, kind: "stock", val: 0, color: getVar("--text-2") } };
      n.data.val += val;
      nodes.set(sid, n);
      edges.push({ data: { id: `${f.cik}-${c.cusip}`, source: "f" + f.cik, target: sid, act: c.act, color: actColor(c.act), width: Math.max(1.2, Math.min(9, Math.log10(Math.max(val, 1e5)) * 2.2 - 9.5)) } });
    }
  }
  for (const n of nodes.values()) if (n.data.kind === "stock") n.data.size = Math.max(14, Math.min(40, Math.log10(Math.max(n.data.val, 1e6)) * 7 - 28));
  const hud = document.documentElement.dataset.theme === "dark";
  const style = [
    { selector: "node", style: { width: "data(size)", height: "data(size)", "background-color": "data(color)", "background-opacity": 0.85, label: "data(name)",
      "font-size": 10, color: getVar("--text-2"), "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "ellipsis", "text-max-width": 130,
      "font-family": hud ? "JetBrains Mono, PingFang SC, monospace" : "Inter, PingFang SC, sans-serif",
      "text-background-color": getVar("--bg"), "text-background-opacity": 0.7, "text-background-padding": 2, "border-width": 1, "border-color": getVar("--border-strong") } },
    { selector: "node[kind = 'fund']", style: { shape: "hexagon", "font-size": 12, "font-weight": 700, color: getVar("--text"), "underlay-color": getVar("--accent"), "underlay-opacity": 0.18, "underlay-padding": 8 } },
    { selector: "node:selected", style: { "overlay-color": getVar("--accent"), "overlay-opacity": 0.25, "overlay-padding": 6 } },
    { selector: "edge", style: { width: "data(width)", "line-color": "data(color)", "curve-style": "bezier", "line-opacity": 0.7 } },
    { selector: "edge[act = 'exit']", style: { "line-style": "dashed", "line-dash-pattern": [6, 4] } },
    { selector: ".dim", style: { opacity: 0.12 } },
  ];
  $("#g13-empty").hidden = nodes.size > 0;
  // 布局用 animate: "end"（先算好位置再平滑移动过去）：比逐帧跑物理模拟省 CPU，而且快速重画（连续切换“显示持平”）时销毁上一张图不会在半路的布局 tick 上报错
  sm.layout?.stop();
  if (sm.cy) sm.cy.destroy();
  const cy = sm.cy = cytoscape({ container: $("#cy13"), elements: [...nodes.values(), ...edges], style, wheelSensitivity: 0.25, minZoom: 0.15, maxZoom: 3 });
  sm.layout = cy.layout({ name: "cose", animate: REDUCED ? false : "end", animationDuration: 900, nodeRepulsion: () => 9000, idealEdgeLength: () => 90, padding: 30, randomize: true });
  sm.layout.run();
  cy.on("tap", "node", (e) => {
    const n = e.target;
    cy.elements().addClass("dim");
    n.closedNeighborhood().removeClass("dim");
    if (n.data("kind") === "fund") { sm.fund = +n.id().slice(1); renderFund(); }
    else renderStock(n.id().slice(1));
  });
  cy.on("tap", (e) => { if (e.target === cy) cy.elements().removeClass("dim"); });
}
$("#g13-hold").addEventListener("change", () => sm.f13 && drawGraph13());
$("[data-z13]").addEventListener("click", () => sm.cy?.fit(undefined, 30));

function fundSummary() {
  return `<div class="card"><div class="card-head"><h3>基金概览</h3><span class="spacer"></span><span class="muted">点击行查看明细</span></div>
    <div class="table-wrap"><table class="f13-sum"><tr><th>基金</th><th>报告季度</th><th>申报日</th><th class="num">持仓数</th><th class="num">持仓市值</th>
      <th class="num">新建仓</th><th class="num">加仓</th><th class="num">减仓</th><th class="num">清仓</th></tr>
    ${sm.f13.funds.map((f) => `<tr data-fund="${f.cik}" class="${f.cik === sm.fund ? "on" : ""}"><td><b>${esc(f.name)}</b></td><td class="mono">${esc(f.report)}</td><td class="mono muted">${esc(f.filed)}</td>
      <td class="num">${f.positions}</td><td class="num">${fmtUsd(f.total)}</td>
      ${["new", "add", "reduce", "exit"].map((a) => `<td class="num"><b style="color:${actColor(a)}">${f.count[a]}</b></td>`).join("")}</tr>`).join("")}</table></div></div>`;
}
function changesTable(rows, withFund) {
  return `<table><tr>${withFund ? "<th>基金</th>" : ""}<th>动作</th><th>股票</th><th class="mono">CUSIP</th><th class="num">市值</th><th class="num">仓位占比</th><th class="num">股数</th><th class="num">股数变化</th></tr>
    ${rows.map((c) => `<tr>${withFund ? `<td>${esc(c.fund)}</td>` : ""}<td><span class="badge q-act" style="--c:${actColor(c.act)}">${ACT_TEXT[c.act]}</span></td><td><b>${esc(c.name)}</b> <span class="muted">${esc(c.cls)}</span></td>
      <td class="mono muted">${esc(c.cusip)}</td><td class="num">${c.act === "exit" ? `<span class="muted">${fmtUsd(c.prev_value)}</span>` : fmtUsd(c.value)}</td>
      <td class="num">${c.weight ? c.weight.toFixed(2) + "%" : "—"}</td><td class="num">${fmtNum(c.shares, 0)}</td><td class="num">${rcell(c.share_chg)}</td></tr>`).join("")}</table>`;
}
function renderFund() {
  const f = sm.f13?.funds.find((x) => x.cik === sm.fund);
  if (!f) return ($("#f13-detail").innerHTML = sm.f13 ? fundSummary() : "");
  const rows = f.changes.filter((c) => c.act !== "hold" || $("#g13-hold").checked);
  $("#f13-detail").innerHTML = fundSummary() + `<div class="card"><div class="card-head"><h3>${esc(f.name)} · ${esc(f.report)} vs ${esc(f.prev_report || "—")}</h3><span class="chip">${rows.length}</span><span class="spacer"></span>
      <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${f.cik}&type=13F-HR" target="_blank" rel="noopener">EDGAR ↗</a></div>
    <div class="table-wrap tall">${changesTable(rows, false)}</div></div>
    <p class="muted sm-note">13F 只披露季末的美股多头持仓（不含空头、现金、多数海外资产），季度结束后约 45 天内申报，看到的已是旧仓位。期权持仓未计入。仅供参考，不构成投资建议。</p>`;
}
function renderStock(cusip) {
  const rows = [];
  for (const f of sm.f13.funds) for (const c of f.changes) if (c.cusip === cusip) rows.push({ ...c, fund: f.name });
  $("#f13-detail").innerHTML = fundSummary() + `<div class="card"><div class="card-head"><h3>${esc(rows[0]?.name || cusip)} · 各基金动作</h3><span class="chip">${rows.length}</span></div>
    <div class="table-wrap">${changesTable(rows, true)}</div></div>`;
}
$("#f13-detail").addEventListener("click", (e) => {
  const tr = e.target.closest("[data-fund]");
  if (!tr) return;
  sm.fund = +tr.dataset.fund;
  renderFund();
  const n = sm.cy?.$id("f" + sm.fund);
  if (n?.length) { sm.cy.elements().addClass("dim"); n.closedNeighborhood().removeClass("dim"); }
});

TAB_LOADERS.smart = () => { renderQuick(); if (state.cfg.sec_email) $("#sm-msg").innerHTML = ""; else needEmail(); };
RERENDER.push(() => { renderQuick(); renderInsider(); if (sm.f13) render13f(); });
$("#sm-msg").addEventListener("click", (e) => { const b = e.target.closest("[data-goto]"); if (b) { switchTab(b.dataset.goto); $("#cfg-sec_email").focus(); } });
