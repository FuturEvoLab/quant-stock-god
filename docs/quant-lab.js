// 量化股神 — 量化实验室：规则回测（/api/backtest）与基于历史波动率的统计区间（/api/forecast）
// 两者都是对历史数据的统计描述：回测说明“这条规则在过去这段时间表现如何”，统计区间说明“按过去的波动幅度，N 天后价格大概率落在哪”。
// 不是预测，不构成投资建议。

const ql = { bt: null, fc: null, sg: null };
const STATE_TEXT = { trend: { above: "200 日均线上方", below: "200 日均线下方" }, mom: { up: "20 日上涨", down: "20 日下跌" }, rsi: { oversold: "RSI 超卖", neutral: "RSI 中性", overbought: "RSI 超买" }, vol: { high: "波动偏高", normal: "波动常规", low: "波动偏低" } };
const MATCH_TEXT = { trend: "趋势", mom: "动量", rsi: "RSI" };
const FEAT_TEXT = { r5: "5 日收益", r20: "20 日收益", r60: "60 日收益", rsi: "RSI", ma200: "相对 200 日均线", volr: "波动率变化", pos52: "52 周位置" };
const MONTHS = ["1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月", "11 月", "12 月"], WEEKDAYS = ["周一", "周二", "周三", "周四", "周五"];
const QL_STRAT = { buyhold: "买入持有", ma_cross: "均线金叉 / 死叉（20 / 50 日）", trend200: "200 日趋势", rsi_mr: "RSI 均值回归" };
const QL_QUICK = ["^GSPC", "^IXIC", "^HSI", "GC=F", "CL=F", "NVDA", "AAPL", "0700.HK"];
const fmtSign = (v, d = 1, unit = "%") => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}${unit}`);

try {
  const saved = JSON.parse(localStorage.getItem("qs-ql") || "null");
  if (saved) { $("#ql-sym").value = saved.sym || ""; $("#ql-strategy").value = saved.strategy || "ma_cross"; $("#ql-range").value = saved.range || "5y"; $("#ql-fee").value = saved.fee ?? 5; }
} catch {}

function renderQuickQl() {
  const list = [...new Set([...state.watch.map((w) => w.sym), ...QL_QUICK])].slice(0, 12);
  $("#ql-quick").innerHTML = `<span class="muted">快速选择：</span>` + list.map((s) => `<button type="button" class="chip-btn" data-ql="${esc(s)}">${esc(s)}</button>`).join("");
}
$("#ql-quick").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ql]");
  if (b) { $("#ql-sym").value = b.dataset.ql; runQuant(); }
});
$("#ql-form").addEventListener("submit", (e) => { e.preventDefault(); runQuant(); });

async function runQuant() {
  const sym = $("#ql-sym").value.trim().toUpperCase();
  if (!sym) return toast("请输入代码");
  const strategy = $("#ql-strategy").value, range = $("#ql-range").value, fee = Math.max(0, +$("#ql-fee").value || 0), target = +$("#ql-target").value || 0;
  try { localStorage.setItem("qs-ql", JSON.stringify({ sym, strategy, range, fee })); } catch {}
  const loading = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在计算…</p></div>`;
  $("#ql-bt").innerHTML = $("#ql-fc").innerHTML = $("#ql-sg").innerHTML = loading;
  $("#ql-bt-sub").textContent = $("#ql-fc-sub").textContent = $("#ql-sg-sub").textContent = "";
  const btn = $("#ql-form button.primary");
  btn.disabled = true;
  const [bt, fc, sg] = await Promise.allSettled([
    api(`/api/backtest?sym=${encodeURIComponent(sym)}&strategy=${strategy}&range=${range}&fee=${fee}`),
    api(`/api/forecast?sym=${encodeURIComponent(sym)}${target ? `&target=${target}` : ""}`),
    api(`/api/signals?sym=${encodeURIComponent(sym)}`),
  ]);
  if (sg.status === "fulfilled") { ql.sg = sg.value; renderSignals(); } else { ql.sg = null; $("#ql-sg").innerHTML = `<div class="err">${esc(sg.reason.message)}</div>`; }
  btn.disabled = false;
  if (bt.status === "fulfilled") { ql.bt = bt.value; renderBacktest(); } else { ql.bt = null; $("#ql-bt").innerHTML = `<div class="err">${esc(bt.reason.message)}</div>`; }
  if (fc.status === "fulfilled") { ql.fc = fc.value; renderForecast(); } else { ql.fc = null; $("#ql-fc").innerHTML = `<div class="err">${esc(fc.reason.message)}</div>`; }
}

function renderBacktest() {
  const d = ql.bt;
  if (!d) return;
  const IN = getVar("--in"), OUT = getVar("--out"), ACC = getVar("--accent"), MUTED = getVar("--muted");
  const st = d.stats, bh = d.bh;
  // 每一段单独放在 span 里：自动翻译按文本节点工作，拼在一起的长句子匹配不到词典
  $("#ql-bt-sub").innerHTML = `<span translate="no">${esc(d.sym)}</span> · <span>${esc(QL_STRAT[d.strategy] || d.strategy)}</span> · <span translate="no">${fmtTime(d.start, false)} ~ ${fmtTime(d.end, false)}</span> · <span>${d.days} 个交易日</span> · <span>手续费 ${d.fee_bp} bp</span>`;
  const row = (label, a, b, fmt = (v) => fmtSign(v), good = (x, y) => x > y) =>
    `<tr><td>${label}</td><td class="num mono ${a != null && b != null ? (good(a, b) ? "up" : a === b ? "" : "down") : ""}">${fmt(a)}</td><td class="num mono muted">${fmt(b)}</td></tr>`;
  const metrics = `<table class="plain ql-metrics"><tr><th></th><th class="num">策略</th><th class="num">买入持有</th></tr>
    ${row("总收益", st.total, bh.total)}${row("年化收益", st.cagr, bh.cagr)}${row("年化波动", st.vol, bh.vol, (v) => (v == null ? "—" : v.toFixed(1) + "%"), (x, y) => x < y)}
    ${row("夏普比率", st.sharpe, bh.sharpe, (v) => (v == null ? "—" : v.toFixed(2)))}${row("最大回撤", st.mdd, bh.mdd, (v) => (v == null ? "—" : v.toFixed(1) + "%"), (x, y) => x > y)}</table>`;
  const facts = `<div class="ql-facts">
    <div><span>交易次数</span><b class="mono">${d.trades}${d.open_trade ? ` <small class="muted">+1 持有中</small>` : ""}</b></div>
    <div><span>胜率</span><b class="mono">${d.win_rate != null ? d.win_rate.toFixed(0) + "%" : "—"}</b></div>
    <div><span>平均每笔</span><b class="mono ${updn(d.avg_trade)}">${fmtSign(d.avg_trade)}</b></div>
    <div><span>持仓时间占比</span><b class="mono">${d.exposure.toFixed(0)}%</b></div>
    <div><span>当前状态</span><b class="${d.in_position ? "up" : "muted"}">${d.in_position ? "持有" : "空仓"}</b></div></div>`;
  // 净值曲线：策略 vs 买入持有，底部阴影为持仓区间
  const s = d.series, W = 720, H = 220, L = 44, R = 10, T = 10, B = 24;
  const all = [...s.eq, ...s.bh], lo = Math.min(...all), hi = Math.max(...all), rng = hi - lo || 1;
  const x = (i) => L + (i / (s.ts.length - 1)) * (W - L - R), y = (v) => T + (1 - (v - lo) / rng) * (H - T - B);
  const line = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  let shade = "", runStart = null;
  s.pos.forEach((p, i) => {
    if (p && runStart == null) runStart = i;
    if ((!p || i === s.pos.length - 1) && runStart != null) { shade += `<rect x="${x(runStart).toFixed(1)}" y="${T}" width="${(x(p && i === s.pos.length - 1 ? i : i) - x(runStart)).toFixed(1)}" height="${H - T - B}" fill="${IN}" opacity=".07"/>`; runStart = null; }
  });
  const grid = [0, 0.5, 1].map((f) => { const v = lo + rng * f; return `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${v.toFixed(2)}</text>`; }).join("");
  const dates = [0, Math.floor((s.ts.length - 1) / 2), s.ts.length - 1].map((i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === s.ts.length - 1 ? "end" : "middle"}">${fmtTime(s.ts[i], false)}</text>`).join("");
  const chart = `<div class="ql-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${shade}${grid}<path d="${line(s.bh)}" stroke="${MUTED}" class="bh"/><path d="${line(s.eq)}" stroke="${ACC}" class="eq"/>${dates}</svg>
    <div class="ql-legend"><span><i style="background:${ACC}"></i>策略净值</span><span><i style="background:${MUTED}"></i>买入持有</span><span><i style="background:${IN};opacity:.4"></i>持仓区间</span></div></div>`;
  const halves = d.halves.length === 2 ? `<table class="plain ql-halves"><tr><th>分段</th><th class="num">策略</th><th class="num">买入持有</th><th class="num">最大回撤</th><th class="num">夏普</th></tr>${d.halves.map((h, i) =>
    `<tr><td>${i ? "后半段" : "前半段"} <span class="muted mono">${fmtTime(h.from, false).slice(2)} ~ ${fmtTime(h.to, false).slice(2)}</span></td><td class="num mono ${updn(h.total)}">${fmtSign(h.total)}</td><td class="num mono muted">${fmtSign(h.bh_total)}</td><td class="num mono">${h.mdd.toFixed(1)}%</td><td class="num mono">${h.sharpe != null ? h.sharpe.toFixed(2) : "—"}</td></tr>`).join("")}</table>
    <p class="muted ql-note">前后两段都跑赢才说明规则不只在某一段有效；只有一段有效多半是巧合。</p>` : "";
  const trades = d.recent_trades.length ? `<div class="section-title">最近交易</div><div class="ql-trades">${d.recent_trades.slice().reverse().map((t) => `<span class="${updn(t.ret)}"><span class="mono muted">${fmtTime(t.entry, false).slice(2)} → ${fmtTime(t.exit, false).slice(2)}</span> <b class="mono">${fmtSign(t.ret)}</b></span>`).join("")}</div>` : "";
  $("#ql-bt").innerHTML = `<div class="ql-grid">${metrics}${facts}</div>${chart}${halves}${trades}
    <p class="muted ql-note">只做多、按收盘价执行、每次换仓扣 ${d.fee_bp} bp 手续费，未计滑点、股息和税费。历史表现不代表未来。</p>`;
}

function renderForecast() {
  const d = ql.fc;
  if (!d) return;
  const ACC = getVar("--accent"), OUT = getVar("--out");
  const regime = d.vol_pctile == null ? "" : d.vol_pctile >= 80 ? "近期波动明显高于过去一年的常态" : d.vol_pctile <= 20 ? "近期波动明显低于过去一年的常态" : "近期波动处于过去一年的常规水平";
  $("#ql-fc-sub").innerHTML = `<span translate="no">${esc(d.sym)} · ${fmtPx(d.price)} ${esc(d.currency || "")}</span> · <span>年化波动率 ${d.sigma_y.toFixed(1)}%</span>${d.sigma20_y != null ? ` · <span>近 20 日 ${d.sigma20_y.toFixed(1)}%</span>` : ""}`;
  const rows = d.bands.map((b) => `<tr><td class="mono">${b.h} 日</td><td class="num mono">${fmtPx(b.lo1)} – ${fmtPx(b.hi1)}</td><td class="num mono muted">${fmtPx(b.lo2)} – ${fmtPx(b.hi2)}</td><td class="num mono muted">±${b.sigma.toFixed(1)}%</td></tr>`).join("");
  const table = `<table class="plain ql-bands"><tr><th>期限</th><th class="num">68% 区间（±1σ）</th><th class="num">95% 区间（±2σ）</th><th class="num">1σ 幅度</th></tr>${rows}</table>`;
  const prob = d.prob ? `<div class="section-title">到达目标价 ${fmtPx(d.target)} 的概率</div><table class="plain ql-bands"><tr><th>期限</th><th class="num">到期时在目标价${d.target >= d.price ? "上方" : "下方"}</th><th class="num">期间曾触及</th></tr>
    ${d.prob.map((p) => `<tr><td class="mono">${p.h} 日</td><td class="num mono">${p.end.toFixed(1)}%</td><td class="num mono">${p.touch.toFixed(1)}%</td></tr>`).join("")}</table>` : "";
  // 波动率锥：以 60 个交易日为横轴，画 95% 与 68% 区间
  const W = 720, H = 200, L = 60, R = 16, T = 10, B = 24, last = d.bands[d.bands.length - 1];
  const pts = [{ h: 0, lo1: d.price, hi1: d.price, lo2: d.price, hi2: d.price }, ...d.bands];
  const lo = Math.min(last.lo2, d.target || Infinity), hi = Math.max(last.hi2, d.target || -Infinity), rng = hi - lo || 1;
  const x = (h) => L + (h / last.h) * (W - L - R), y = (v) => T + (1 - (v - lo) / rng) * (H - T - B);
  const poly = (loK, hiK) => pts.map((p) => `${x(p.h).toFixed(1)},${y(p[hiK]).toFixed(1)}`).concat(pts.slice().reverse().map((p) => `${x(p.h).toFixed(1)},${y(p[loK]).toFixed(1)}`)).join(" ");
  const grid = [0, 0.5, 1].map((f) => { const v = lo + rng * f; return `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${fmtPx(v)}</text>`; }).join("");
  const xt = d.bands.map((b) => `<text x="${x(b.h)}" y="${H - 6}" text-anchor="middle">${b.h}日</text>`).join("");
  const tgt = d.target ? `<line x1="${L}" x2="${W - R}" y1="${y(d.target)}" y2="${y(d.target)}" stroke="${OUT}" stroke-dasharray="4 3"/><text x="${W - R}" y="${y(d.target) - 4}" text-anchor="end" fill="${OUT}">${fmtPx(d.target)}</text>` : "";
  const chart = `<div class="ql-chart cone"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polygon points="${poly("lo2", "hi2")}" fill="${ACC}" opacity=".12"/><polygon points="${poly("lo1", "hi1")}" fill="${ACC}" opacity=".22"/>
    <line x1="${L}" x2="${W - R}" y1="${y(d.price)}" y2="${y(d.price)}" stroke="${ACC}"/>${tgt}${xt}</svg></div>`;
  const cov = Object.entries(d.coverage || {}).map(([h, c]) => `${h} 日：68% 区间实际覆盖 ${c.c1.toFixed(0)}%、95% 区间 ${c.c2.toFixed(0)}%（${c.n} 个样本）`).join("；");
  $("#ql-fc").innerHTML = `<div class="ql-grid">${table}<div class="ql-facts">
      <div><span>日波动率</span><b class="mono">${d.sigma_d.toFixed(2)}%</b></div>
      <div><span>近 20 日波动率百分位</span><b class="mono">${d.vol_pctile != null ? d.vol_pctile.toFixed(0) : "—"}</b><small class="muted">${regime}</small></div>
      <div><span>样本</span><b class="mono">${d.n} 个交易日</b></div></div></div>${chart}${prob}
    <p class="muted ql-note">假设未来日收益率的波动与过去一年相同、方向对称（无漂移）、服从正态分布；真实市场有肥尾，极端行情会超出 95% 区间。${cov ? `回看过去一年：${cov}；理论值 68% / 95%，偏差越大说明假设越不贴合。` : ""}</p>`;
}

function renderSignals() {
  const d = ql.sg;
  if (!d) return;
  const IN = getVar("--in"), OUT = getVar("--out");
  $("#ql-sg-sub").innerHTML = `<span translate="no">${esc(d.sym)} · ${fmtPx(d.price)} ${esc(d.currency || "")}</span> · <span>${d.years.toFixed(1)} 年历史</span>`;
  const a = d.analogs, st = a.state;
  const chips = ["trend", "mom", "rsi", "vol"].map((k) => `<span class="badge ${k === "mom" ? (st[k] === "up" ? "ok" : "no") : k === "trend" ? (st[k] === "above" ? "ok" : "no") : ""}">${STATE_TEXT[k][st[k]]}</span>`).join(" ");
  const analog = `<div class="section-title">历史相似情形</div>
    <p class="muted ql-note" style="margin:0 0 6px">当前状态：${chips}<br><span>按 ${a.matched_on.map((k) => tr(MATCH_TEXT[k])).join(" + ")} 匹配到 ${a.n} 个历史交易日（样本有重叠，独立样本远少于此）。</span></p>
    <table class="plain ql-bands"><tr><th>之后</th><th class="num">上涨比例</th><th class="num">全部历史</th><th class="num">收益中位数</th><th class="num">25% ~ 75%</th></tr>
    ${a.horizons.map((h) => `<tr><td class="mono">${h.h} 日</td><td class="num mono ${h.hit != null && h.base_hit != null ? (h.hit > h.base_hit + 3 ? "up" : h.hit < h.base_hit - 3 ? "down" : "") : ""}">${h.hit != null ? h.hit.toFixed(0) + "%" : "—"}</td><td class="num mono muted">${h.base_hit != null ? h.base_hit.toFixed(0) + "%" : "—"}</td><td class="num mono ${updn(h.median)}">${fmtSign(h.median)}</td><td class="num mono muted">${fmtSign(h.p25)} ~ ${fmtSign(h.p75)}</td></tr>`).join("")}</table>`;
  let model;
  if (d.model) {
    const m = d.model, up = m.p_now >= 50;
    const bar = (w) => `<div class="ql-w"><span>${FEAT_TEXT[w.feature] || w.feature}</span><div class="ql-wbar"><i style="width:${Math.min(100, Math.abs(w.w) / Math.max(...m.weights.map((x) => Math.abs(x.w)), 1e-9) * 100).toFixed(0)}%;background:${w.w >= 0 ? IN : OUT}"></i></div><b class="mono ${updn(w.w)}">${fmtSign(w.w, 2, "")}</b></div>`;
    model = `<div class="section-title">样本外模型检验（逻辑回归，预测 ${m.h} 个交易日后涨跌）</div>
      <div class="ql-grid"><div class="ql-facts">
        <div><span>模型给出的上涨概率</span><b class="mono ${up ? "up" : "down"}">${m.p_now.toFixed(0)}%</b><small class="muted">${m.useful ? "该模型在检验期优于基准" : "该模型在检验期并不优于基准，这个数字不应作为依据"}</small></div>
        <div><span>检验期命中率</span><b class="mono ${m.accuracy > m.base_accuracy + 3 ? "up" : m.accuracy < m.base_accuracy - 3 ? "down" : ""}">${m.accuracy.toFixed(0)}%</b><small class="muted">基准 ${m.base_accuracy.toFixed(0)}%（一直预测训练期多数方向）</small></div>
        <div><span>Brier 分数（越低越好）</span><b class="mono ${m.brier < m.brier_base ? "up" : "down"}">${m.brier.toFixed(3)}</b><small class="muted">基准 ${m.brier_base.toFixed(3)} · 技巧分 ${fmtSign(m.skill, 0)}</small></div>
        <div><span>样本</span><b class="mono">${m.train_n} / ${m.test_n}</b><small class="muted">训练期 / 检验期（最近一年）交易日</small></div></div>
      <div><div class="section-title" style="margin-top:0">特征权重（标准化后）</div>${m.weights.map(bar).join("")}
        <div class="section-title">校准：预测概率 → 实际上涨比例</div>
        <table class="plain ql-bands"><tr><th>预测概率</th><th class="num">样本</th><th class="num">实际上涨</th></tr>${m.calibration.map((b) => `<tr><td class="mono">${(b.range[0] * 100).toFixed(0)}% ~ ${(b.range[1] * 100).toFixed(0)}%</td><td class="num mono">${b.n}</td><td class="num mono">${b.up != null ? b.up.toFixed(0) + "%" : "—"}</td></tr>`).join("")}</table></div></div>`;
  } else {
    model = `<div class="section-title">样本外模型检验</div><p class="muted">${esc(d.model_error || "—")}</p>`;
  }
  const se = d.seasonality;
  const maxAbs = Math.max(...se.months.map((m) => Math.abs(m.mean || 0)), 0.01);
  const months = `<div class="section-title">季节性（历史月收益均值 / 上涨月份比例）</div><div class="ql-season">${se.months.map((m, i) => `<div class="${m.n ? updn(m.mean) : ""}" title="${MONTHS[i]}：${m.n} 个样本"><span>${MONTHS[i]}</span><i style="height:${m.n ? (Math.abs(m.mean) / maxAbs * 28).toFixed(0) : 0}px"></i><b class="mono">${m.n ? fmtSign(m.mean, 1) : "—"}</b><small class="mono">${m.n ? m.hit.toFixed(0) + "%" : ""}</small></div>`).join("")}</div>
    <div class="ql-week">${se.weekdays.map((w, i) => `<span><span class="muted">${WEEKDAYS[i]}</span> <b class="mono ${updn(w.mean)}">${w.mean != null ? fmtSign(w.mean, 3) : "—"}</b></span>`).join("")}</div>`;
  $("#ql-sg").innerHTML = analog + model + months +
    `<p class="muted ql-note">相似情形用“趋势 / 动量 / RSI”三个粗分类匹配，忽略了宏观环境等更重要的差异；模型只用价格派生的特征，命中率不高于基准是大多数品种的常态，说明价格历史里没有可利用的规律，而不是程序出错。季节性样本只有几个到十几个，差异多半是噪声。以上均不构成投资建议。</p>`;
}

TAB_LOADERS.quant = () => { renderQuickQl(); if ($("#ql-sym").value && !ql.bt) runQuant(); };
RERENDER.push(() => { renderQuickQl(); if (ql.bt) renderBacktest(); if (ql.fc) renderForecast(); if (ql.sg) renderSignals(); });
