// 量化股神 前端：通用工具、导航、主题、语言、HUD 状态栏、自选监控、后台提醒、设置
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const getVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const state = { watch: [], rows: [], cfg: {}, sort: null };
try { state.sort = JSON.parse(localStorage.getItem("qs-wsort") || "null"); } catch {}
const FLAG_TEXT = { move: "价格异动", volume: "放量", rsi_hi: "RSI 超买", rsi_lo: "RSI 超卖", hi52: "52 周新高", lo52: "52 周新低", above: "升破目标价", below: "跌破目标价", golden: "均线金叉", death: "均线死叉" };

// ---------------------------------------------------------------- 工具函数

const apiLat = [], apiHist = [];
function drawSpark() {
  const svg = document.getElementById("sys-spark");
  if (!svg || apiHist.length < 2) return;
  const max = Math.max(...apiHist, 50), n = apiHist.length;
  const pts = apiHist.map((v, i) => [(i / (n - 1)) * 100, 20 - (v / max) * 17]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  svg.querySelector(".line").setAttribute("d", line);
  svg.querySelector(".area").setAttribute("d", `${line}L100 22L0 22Z`);
  const [lx, ly] = pts[n - 1];
  svg.querySelector("circle").setAttribute("cx", lx); svg.querySelector("circle").setAttribute("cy", ly);
  svg.classList.add("has");
}
async function api(path, opts = {}) {
  const t0 = performance.now();
  const res = await fetch(path, {
    method: opts.method || "GET",
    // X-QS-Client：服务端要求所有写操作带这个请求头（防跨站伪造请求）
    headers: { "X-QS-Client": "1", ...(opts.body ? { "Content-Type": "application/json" } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json();
  const ms = performance.now() - t0;
  apiHist.push(ms);
  if (apiHist.length > 32) apiHist.shift();
  drawSpark();
  apiLat.push(ms);
  if (apiLat.length > 5) apiLat.shift();
  const avg = apiLat.reduce((a, b) => a + b, 0) / apiLat.length;
  $("#sys-lat").textContent = avg >= 1000 ? `${(avg / 1000).toFixed(1)} s` : `${Math.round(avg)} ms`;
  if (!res.ok || data.error) throw new Error(data.error || res.statusText);
  return data;
}

function toast(text, ms = 2500) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}

function fmtNum(n, d = 2) {
  if (n == null || isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (a >= 1e4) return (n / 1e3).toFixed(1) + "K";
  return n.toLocaleString("en-US", { maximumFractionDigits: d });
}
const fmtUsd = (n) => (n == null ? "—" : (n < 0 ? "-$" : "$") + fmtNum(Math.abs(n)));
const fmtPx = (v) => (v == null ? "—" : v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 1 }) : v >= 10 ? v.toFixed(2) : v.toFixed(3));
const pct = (v, d = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const updn = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
function fmtTime(ts, withTime = true) {
  if (!ts) return "—";
  const d = new Date(ts * 1000), p = (x) => String(x).padStart(2, "0");
  const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  return withTime ? `${day} ${p(d.getHours())}:${p(d.getMinutes())}` : day;
}
function ago(ts) {
  if (!ts) return "从未";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "刚刚";
  if (s < 3600) return Math.floor(s / 60) + " 分钟前";
  if (s < 86400) return Math.floor(s / 3600) + " 小时前";
  return Math.floor(s / 86400) + " 天前";
}
function sparkSvg(vals, color, w = 100, h = 28) {
  if (!vals || vals.length < 2) return "";  // 只有一个点（新上市）画不出折线，分母会是 0
  const min = Math.min(...vals), max = Math.max(...vals), rng = max - min || 1;
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / rng) * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="mk-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="0,${h} ${pts} ${w},${h}" fill="${color}" opacity=".12" stroke="none"/><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg>`;
}
function flashVal(el, text) {
  if (!el || el.textContent === text) return;
  const first = el.textContent === "—";
  el.textContent = text;
  if (first) return;
  el.classList.remove("flash-val"); void el.offsetWidth; el.classList.add("flash-val");
}

// ---------------------------------------------------------------- 标签页切换 / 侧边菜单

const TAB_LOADERS = {};
$$(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
function switchTab(name) {
  $$(".tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  $$(".tab").forEach((x) => x.classList.toggle("active", x.id === "tab-" + name));
  const h1 = $(`#tab-${name} h1`);
  moveNavIndicator();
  if (h1 && !REDUCED) { h1.dataset.text = h1.textContent; h1.classList.remove("glitch"); void h1.offsetWidth; h1.classList.add("glitch"); }
  try { localStorage.setItem("qs-tab", name); } catch {}
  TAB_LOADERS[name]?.();
}
function moveNavIndicator() {
  const btn = $(".nav .tabs button.active"), ind = $("#nav-ind");
  if (!btn || !ind) return;
  ind.style.transform = `translateY(${btn.offsetTop}px)`;
  ind.style.height = `${btn.offsetHeight}px`;
  ind.classList.remove("moving"); void ind.offsetWidth; ind.classList.add("moving");
}
$$(".nav .tabs button").forEach((b) => b.addEventListener("click", (e) => {
  if (REDUCED) return;
  const r = b.getBoundingClientRect(), f = document.createElement("span");
  f.className = "nav-flash";
  f.style.left = `${e.clientX - r.left}px`; f.style.top = `${e.clientY - r.top}px`;
  b.appendChild(f);
  setTimeout(() => f.remove(), 600);
}));
function setNavCollapsed(on) {
  $(".app").classList.toggle("nav-collapsed", on);
  try { localStorage.setItem("qs-nav", on ? "1" : "0"); } catch {}
  setTimeout(() => { moveNavIndicator(); if (typeof sm !== "undefined") sm.cy?.resize(); }, 420);
}
$("#nav-collapse").addEventListener("click", () => setNavCollapsed(!$(".app").classList.contains("nav-collapsed")));
try { if (localStorage.getItem("qs-nav") === "1") $(".app").classList.add("nav-collapsed"); } catch {}
window.addEventListener("resize", moveNavIndicator);
document.fonts?.ready.then(moveNavIndicator);
requestAnimationFrame(moveNavIndicator);

document.addEventListener("keydown", (e) => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
  const tab = { 1: "market", 2: "watch", 3: "portfolio", 4: "quant", 5: "smart", 6: "cot", 7: "news", 8: "settings" }[e.key];
  if (tab) switchTab(tab);
});

// ---------------------------------------------------------------- 主题

// 三种外观：蓝色 HUD（深色）/ 黑金（深色 + 金色配色）/ 浅色
const SKINS = ["blue", "gold", "light"];
const currentSkin = () => (document.documentElement.dataset.theme === "light" ? "light" : document.documentElement.dataset.palette === "gold" ? "gold" : "blue");
function setSkin(skin) {
  const el = document.documentElement;
  el.dataset.theme = skin === "light" ? "light" : "dark";
  if (skin === "gold") el.dataset.palette = "gold"; else delete el.dataset.palette;
  try { localStorage.setItem("qs-theme", el.dataset.theme); localStorage.setItem("qs-palette", skin === "gold" ? "gold" : "blue"); } catch {}
  $$("[data-skin]").forEach((b) => b.classList.toggle("on", b.dataset.skin === skin));
  rerenderAll(); // 图表、关系图里用到的颜色是渲染时读取的，要重画
}
$("#theme-toggle").addEventListener("click", () => setSkin(SKINS[(SKINS.indexOf(currentSkin()) + 1) % SKINS.length]));
document.addEventListener("click", (e) => { const b = e.target.closest("[data-skin]"); if (b) setSkin(b.dataset.skin); });
$$("[data-skin]").forEach((b) => b.classList.toggle("on", b.dataset.skin === currentSkin()));

// ---------------------------------------------------------------- 自选监控

async function loadWatch(refresh = true) {
  state.watch = await api("/api/watchlist");
  $("#watch-count").textContent = state.watch.length;
  $("#hud-watch").textContent = `WATCH ${state.watch.length}`;
  if (refresh) await refreshWatch();
  else renderWatch();
}
async function refreshWatch(retry = 0) {
  const b = $("#w-refresh");
  b.disabled = true;
  try {
    state.rows = await api("/api/watchlist/refresh");
    state.rowsAt = Date.now();
    renderWatch(); renderMarquee();
    if (state.rows.some((r) => r.refreshing) && retry < 3) setTimeout(() => refreshWatch(retry + 1), 4000);
  } catch (e) { toast(e.message, 4000); }
  b.disabled = false;
}
function renderWatch() {
  const IN = getVar("--in"), OUT = getVar("--out");
  const bySym = Object.fromEntries(state.rows.map((r) => [r.sym, r]));
  const hits = state.rows.filter((r) => r.flags?.length).length;
  $("#nav-new").hidden = !hits;
  $("#nav-new").textContent = hits;
  if (state.rowsAt) $("#w-upd").textContent = `更新于 ${fmtTime(state.rowsAt / 1000).slice(11)}`;
  // 点表头排序；排序键为空的行（获取失败）排最后
  const sk = state.sort?.key, sd = state.sort?.dir || 1;
  const list = [...state.watch];
  if (sk) list.sort((a, b) => {
    const va = sk === "sym" ? a.sym : bySym[a.sym]?.[sk], vb = sk === "sym" ? b.sym : bySym[b.sym]?.[sk];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sd;
  });
  const th = (key, text, cls = "", title = "") => `<th class="${cls} sortable ${sk === key ? (sd > 0 ? "asc" : "desc") : ""}" data-sort="${key}" ${title ? `title="${title}"` : ""}>${text}</th>`;
  $("#watch-table").innerHTML = state.watch.length
    ? `<tr>${th("sym", "代码")}<th>名称</th>${th("price", "价格", "num")}${th("chg1d", "1D", "num")}${th("chg1w", "1W", "num")}${th("chg1m", "1M", "num")}${th("rs1m", "vs SPX · 1M", "num", "相对强弱：1 个月涨跌幅减去标普 500 同期涨跌幅（百分点）")}${th("vol_ratio", "成交量 / 20 日均量", "num", "盘中按交易时段进度折算成全天预估量")}${th("rsi14", "RSI", "num", "14 日相对强弱指数：≥70 超买，≤30 超卖")}${th("pos52", "52 周区间", "", "现价在 52 周最低价与最高价之间的位置（按收盘价）")}<th>2 个月走势</th><th class="num">阈值</th><th>状态</th><th></th></tr>` +
      list.map((w) => {
        const r = bySym[w.sym] || {};
        const flags = (r.flags || []).map((f) => `<span class="badge q-flag ${f}">${FLAG_TEXT[f] || f}</span>`).join(" ");
        return `<tr class="${r.flags?.length ? "q-hit" : ""}" data-sym="${esc(w.sym)}" title="点击查看详情"><td><b class="mono">${esc(w.sym)}</b></td><td>${esc(w.label || r.name || "")}</td>
          <td class="num mono">${r.price != null ? fmtPx(r.price) : "—"} <span class="muted">${esc(r.currency || "")}</span></td>
          <td class="num mk-chg ${updn(r.chg1d)}">${pct(r.chg1d)}</td><td class="num mk-chg ${updn(r.chg1w)}">${pct(r.chg1w)}</td><td class="num mk-chg ${updn(r.chg1m)}">${pct(r.chg1m)}</td>
          <td class="num mono ${updn(r.rs1m)}">${r.rs1m != null ? `${r.rs1m >= 0 ? "+" : ""}${r.rs1m.toFixed(1)} pt` : "—"}</td>
          <td class="num">${r.vol_ratio != null ? `<b class="${r.vol_ratio >= (w.vol_mult || 99) ? "up" : ""}">×${r.vol_ratio.toFixed(2)}</b> <span class="muted">${fmtNum(r.volume)}</span>${r.vol_projected ? `<sup class="muted" title="盘中按交易时段进度折算成全天预估量">*</sup>` : ""}` : `<span class="muted">—</span>`}</td>
          <td class="num mono ${r.rsi14 >= 70 ? "down" : r.rsi14 <= 30 ? "up" : ""}">${r.rsi14 != null ? r.rsi14.toFixed(0) : "—"}</td>
          <td>${r.pos52 != null ? `<div class="q-r52" title="${fmtPx(r.lo52)} – ${fmtPx(r.hi52)}"><i style="left:${r.pos52.toFixed(1)}%"></i></div>` : `<span class="muted">—</span>`}</td>
          <td class="spark-td">${sparkSvg(r.spark, (r.chg1m ?? 0) >= 0 ? IN : OUT, 120, 30)}</td>
          <td class="num muted" translate="no">±${w.move_pct || 0}% · ×${w.vol_mult || 0}${w.rsi_alert !== false ? " · RSI" : ""}${w.hi52_alert !== false ? " · 52W" : ""}${w.ma_alert !== false ? " · MA" : ""}${w.above ? ` · ≥${fmtPx(w.above)}` : ""}${w.below ? ` · ≤${fmtPx(w.below)}` : ""}</td>
          <td>${r.error ? `<span class="badge no" title="${esc(r.error)}">获取失败</span>` : flags || `<span class="muted">正常</span>`}${r.stale ? ` <span class="badge">缓存</span>` : ""}</td>
          <td class="row-acts"><button type="button" class="small ghost" data-wedit="${esc(w.sym)}">修改</button><button type="button" class="small ghost" data-wdel="${esc(w.sym)}">删除</button></td></tr>`;
      }).join("")
    : `<tr><td class="muted">自选列表是空的，在上面添加代码。</td></tr>`;
}
$("#watch-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { sym: $("#w-sym").value, label: $("#w-label").value, move_pct: +$("#w-move").value, vol_mult: +$("#w-vol").value,
    rsi_alert: $("#w-rsi").checked, hi52_alert: $("#w-52").checked, ma_alert: $("#w-ma").checked, above: +$("#w-above").value || 0, below: +$("#w-below").value || 0 };
  try {
    state.watch = await api("/api/watchlist", { method: "POST", body });
    $("#w-sym").value = $("#w-label").value = $("#w-above").value = $("#w-below").value = "";
    toast("已保存");
  } catch (err) { toast(err.message, 4000); }
  await loadWatch();
});
$("#watch-table").addEventListener("click", async (e) => {
  const sortTh = e.target.closest("th[data-sort]");
  if (sortTh) {
    const key = sortTh.dataset.sort;
    const first = key === "sym" ? 1 : -1; // 代码列先升序，数字列先降序；再点反向，第三次取消排序
    state.sort = state.sort?.key !== key ? { key, dir: first } : state.sort.dir === first ? { key, dir: -first } : null;
    try { localStorage.setItem("qs-wsort", JSON.stringify(state.sort)); } catch {}
    return renderWatch();
  }
  const del = e.target.closest("[data-wdel]"), ed = e.target.closest("[data-wedit]");
  if (del && confirm("从自选列表删除？")) {
    await api(`/api/watchlist?sym=${encodeURIComponent(del.dataset.wdel)}`, { method: "DELETE" });
    state.rows = state.rows.filter((r) => r.sym !== del.dataset.wdel);
    loadWatch(false);
  }
  if (ed) {
    const w = state.watch.find((x) => x.sym === ed.dataset.wedit);
    $("#w-sym").value = w.sym; $("#w-label").value = w.label || ""; $("#w-move").value = w.move_pct; $("#w-vol").value = w.vol_mult;
    $("#w-rsi").checked = w.rsi_alert !== false; $("#w-52").checked = w.hi52_alert !== false; $("#w-ma").checked = w.ma_alert !== false;
    $("#w-above").value = w.above || ""; $("#w-below").value = w.below || "";
    $("#w-sym").focus();
  }
});
$("#w-refresh").addEventListener("click", () => refreshWatch());
TAB_LOADERS.watch = () => { loadAlerts(); loadDigest(); if (!state.rowsAt || Date.now() - state.rowsAt > 120000) refreshWatch(); };
setInterval(() => { if (!document.hidden) refreshWatch(); }, 300000);

// 导出 / 导入：自选列表 + 13F 基金列表（JSON，不含 API Key），用于备份或在多台电脑之间同步
$("#w-export").addEventListener("click", async () => {
  try {
    const d = await api("/api/watchlist/export");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    a.download = `quantriel-backup-${fmtTime(Date.now() / 1000, false)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(e.message, 4000); }
});
$("#w-import").addEventListener("click", () => $("#w-file").click());
$("#w-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  let body;
  try { body = JSON.parse(await f.text()); } catch { return toast("不是有效的 JSON 文件", 4000); }
  if (!Array.isArray(body?.watchlist)) return toast("导入文件格式不正确", 4000);
  if (!confirm(`从 ${f.name} 导入 ${body.watchlist.length} 个品种到自选列表？`)) return;
  const replace = confirm("替换本机现有的自选列表？\n「确定」= 替换；「取消」= 只添加本机没有的品种。\n持仓和基金列表只会添加，不会被替换。");
  try {
    const r = await api("/api/watchlist/import", { method: "POST", body: { ...body, replace } });
    toast((replace ? `已替换：现有 ${r.watchlist} 个品种` : `已添加 ${r.added} 个品种，共 ${r.watchlist} 个`) + (r.skipped ? `（跳过 ${r.skipped} 条格式不正确的记录）` : ""));
    await loadWatch();
    if (typeof loadManagers === "function" && r.managers_added) loadManagers().catch(() => {});
  } catch (err) { toast(err.message, 5000); }
});

// 每日摘要通知
function renderDigest(st) {
  $("#dg-on").checked = st.enabled;
  if (document.activeElement !== $("#dg-time")) $("#dg-time").value = st.time;
  const bits = [];
  if (st.last?.ts) bits.push(`上次 ${fmtTime(st.last.ts).slice(5)}`);
  if (st.last_error) bits.push(`失败：${st.last_error}`);
  $("#dg-info").textContent = bits.join(" · ");
  $("#dg-info").title = st.last?.text || "";
}
async function loadDigest(body) {
  try { renderDigest(await api("/api/digest", body ? { method: "POST", body } : {})); } catch (e) { toast(e.message, 4000); }
}
$("#dg-on").addEventListener("change", async (e) => {
  const t = $("#dg-time").value;
  await loadDigest({ enabled: e.target.checked, lang: I18N.lang, ...(/^\d\d:\d\d$/.test(t) ? { time: t } : {}) });  // 时间框被清空时不传，沿用服务端保存的时间
  toast(e.target.checked ? `已开启每日摘要：每天 ${$("#dg-time").value || "08:30"} 推送` : "已关闭每日摘要");
});
$("#dg-time").addEventListener("change", (e) => e.target.value && loadDigest({ time: e.target.value }));
$("#dg-run").addEventListener("click", async () => {
  const b = $("#dg-run");
  b.disabled = true;
  try {
    await api("/api/digest", { method: "POST", body: { lang: I18N.lang } });
    const r = await api("/api/digest/run", { method: "POST" });
    renderDigest(r);
    toast(`已发送：${r.sent.text}`, 6000);
  } catch (e) { toast(e.message, 5000); }
  b.disabled = false;
});

// ---------------------------------------------------------------- 后台异动提醒（服务端定时检查 + macOS 通知）

function renderAlerts(st) {
  $("#al-on").checked = st.enabled;
  $("#al-int").value = String(st.interval);
  $("#al-sound").checked = st.sound !== false;
  const badge = $("#al-state");
  badge.className = `badge ${st.enabled ? "ok" : ""}`;
  badge.textContent = st.running ? "检查中…" : st.enabled ? "运行中" : "已关闭";
  const bits = [];
  if (st.last_run) bits.push(`上次检查 ${fmtTime(st.last_run).slice(5)}`);
  if (st.enabled && st.next_run) bits.push(`下次约 ${fmtTime(st.next_run).slice(11, 16)}`);
  if (st.skipped?.length) bits.push(`休市未更新，跳过 ${st.skipped.length} 个品种`);
  if (st.last_error) bits.push(`部分失败：${st.last_error}`);
  $("#al-info").innerHTML = bits.map((b) => `<span>${esc(b)}</span>`).join(" · ");
  const h = st.history || [];
  $("#al-hist").innerHTML = h.length
    ? `<div class="section-title">最近提醒</div>` + h.slice(0, 8).map((r) => `<div class="al-row ${r.chg1d >= 0 ? "in" : "out"}"><span class="mono">${fmtTime(r.ts).slice(5)}</span><b class="mono">${esc(r.sym)}</b>
        <span class="badge q-flag ${r.type}">${FLAG_TEXT[r.type] || r.type}</span><b class="mk-chg ${updn(r.chg1d)}">${pct(r.chg1d)}</b>
        <span class="muted">${fmtPx(r.price)} ${esc(r.currency || "")}${r.type === "volume" && r.vol_ratio ? ` · ×${r.vol_ratio.toFixed(1)}` : ""}${r.type?.startsWith("rsi") && r.rsi14 != null ? ` · RSI ${r.rsi14.toFixed(0)}` : ""}${(r.type === "above" || r.type === "below") && r.target != null ? ` · ${r.type === "above" ? "≥" : "≤"}${fmtPx(r.target)}` : ""}</span></div>`).join("")
    : `<div class="muted">还没有提醒记录。</div>`;
}
async function loadAlerts(body) {
  try { renderAlerts(await api("/api/alerts", body ? { method: "POST", body } : {})); } catch (e) { toast(e.message, 4000); }
}
$("#al-on").addEventListener("change", async (e) => {
  await loadAlerts({ enabled: e.target.checked, lang: I18N.lang, interval: +$("#al-int").value });
  toast(e.target.checked ? "已开启后台提醒：约 30 秒后做第一次检查" : "已关闭后台提醒");
});
$("#al-int").addEventListener("change", (e) => loadAlerts({ interval: +e.target.value }));
$("#al-sound").addEventListener("change", (e) => loadAlerts({ sound: e.target.checked }));
$("#al-test").addEventListener("click", async () => {
  try {
    await api("/api/alerts", { method: "POST", body: { lang: I18N.lang } });
    await api("/api/alerts/test", { method: "POST" });
    toast("已发送测试通知。如果没看到，请在“系统设置 → 通知”里允许“脚本编辑器”的通知", 5000);
  } catch (e) { toast(e.message, 5000); }
});
$("#al-run").addEventListener("click", async () => {
  const b = $("#al-run");
  b.disabled = true;
  try {
    const r = await api("/api/alerts/run", { method: "POST" });
    renderAlerts(r);
    toast(r.busy ? "后台正在检查，请稍后再看" : r.found.length ? `发现 ${r.found.length} 条新异动，已推送通知` : "没有新的异动");
  } catch (e) { toast(e.message, 4000); }
  b.disabled = false;
});
setInterval(() => { if (!document.hidden && $("#tab-watch").classList.contains("active")) loadAlerts(); }, 30000);

// ---------------------------------------------------------------- 设置 / 数据源状态

const CFG_FIELDS = { sec_email: "sec", fred_key: "fred", eia_key: "eia" };
async function loadConfig() {
  const c = (state.cfg = await api("/api/config"));
  for (const [k, id] of Object.entries(CFG_FIELDS)) {
    const el = $(`#cfg-${id}`);
    el.className = `badge ${c[k] ? "ok" : "no"}`;
    el.textContent = c[k] ? "已配置" : "未配置";
    const del = $(`[data-clear="${k}"]`);
    if (del) del.hidden = !c[k] || (c.env || []).includes(k); // 来自环境变量的 Key 不能在页面上删除
  }
  renderSources();
  return c;
}
async function renderSources() {
  let st = {};
  try { st = await api("/api/status"); } catch {}
  const y = st.yahoo || {}, cnn = st.cnn || {};
  const src = [
    ["Yahoo", y.ok !== false, y.cooldown ? "限流冷却" : "约 15 分钟延迟", y.cooldown],
    ["CNN F&G", cnn.ok === true, cnn.ok === false ? "不可用 · 用合成指数" : cnn.ok ? "非官方" : "待检测", cnn.ok === false],
    ["SEC EDGAR", !!state.cfg.sec_email, state.cfg.sec_email ? "已配置邮箱" : "需要邮箱", false],
    ["CFTC COT", true, "每周", false],
  ];
  $("#src-status").innerHTML = src.map(([n, ok, t, weak]) =>
    `<div class="src-row" title="${esc(n)} · ${esc(t)}"><i class="${ok ? "" : "off"}"></i><span class="src-name" translate="no">${n}</span><span class="sig ${ok ? (weak ? "weak" : "") : "off"}"><s></s><s></s><s></s></span><small>${t}</small></div>`).join("");
}
$("#cfg-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  for (const k of Object.keys(CFG_FIELDS)) {
    const el = $(`#cfg-${k}`);
    if (el.value.trim()) body[k] = el.value;
  }
  try {
    await api("/api/config", { method: "POST", body });
    for (const k of Object.keys(CFG_FIELDS)) $(`#cfg-${k}`).value = "";
    await loadConfig();
    toast("已保存");
  } catch (err) { toast(err.message, 4000); }
});
// 删除已保存的邮箱 / Key（发空值给服务端即删除）
$("#cfg-form").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-clear]");
  if (!b) return;
  e.preventDefault();
  if (!confirm("从本机删除这项设置？")) return;
  try {
    await api("/api/config", { method: "POST", body: { [b.dataset.clear]: "" } });
    await loadConfig();
    toast("已删除");
  } catch (err) { toast(err.message, 4000); }
});
$("#legal-open").addEventListener("click", (e) => {
  e.preventDefault();
  switchTab("settings");
  setTimeout(() => $("#legal").scrollIntoView({ behavior: "smooth", block: "start" }), 60);
});
TAB_LOADERS.settings = () => loadConfig();

// ---------------------------------------------------------------- HUD 状态栏

function renderMarquee() {
  const hits = state.rows.filter((r) => r.flags?.length);
  const items = hits.length
    ? hits.map((r) => `<span class="mq ${r.chg1d >= 0 ? "in" : "out"}">◆ ${esc(r.label || r.sym)} ${FLAG_TEXT[r.flags[0]]} <b>${pct(r.chg1d)}</b> · ${fmtPx(r.price)}</span>`)
    : [`<span class="mq">◆ SYSTEM READY · 自选 ${state.watch.length} 个品种</span>`, `<span class="mq">◆ 行情约延迟 15 分钟 · 不构成投资建议</span>`, `<span class="mq">◆ 快捷键 1–8 切换页面 · / 查看代码</span>`];
  const html = items.join("");
  $("#marquee-track").innerHTML = html + html; // 两份首尾相接，无缝循环
  $("#marquee-track").style.animationDuration = `${Math.max(30, items.length * 9)}s`;
}
$("#marquee").addEventListener("click", () => switchTab("watch"));

const bootAt = Date.now();
function zoned(tz) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false }).formatToParts(new Date());
  const g = (t) => parts.find((p) => p.type === t)?.value;
  return { hm: `${g("hour") === "24" ? "00" : g("hour")}:${g("minute")}`, mins: (+g("hour") % 24) * 60 + +g("minute"), wd: g("weekday") };
}
function tickClock() {
  const p = (x) => String(x).padStart(2, "0");
  const up = Math.floor((Date.now() - bootAt) / 1000);
  $("#sys-up").textContent = `${p(Math.floor(up / 3600))}:${p(Math.floor(up / 60) % 60)}:${p(up % 60)}`;
  const ny = zoned("America/New_York"), hk = zoned("Asia/Hong_Kong");
  $("#clock").textContent = `NY ${ny.hm} · HK ${hk.hm}`;
  // 只按常规交易时段判断，不含节假日
  const wk = !["Sat", "Sun"].includes(ny.wd);
  const open = wk && ny.mins >= 570 && ny.mins < 960;
  const pre = wk && ny.mins >= 240 && ny.mins < 570;
  const after = wk && ny.mins >= 960 && ny.mins < 1200;
  const t = open ? "OPEN" : pre ? "PRE" : after ? "AFTER" : "CLOSED";
  const b = $("#hb-mkt b");
  if (b.textContent !== t) { b.textContent = t; b.className = open ? "up" : ""; }
}
async function loadTicker() {
  try {
    const list = await api("/api/ticker");
    const short = { "^GSPC": "SPX", "^HSI": "HSI", "GC=F": "GOLD", "CL=F": "WTI", "^VIX": "VIX" };
    const c = (v) => (v == null ? "" : `<i class="chg ${v >= 0 ? "up" : "down"}">${v >= 0 ? "▲" : "▼"}${Math.abs(v).toFixed(1)}%</i>`);
    $("#ticker").innerHTML = list.map((x) => `<span>${short[x.sym] || x.sym} <b>${fmtPx(x.price)}</b>${c(x.chg1d)}</span>`).join("");
  } catch {}
  const beat = $("#hb-beat");
  beat.style.setProperty("--beat", "60s");
  beat.classList.remove("run"); void beat.offsetWidth; beat.classList.add("run");
}
tickClock(); setInterval(tickClock, 1000);
setInterval(() => { if (!document.hidden) loadTicker(); }, 60000);

// 启动自检动画：每个浏览器会话只播放一次，可点击跳过
const boot = (() => {
  let show = false;
  try { show = !sessionStorage.getItem("qs-booted") && !REDUCED; } catch {}
  const el = $("#boot"), t0 = performance.now();
  const finish = () => { el.classList.add("done"); try { sessionStorage.setItem("qs-booted", "1"); } catch {} setTimeout(() => (el.hidden = true), 600); };
  if (show) { el.hidden = false; el.addEventListener("click", finish); }
  return {
    line(text, status = "OK") {
      if (!show) return;
      const dots = ".".repeat(Math.max(3, 34 - text.length));
      $("#boot-lines").insertAdjacentHTML("beforeend", `<div>${esc(text)} ${dots} <b>${esc(status)}</b></div>`);
    },
    async end() {
      if (!show) return;
      await new Promise((r) => setTimeout(r, Math.max(0, 900 - (performance.now() - t0))));
      this.line("ALL SYSTEMS NOMINAL", "READY");
      setTimeout(finish, 250);
    },
  };
})();
boot.line("INITIALIZING CORE SYSTEMS");

// ---------------------------------------------------------------- 语言

const RERENDER = [];
function rerenderAll() {
  renderWatch(); renderMarquee(); renderSources();
  RERENDER.forEach((f) => f());
  moveNavIndicator();
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-lang]");
  if (!b) return;
  applyLang(b.dataset.lang);
  rerenderAll();
  api("/api/alerts", { method: "POST", body: { lang: b.dataset.lang } }).catch(() => {});
});

// ---------------------------------------------------------------- 启动

window.addEventListener("DOMContentLoaded", async () => {
  i18nInit();
  let tab = "market";
  try { tab = localStorage.getItem("qs-tab") || "market"; } catch {}
  // 先拿到设置和自选列表（都是本地数据，很快），再恢复上次的页面；否则聪明钱页会误报“未填邮箱”，自选页会先闪一下空列表
  const [cfg] = await Promise.all([loadConfig().catch(() => ({})), loadWatch(false).catch(() => {})]);
  if (tab !== "market" && document.getElementById(`tab-${tab}`)?.classList.contains("tab")) switchTab(tab);
  else TAB_LOADERS.market?.();
  boot.line("LINK YAHOO FINANCE", "OK");
  boot.line("LINK SEC EDGAR", cfg.sec_email ? "OK" : "NO EMAIL");
  boot.line("LINK CFTC SOCRATA", "OK");
  loadTicker();
  boot.line("WATCHLIST TARGETS", `${state.watch.length} LOCKED`);
  boot.end();
  renderMarquee();
  loadAlerts();
  if (tab !== "watch") refreshWatch(); // 自选页的 loader 已经刷新过
});

// ---------------------------------------------------------------- 服务：代码更新提示、一键重启
// 每 15 秒看一下服务端代码 / 界面文件的修改时间：改了 server.py 提示重启，改了界面文件提示刷新

const svc = { info: null, pageStatic: null, restarting: false };
async function checkVersion() {
  if (document.hidden && svc.info) return;
  let v;
  try { v = await api("/api/version"); } catch { return; }
  svc.info = v;
  if (v.version) $(".brand-sub i").textContent = "v" + v.version.replace(/\.0$/, "");  // 侧栏显示服务端版本号
  if (svc.pageStatic == null) svc.pageStatic = v.static_mtime;
  const bar = $("#upd-bar"), msgs = [];
  if (v.server_mtime > v.started + 1) msgs.push(`<span>服务端代码已更新，重启后生效</span><button type="button" class="small primary" data-svc="restart">重启服务</button>`);
  if (v.static_mtime > svc.pageStatic) msgs.push(`<span>界面文件已更新</span><button type="button" class="small ghost" data-svc="reload">刷新页面</button>`);
  if (!svc.restarting) { bar.innerHTML = msgs.join(""); bar.hidden = !msgs.length; }
  renderSvc();
}
function renderSvc() {
  const v = svc.info;
  if (!v) return;
  const os = v.platform === "darwin" ? "macOS" : v.platform.startsWith("win") ? "Windows" : v.platform;
  $("#svc-info").innerHTML = `<tr><td>版本</td><td class="mono" translate="no">v${esc(v.version || "1.0")}</td></tr>
    <tr><td>地址</td><td class="mono" translate="no">http://127.0.0.1:${v.port}</td></tr>
    <tr><td>启动于</td><td>${fmtTime(v.started)}</td></tr>
    <tr><td>开机自启</td><td>${v.autostart ? `<span class="badge ok">已开启</span>` : `<span class="badge">未开启</span> <span class="muted">双击项目文件夹里的“Enable-Autostart-${os === "Windows" ? "Windows.bat" : "macOS.command"}”</span>`}</td></tr>
    <tr><td>日志</td><td class="mono" translate="no">${esc(v.log)}</td></tr>`;
}
async function restartService() {
  const old = svc.info?.started;
  svc.restarting = true;
  $("#upd-bar").innerHTML = `<span>正在重启服务…</span>`;
  $("#upd-bar").hidden = false;
  try { await api("/api/restart", { method: "POST" }); } catch {}
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 750));
    try { const v = await api("/api/version"); if (v.started !== old) return location.reload(); } catch {}
  }
  svc.restarting = false;
  $("#upd-bar").innerHTML = `<span>服务没有在 30 秒内恢复，请查看日志或手动启动</span>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-svc]");
  if (b?.dataset.svc === "restart") restartService();
  if (b?.dataset.svc === "reload") location.reload();
});
$("#svc-restart").addEventListener("click", () => { if (confirm("重启服务？大约几秒钟，页面会自动刷新。")) restartService(); });
checkVersion();
setInterval(checkVersion, 15000);
