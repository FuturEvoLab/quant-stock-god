// 量化股神 — 跨资产相关性：市场总览里的指数 / 利率 / 美元 / 商品两两的日收益率相关系数热力图
// 数据来自 /api/corr（服务端用已缓存的 2 年日线计算，不额外请求行情）

const cr = { data: null, days: 60, at: 0, loading: null };
const CORR_SHORT = { "^GSPC": "SPX", "^IXIC": "IXIC", "^HSI": "HSI", "^N225": "N225", "^VIX": "VIX", "^TNX": "US10Y", "DX-Y.NYB": "DXY",
  "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "WTI", "BZ=F": "BRENT", "HG=F": "COPPER", "NG=F": "NATGAS" };

async function loadCorr() {
  // 相关性只在新的一根日线出来后才会变，市场总览每 5 分钟的强制刷新不用跟着重算，10 分钟内直接复用
  if (cr.data && cr.data.days === cr.days && Date.now() - cr.at < 600000) return renderCorr();
  if (cr.loading) return cr.loading;
  const want = cr.days;
  if (!cr.data) $("#mk-corr").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在计算相关性…</p></div>`;
  cr.loading = (async () => {
    try {
      cr.data = await api(`/api/corr?days=${cr.days}`);
      cr.at = Date.now();
      renderCorr();
    } catch (e) { $("#mk-corr").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
    cr.loading = null;
    if (cr.days !== want) loadCorr(); // 请求期间用户切换了窗口：按新窗口再取一次（按请求时的窗口比较，请求失败时不会死循环）
  })();
  return cr.loading;
}

function renderCorr() {
  const d = cr.data;
  if (!d) return;
  const { syms, matrix } = d;
  const short = (s) => CORR_SHORT[s] || s;
  const name = (i) => d.names[i] || syms[i];
  const cell = (v, i, j) => {
    if (i === j) return `<td class="diag">—</td>`;
    if (v == null) return `<td class="muted">—</td>`;
    const pctv = Math.round(Math.abs(v) * 80), col = v >= 0 ? "var(--in)" : "var(--out)";
    return `<td style="background:color-mix(in srgb, ${col} ${pctv}%, transparent)" class="${Math.abs(v) >= 0.6 ? "strong" : ""}" title="${esc(name(i))} / ${esc(name(j))}：${v.toFixed(2)}">${v.toFixed(2)}</td>`;
  };
  const head = `<tr><th></th>${syms.map((s) => `<th translate="no">${esc(short(s))}</th>`).join("")}</tr>`;
  const rows = syms.map((s, i) => `<tr><th translate="no" title="${esc(name(i))}">${esc(short(s))}</th>${matrix[i].map((v, j) => cell(v, i, j)).join("")}</tr>`).join("");
  // 最强的正 / 负相关各 3 对（去掉对角线和重复的 (j, i)）
  const pairs = [];
  for (let i = 0; i < syms.length; i++) for (let j = i + 1; j < syms.length; j++) if (matrix[i][j] != null) pairs.push({ i, j, v: matrix[i][j] });
  pairs.sort((a, b) => b.v - a.v);
  const fmtPair = (p) => `<span class="corr-pair ${p.v >= 0 ? "up" : "down"}" translate="no">${esc(short(syms[p.i]))} / ${esc(short(syms[p.j]))} <b>${p.v >= 0 ? "+" : ""}${p.v.toFixed(2)}</b></span>`;
  const pos = pairs.filter((p) => p.v > 0).slice(0, 3), neg = pairs.filter((p) => p.v < 0).slice(-3).reverse();
  $("#mk-corr").innerHTML = `<div class="corr-wrap"><table class="corr">${head}${rows}</table></div>
    <div class="corr-foot">
      ${pos.length ? `<div><span class="muted">最强正相关</span>${pos.map(fmtPair).join("")}</div>` : ""}
      ${neg.length ? `<div><span class="muted">最强负相关</span>${neg.map(fmtPair).join("")}</div>` : ""}
      <p class="muted">${d.n} 个交易日的日收益率相关系数（Pearson）：+1 完全同向、−1 完全反向、0 无关。各市场假日不同，只取共同交易日；相关性会随时间变化，不代表因果。</p>
    </div>`;
  const bad = Object.keys(d.errors || {});
  $("#corr-msg").textContent = bad.length ? `部分品种获取失败：${bad.join(", ")}` : "";
}

$("#corr-range").addEventListener("click", (e) => {
  const b = e.target.closest("[data-d]");
  if (!b) return;
  cr.days = +b.dataset.d;
  $$("#corr-range button").forEach((x) => x.classList.toggle("on", x === b));
  loadCorr();
});
MARKET_HOOKS.push(() => loadCorr());
RERENDER.push(() => cr.data && renderCorr());
