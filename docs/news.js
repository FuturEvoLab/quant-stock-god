// 量化股神 — 新闻影响：公开 RSS 标题 + 关键词规则 → 驱动因素与通常的影响方向（不是价格预测）

const nw = { data: null, at: 0, asset: "", px: {} };
const NW_ASSETS = { oil: "原油", natgas: "天然气", gold: "黄金", silver: "白银", copper: "铜" };
const NW_SYM = { oil: "CL=F", natgas: "NG=F", gold: "GC=F", silver: "SI=F", copper: "HG=F" };
const NW_LABEL = { bull: "新闻偏多", bear: "新闻偏空", mixed: "多空交织", neutral: "无明显倾向" };
const effMark = (v) => (v === "mix" ? "±" : v >= 2 ? "▲▲" : v > 0 ? "▲" : v <= -2 ? "▼▼" : v < 0 ? "▼" : "");
// 两个视图（大宗商品 / AI·科技）共用提示区和刷新按钮：只让当前视图写入
const newsView = () => (typeof tn !== "undefined" ? tn.view : "commod");
const msgFor = (view, html) => { if (newsView() === view) $("#nw-msg").innerHTML = html; };
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#"); // RSS 来的链接只允许 http(s)
// 新闻源长时间没刷新成功时提醒（页面上的时间是数据真正抓取的时间）
function staleNote(d) {
  const ts = d.data_ts || d.fetched;
  return Date.now() / 1000 - ts > 3600 ? `<div>新闻数据较旧：最后成功更新于 ${fmtTime(ts).slice(5)}，新闻源可能暂时无法访问</div>` : "";
}
const effCls = (v) => (v === "mix" ? "mix" : v > 0 ? "up" : "down");

async function loadNews(force = false) {
  if (!force && nw.data && Date.now() - nw.at < 600000) return renderNews();
  const b = $("#nw-refresh");
  b.disabled = true;
  if (!nw.data) $("#nw-assets").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在抓取新闻…</p></div>`;
  try {
    const [d, m] = await Promise.all([api("/api/news"), api("/api/market").catch(() => null)]);
    nw.data = d;
    nw.at = Date.now();
    if (m) for (const q of [...m.indices, ...m.commods]) nw.px[q.sym] = q;
    renderNews();
  } catch (e) { msgFor("commod", `<div class="err">${esc(e.message)}</div>`); }
  b.disabled = false;
}

// 新闻倾向和实际价格走势是否一致：只做事实对照，不下结论
function priceNote(label, q) {
  if (!q || q.chg1w == null || label === "neutral" || label === "mixed") return "";
  if (label === "bull" && q.chg1w < -1) return "新闻偏多，但价格一周下跌";
  if (label === "bear" && q.chg1w > 1) return "新闻偏空，但价格一周上涨";
  return "";
}

function renderNews() {
  const d = nw.data;
  if (!d) return;
  const bad = Object.keys(d.errors || {});
  msgFor("commod", (bad.length ? `<div>部分新闻源暂时不可用：${esc(bad.join(", "))}</div>` : "") + staleNote(d));
  if (newsView() === "commod") $("#nw-upd").textContent = `更新于 ${fmtTime(d.data_ts || d.fetched).slice(5)}`;
  const strong = Object.values(d.summary).filter((s) => s.label === "bull" || s.label === "bear").length;
  $("#nav-news").hidden = !strong;
  $("#nav-news").textContent = strong;

  $("#nw-assets").innerHTML = Object.entries(NW_ASSETS).map(([a, name]) => {
    const s = d.summary[a], q = nw.px[NW_SYM[a]];
    const color = s.label === "bull" ? getVar("--in") : s.label === "bear" ? getVar("--out") : s.label === "mixed" ? getVar("--q-reduce") : getVar("--muted");
    const pos = Math.max(0, Math.min(6, s.pos)) / 6 * 50, neg = Math.max(0, Math.min(6, -s.neg)) / 6 * 50;
    const note = priceNote(s.label, q);
    return `<div class="card nw-asset" style="--pc:${color}" data-a="${a}">
      <div class="card-head"><h3>${name}</h3><span class="mono muted" translate="no">${NW_SYM[a]}</span><span class="spacer"></span><span class="badge q-act" style="--c:${color}">${NW_LABEL[s.label]}</span></div>
      <div class="nw-tilt" title="左：偏空因素合计 · 右：偏多因素合计"><i class="neg" style="width:${neg.toFixed(1)}%"></i><i class="pos" style="width:${pos.toFixed(1)}%"></i></div>
      <div class="nw-meta"><span>倾向分 <b class="${updn(s.score)}">${s.score >= 0 ? "+" : ""}${s.score.toFixed(1)}</b></span><span>相关新闻 ${s.count} 条</span></div>
      ${q ? `<div class="nw-meta"><span>价格 1D <b class="${updn(q.chg1d)}">${pct(q.chg1d)}</b></span><span>1W <b class="${updn(q.chg1w)}">${pct(q.chg1w)}</b></span></div>` : ""}
      ${note ? `<div class="nw-note">${note}</div>` : ""}
      <ul class="nw-drivers">${s.drivers.map((x) => `<li><i class="${x.mix ? "mix" : updn(x.score)}">${x.mix ? "±" : x.score >= 0 ? "▲" : "▼"}</i><span>${esc(x.label)}</span><small>${x.n}</small></li>`).join("") || `<li class="muted">暂无</li>`}</ul>
    </div>`;
  }).join("");

  const rules = Object.fromEntries(d.rules.map((r) => [r.id, r]));
  const onlyDrv = $("#nw-drv").checked;
  const list = d.items.filter((it) => (!nw.asset || it.assets.includes(nw.asset) || it.effects[nw.asset]) && (!onlyDrv || it.drivers.length));
  $("#nw-count").textContent = list.length;
  $("#nw-list").innerHTML = list.slice(0, 150).map((it) => {
    const effs = Object.entries(it.effects).map(([a, es]) => {
      // 一条标题可能同时命中多个因素：同一商品的方向相加；只有“方向不确定”的因素时显示 ±
      const ind = es.every((e) => e.w < 1);
      const sum = es.filter((e) => e.v !== "mix").reduce((t, e) => t + e.v, 0);
      const shown = es.some((e) => e.v !== "mix") ? sum : "mix";
      return `<span class="nw-eff ${effCls(shown)} ${ind ? "ind" : ""}" title="${ind ? "间接影响（标题没有直接提到）" : ""}">${NW_ASSETS[a]} ${effMark(shown === "mix" ? "mix" : Math.max(-2, Math.min(2, shown)))}</span>`;
    }).join("");
    const drv = it.drivers.map((id) => `<span class="badge nw-drv" title="${esc(rules[id].why)}">${esc(rules[id].label)}</span>`).join(" ");
    return `<div class="nw-row">
      <span class="mono muted nw-time">${ago(it.ts)}</span>
      <div class="nw-main"><a href="${esc(safeUrl(it.link))}" target="_blank" rel="noopener" translate="no">${esc(it.title)}</a>
        <div class="nw-tags"><span class="muted" translate="no">${esc(it.source)}</span>${drv}${it.price_report ? `<span class="badge">行情报道</span>` : ""}</div></div>
      <div class="nw-effs">${effs}</div>
    </div>`;
  }).join("") || `<p class="muted">没有符合条件的新闻。</p>`;

  $("#nw-rules").innerHTML = `<tr><th>驱动因素</th><th>通常影响</th><th>传导逻辑</th></tr>` + d.rules.map((r) => `<tr><td><b>${esc(r.label)}</b></td>
    <td class="nowrap">${Object.entries(r.eff).map(([a, v]) => `<span class="nw-eff ${effCls(v)}">${NW_ASSETS[a]} ${effMark(v)}</span>`).join(" ")}</td><td>${esc(r.why)}</td></tr>`).join("");
}

$("#nw-filter").addEventListener("click", (e) => {
  const b = e.target.closest("[data-a]");
  if (!b) return;
  nw.asset = b.dataset.a;
  $$("#nw-filter button").forEach((x) => x.classList.toggle("on", x === b));
  renderNews();
});
$("#nw-assets").addEventListener("click", (e) => {
  const c = e.target.closest("[data-a]");
  if (c) $(`#nw-filter [data-a="${c.dataset.a}"]`).click();
});
$("#nw-drv").addEventListener("change", renderNews);
$("#nw-refresh").addEventListener("click", () => { if (newsView() === "commod") loadNews(true); });
TAB_LOADERS.news = () => { if (newsView() === "commod") loadNews(); };
RERENDER.push(() => nw.data && renderNews());
setInterval(() => { if (!document.hidden && $("#tab-news").classList.contains("active") && newsView() === "commod") loadNews(true); }, 900000);

// ---------------------------------------------------------------- 重大新闻提醒

function renderNewsAlerts(st) {
  $("#na-on").checked = st.enabled;
  $("#na-src").value = String(st.min_src);
  $("#na-assets").innerHTML = Object.entries(NW_ASSETS).map(([a, n]) =>
    `<label class="switch sm"><input type="checkbox" data-na="${a}" ${st.assets.includes(a) ? "checked" : ""}><i></i>${n}</label>`).join("");
  const badge = $("#na-state");
  badge.className = `badge ${st.enabled ? "ok" : ""}`;
  badge.textContent = st.running ? "检查中…" : st.enabled ? "运行中" : "已关闭";
  const bits = [];
  if (st.last_run) bits.push(`上次检查 ${fmtTime(st.last_run).slice(5)}`);
  if (st.enabled && st.next_run) bits.push(`下次约 ${fmtTime(st.next_run).slice(11, 16)}`);
  if (st.last_error) bits.push(`部分失败：${st.last_error}`);
  $("#na-info").innerHTML = bits.map((b) => `<span>${esc(b)}</span>`).join(" · ");
  const h = st.history || [];
  $("#na-hist").innerHTML = h.length
    ? `<div class="section-title">最近提醒</div>` + h.slice(0, 8).map((r) => `<div class="al-row na-row ${r.v > 0 ? "in" : "out"}"><span class="mono">${fmtTime(r.ts).slice(5)}</span>
        <span class="nw-eff ${r.v > 0 ? "up" : "down"}">${NW_ASSETS[r.asset]} ${effMark(r.v)}</span><span class="badge nw-drv">${esc(r.label)}</span>
        <b>${r.sources}</b><a href="${esc(safeUrl(r.link))}" target="_blank" rel="noopener" translate="no">${esc(r.title)}</a></div>`).join("")
    : `<div class="muted">还没有提醒记录。</div>`;
}
async function loadNewsAlerts(body) {
  try { renderNewsAlerts(await api("/api/news/alerts", body ? { method: "POST", body } : {})); } catch (e) { toast(e.message, 4000); }
}
$("#na-on").addEventListener("change", async (e) => {
  await loadNewsAlerts({ enabled: e.target.checked, lang: I18N.lang });
  toast(e.target.checked ? "已开启重大新闻提醒：约 30 秒后检查一次（包括最近 3 小时的新闻）" : "已关闭重大新闻提醒");
});
$("#na-src").addEventListener("change", (e) => loadNewsAlerts({ min_src: +e.target.value }));
$("#na-assets").addEventListener("change", () => loadNewsAlerts({ assets: $$("#na-assets [data-na]").filter((x) => x.checked).map((x) => x.dataset.na) }));
$("#na-test").addEventListener("click", async () => {
  try {
    await api("/api/alerts", { method: "POST", body: { lang: I18N.lang } });
    await api("/api/alerts/test", { method: "POST" });
    toast("已发送测试通知。如果没看到，请在“系统设置 → 通知”里允许“脚本编辑器”的通知", 5000);
  } catch (e) { toast(e.message, 5000); }
});
$("#na-run").addEventListener("click", async () => {
  const b = $("#na-run");
  b.disabled = true;
  try {
    const r = await api("/api/news/alerts/run", { method: "POST" });
    renderNewsAlerts(r);
    toast(r.busy ? "后台正在检查，请稍后再看" : r.found.length ? `发现 ${r.found.length} 条重大新闻，已推送通知` : "没有新的重大新闻");
  } catch (e) { toast(e.message, 4000); }
  b.disabled = false;
});
const _newsLoader = TAB_LOADERS.news;
TAB_LOADERS.news = () => { _newsLoader(); loadNewsAlerts(); };
setInterval(() => { if (!document.hidden && $("#tab-news").classList.contains("active")) loadNewsAlerts(); }, 30000);

// ---------------------------------------------------------------- 新闻倾向事后验证

async function loadAccuracy() {
  let d;
  try { d = await api("/api/news/accuracy"); } catch { return; }
  $("#nv-since").textContent = d.since ? `从 ${d.since} 开始记录 · ${d.days} 天` : "";
  const rate = (hit, n) => (n ? `<b class="${hit / n >= 0.55 ? "up" : hit / n < 0.45 ? "down" : ""}">${Math.round((hit / n) * 100)}%</b> <span class="muted">${hit}/${n}</span>` : `<span class="muted">—</span>`);
  const base = (v) => (v == null ? `<span class="muted">—</span>` : `${Math.round(v * 100)}%`);
  $("#nv-table").innerHTML = d.days
    ? `<tr><th>商品</th><th class="num">记录天数</th><th class="num">偏多 / 偏空信号</th><th class="num">次日方向命中</th><th class="num">5 日方向命中</th><th class="num">基准：次日上涨占比</th><th class="num">基准：5 日上涨占比</th></tr>` +
      d.assets.map((r) => `<tr><td><b>${NW_ASSETS[r.asset]}</b> <span class="mono muted" translate="no">${r.sym}</span></td><td class="num">${r.days}</td><td class="num">${r.signals}</td>
        <td class="num">${rate(r.hit1, r.n1)}</td><td class="num">${rate(r.hit5, r.n5)}</td><td class="num">${base(r.base1)}</td><td class="num">${base(r.base5)}</td></tr>`).join("")
    : `<tr><td class="muted">从今天开始记录：服务每小时保存一次新闻倾向（每天保留一份），过几个交易日这里就会出现统计。</td></tr>`;
}
const _newsLoader3 = TAB_LOADERS.news;
TAB_LOADERS.news = () => { _newsLoader3(); loadAccuracy(); };
