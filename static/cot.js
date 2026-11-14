// 量化股神 — 商品持仓：CFTC COT 管理资金净持仓，及其在最近 3 年的百分位

const ct = { data: null, at: 0 };

async function loadCot(force = false) {
  if (!force && ct.data && Date.now() - ct.at < 3600000) return renderCot();
  const b = $("#cot-refresh");
  b.disabled = true;
  if (!ct.data) $("#cot-grid").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在读取 CFTC 持仓报告…</p></div>`;
  try {
    ct.data = await api("/api/cot");
    ct.at = Date.now();
    renderCot();
  } catch (e) { $("#cot-msg").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  b.disabled = false;
}

function cotChart(series) {
  const W = 360, H = 110, T = 6, B = 16;
  const v = series.map((s) => s.net), min = Math.min(...v, 0), max = Math.max(...v, 0), rng = max - min || 1;
  const x = (i) => (i / (v.length - 1)) * W, y = (n) => T + (1 - (n - min) / rng) * (H - T - B);
  const line = v.map((n, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(n).toFixed(1)}`).join("");
  const IN = getVar("--in"), OUT = getVar("--out");
  const years = [];
  series.forEach((s, i) => { if (i && s.d.slice(0, 4) !== series[i - 1].d.slice(0, 4)) years.push(`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H - B}" class="g"/><text x="${x(i) + 3}" y="${H - 4}">${esc(s.d.slice(0, 4))}</text>`); });
  return `<svg class="cot-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><clipPath id="cpos"><rect x="0" y="0" width="${W}" height="${y(0)}"/></clipPath><clipPath id="cneg"><rect x="0" y="${y(0)}" width="${W}" height="${H}"/></clipPath></defs>
    ${years.join("")}<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" class="zero"/>
    <path d="${line}L${W} ${y(0)}L0 ${y(0)}Z" fill="${IN}" opacity=".16" clip-path="url(#cpos)"/>
    <path d="${line}L${W} ${y(0)}L0 ${y(0)}Z" fill="${OUT}" opacity=".16" clip-path="url(#cneg)"/>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(v.length - 1)}" cy="${y(v[v.length - 1])}" r="3" fill="var(--accent)" class="last"/></svg>`;
}

function renderCot() {
  const d = ct.data;
  if (!d) return;
  const bad = Object.keys(d.errors || {});
  $("#cot-msg").innerHTML = bad.length ? `<div>部分品种获取失败：${esc(bad.join(", "))}</div>` : "";
  $("#cot-upd").textContent = d.markets[0] ? `报告日 ${d.markets[0].date}` : "";
  $("#cot-grid").innerHTML = d.markets.map((m) => {
    const p = Math.round(m.pctile), zone = p >= 90 ? "极高" : p >= 70 ? "偏高" : p > 30 ? "中间" : p > 10 ? "偏低" : "极低";
    const color = p >= 90 ? getVar("--in") : p <= 10 ? getVar("--out") : getVar("--accent");
    const sgn = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${fmtNum(n, 0)}`);
    return `<div class="card cot-card" style="--pc:${color}">
      <div class="card-head"><h3>${m.name}</h3><span class="mono muted" translate="no">${esc(m.sym)}</span><span class="spacer"></span><span class="badge q-act" style="--c:${color}">${zone}</span></div>
      <div class="cot-top">
        <div class="cot-pct"><b>${p}</b><small>3 年百分位</small></div>
        <dl class="kv">
          <dt>管理资金净持仓</dt><dd><b class="${updn(m.net)}">${sgn(m.net)}</b> <span class="muted">手</span></dd>
          <dt>多 / 空</dt><dd>${fmtNum(m.long, 0)} / ${fmtNum(m.short, 0)}</dd>
          <dt>占总持仓</dt><dd>${m.net_oi == null ? "—" : pct(m.net_oi, 1)}</dd>
          <dt>周变化</dt><dd><span class="${updn(m.chg1w)}">${sgn(m.chg1w)}</span> · 4 周 <span class="${updn(m.chg4w)}">${sgn(m.chg4w)}</span></dd>
          <dt>COT 指数</dt><dd>${Math.round(m.cot_index)}</dd>
        </dl>
      </div>
      <div class="cot-bar" title="3 年最低 → 最高"><i style="left:${m.cot_index.toFixed(1)}%"></i></div>
      <div class="cot-rng"><span>${sgn(m.min)}</span><span>3 年区间 · ${m.weeks} 周</span><span>${sgn(m.max)}</span></div>
      ${cotChart(m.series)}
    </div>`;
  }).join("");
}

$("#cot-refresh").addEventListener("click", () => loadCot(true));
TAB_LOADERS.cot = () => loadCot();
RERENDER.push(() => ct.data && renderCot());
