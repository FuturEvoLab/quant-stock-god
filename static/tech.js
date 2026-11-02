// 量化股神 — AI / 科技股新闻：公司 + 话题两类标签，按公司汇总新闻倾向，并和股价 1D / 1W 对照

const tn = { data: null, at: 0, topic: "", co: "", view: "commod" };
const toneCls = (t) => (t > 0 ? "up" : t < 0 ? "down" : "flat");
const toneMark = (t) => (t > 0 ? "+" : t < 0 ? "−" : "");

async function loadTech(force = false) {
  if (!force && tn.data && Date.now() - tn.at < 600000) return renderTech();
  if (!tn.data) $("#tn-cos").innerHTML = `<div class="sm-loading"><div class="scanbar"><i></i></div><p>正在抓取科技新闻…</p></div>`;
  try {
    tn.data = await api("/api/technews");
    tn.at = Date.now();
    renderTech();
  } catch (e) { msgFor("tech", `<div class="err">${esc(e.message)}</div>`); }
}

function renderTech() {
  const d = tn.data;
  if (!d) return;
  const bad = Object.keys(d.errors || {});
  msgFor("tech", (bad.length ? `<div>部分新闻源暂时不可用：${esc(bad.join(", "))}</div>` : "") + staleNote(d));
  $("#tn-upd").textContent = `更新于 ${fmtTime(d.data_ts || d.fetched).slice(5)}`;
  const topics = Object.fromEntries(d.topics.map((t) => [t.id, t]));
  const tag = (id) => { const t = topics[id]; return `<span class="badge tn-tag ${toneCls(t.tone)} ${tn.topic === id ? "on" : ""}" data-topic="${id}">${esc(t.label)}${t.tone ? `<i>${toneMark(t.tone)}</i>` : ""}</span>`; };

  $("#tn-topics").innerHTML = d.topics.filter((t) => t.count).sort((a, b) => b.count - a.count)
    .map((t) => `<span class="badge tn-tag ${toneCls(t.tone)} ${tn.topic === t.id ? "on" : ""}" data-topic="${t.id}">${esc(t.label)}${t.tone ? `<i>${toneMark(t.tone)}</i>` : ""}<small>${t.count}</small></span>`).join("")
    || `<span class="muted">暂无</span>`;

  $("#tn-cos").innerHTML = d.companies.map((c) => {
    const key = c.ticker || c.name, color = c.tone >= 1 ? getVar("--in") : c.tone <= -1 ? getVar("--out") : getVar("--muted");
    const p = c.price;
    return `<div class="card nw-asset tn-co ${tn.co === key ? "on" : ""}" style="--pc:${color}" data-co="${esc(key)}">
      <div class="card-head"><h3 translate="no">${esc(c.name)}</h3><span class="mono muted" translate="no">${esc(c.ticker || "")}</span><span class="spacer"></span>
        ${c.ticker ? `<button type="button" class="small ghost" data-detail="${esc(c.ticker)}">详情</button>` : `<span class="badge">未上市</span>`}</div>
      <div class="nw-meta"><span>相关新闻 ${c.count} 条</span><span>倾向分 <b class="${updn(c.tone)}">${c.tone >= 0 ? "+" : ""}${c.tone.toFixed(1)}</b></span></div>
      <div class="nw-meta"><span>偏正面 <b class="up">${c.pos}</b> · 偏负面 <b class="down">${c.neg}</b></span></div>
      ${p ? `<div class="nw-meta"><span>价格 1D <b class="${updn(p.chg1d)}">${pct(p.chg1d)}</b></span><span>1W <b class="${updn(p.chg1w)}">${pct(p.chg1w)}</b></span></div>` : ""}
      <div class="tn-tags">${c.topics.map(tag).join("")}</div>
    </div>`;
  }).join("") || `<p class="muted">暂无数据</p>`;

  const list = d.items.filter((it) => (!tn.topic || it.topics.includes(tn.topic)) && (!tn.co || it.companies.some((c) => (c.ticker || c.name) === tn.co)));
  $("#tn-count").textContent = list.length;
  $("#tn-filter").innerHTML = [tn.co && `<span class="badge" translate="no">${esc(d.companies.find((c) => (c.ticker || c.name) === tn.co)?.name || tn.co)}</span>`, tn.topic && tag(tn.topic)].filter(Boolean).join(" ")
    + (tn.co || tn.topic ? ` <button type="button" class="small ghost" data-clear>清除筛选</button>` : "");
  $("#tn-list").innerHTML = list.slice(0, 150).map((it) => `<div class="nw-row">
      <span class="mono muted nw-time">${ago(it.ts)}</span>
      <div class="nw-main"><a href="${esc(safeUrl(it.link))}" target="_blank" rel="noopener" translate="no">${esc(it.title)}</a>
        <div class="nw-tags"><span class="muted" translate="no">${esc(it.source)}</span>${it.topics.map(tag).join("")}</div></div>
      <div class="nw-effs">${it.companies.map((c) => `<span class="nw-eff ${toneCls(it.tone)}" translate="no" data-co="${esc(c.ticker || c.name)}">${esc(c.ticker || c.name)}</span>`).join("")}</div>
    </div>`).join("") || `<p class="muted">没有符合条件的新闻。</p>`;
}

$("#nw-tech").addEventListener("click", (e) => {
  const det = e.target.closest("[data-detail]");
  if (det) { e.stopPropagation(); return openDetail(det.dataset.detail); }
  if (e.target.closest("[data-clear]")) { tn.topic = tn.co = ""; return renderTech(); }
  const t = e.target.closest("[data-topic]");
  if (t) { tn.topic = tn.topic === t.dataset.topic ? "" : t.dataset.topic; return renderTech(); }
  const c = e.target.closest("[data-co]");
  if (c) { tn.co = tn.co === c.dataset.co ? "" : c.dataset.co; renderTech(); if (tn.co) $("#tn-list").scrollIntoView({ behavior: "smooth", block: "start" }); }
});

function setNewsView(v, load = true) {
  tn.view = v;
  $$("#nw-view button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  $("#nw-commod").hidden = v !== "commod";
  $("#nw-tech").hidden = v !== "tech";
  $("#nw-msg").innerHTML = "";
  try { localStorage.setItem("qs-news-view", v); } catch {}
  if (!load) return;
  if (v === "tech") loadTech(); else loadNews();
}
$("#nw-view").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (b) setNewsView(b.dataset.v); });
$("#nw-refresh").addEventListener("click", () => { if (tn.view === "tech") loadTech(true); });
setInterval(() => { if (!document.hidden && $("#tab-news").classList.contains("active") && tn.view === "tech") loadTech(true); }, 900000);
const _newsLoader2 = TAB_LOADERS.news;
TAB_LOADERS.news = () => { _newsLoader2(); if (tn.view === "tech") loadTech(); };
// 只恢复上次选的视图，不在页面加载时就抓科技新闻（等打开“新闻影响”页再抓）
try { if (localStorage.getItem("qs-news-view") === "tech") setNewsView("tech", false); } catch {}
RERENDER.push(() => tn.data && renderTech());
