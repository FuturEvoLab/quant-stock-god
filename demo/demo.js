// 量化股神 — 在线演示版（GitHub Pages）专用：没有后端，页面的 /api/ 请求由这里用预先录好的数据快照回答。
// 只在 tools/build_demo.py 生成的 docs/ 里加载，本地运行的完整版不会用到这个文件。
// 链接参数：?lang=en|ja|zh 指定界面语言，?tab=market|watch|portfolio|quant|smart|cot|news|settings 打开某个页面，
//          ?view=tech 新闻页切到 AI·科技股，?skin=gold|light 换配色，?clean=1 不显示演示提示条（截图用）
(function () {
  const REPO = "https://github.com/FuturEvoLab/quant-stock-god";
  // 页面里的时间按“录制快照的那一刻”走（加上打开页面后经过的时间），否则快照过一天后，
  // 新闻页会提示“数据较旧”、各处显示“x 天前”。快照日期在底部提示条里标明。
  const generated = +document.currentScript.dataset.generated || 0;
  if (generated) {
    const realNow = Date.now.bind(Date), shift = Math.max(0, realNow() - (generated + 60) * 1000);
    Date.now = () => realNow() - shift;
  }
  const params = new URLSearchParams(location.search);
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
  if (["en", "ja", "zh"].includes(params.get("lang"))) set("qs-lang", params.get("lang"));
  if (params.get("tab")) set("qs-tab", params.get("tab"));
  if (params.get("view") === "tech") set("qs-news-view", "tech");
  const skin = params.get("skin");
  if (skin === "gold") { set("qs-theme", "dark"); set("qs-palette", "gold"); document.documentElement.dataset.theme = "dark"; document.documentElement.dataset.palette = "gold"; }
  if (skin === "light") { set("qs-theme", "light"); set("qs-palette", "blue"); document.documentElement.dataset.theme = "light"; delete document.documentElement.dataset.palette; }
  if (params.get("clean") === "1") try { sessionStorage.setItem("qs-booted", "1"); } catch {} // 截图时跳过启动动画

  let lang = "en";
  try { lang = localStorage.getItem("qs-lang") || "en"; } catch {}
  const T = {
    en: { bar: "Online demo: a recorded data snapshot. Searching, settings and alerts are disabled.", get: "Get the full version (runs locally) ↗",
          err: "The online demo only contains a recorded snapshot and cannot fetch new data or change settings. Download the full version to run it locally." },
    ja: { bar: "オンラインデモ：記録済みのデータスナップショットです。検索・設定・通知は使えません。", get: "フル版をダウンロード（ローカルで実行）↗",
          err: "オンラインデモには記録済みのスナップショットしか含まれておらず、新しいデータの取得や設定の変更はできません。フル版をダウンロードしてローカルで実行してください。" },
    zh: { bar: "在线演示版：数据为录制好的快照，不能搜索、修改设置或推送提醒。", get: "下载完整版（本地运行）↗",
          err: "在线演示版只包含录制好的数据快照，不能获取新数据或修改设置。完整功能请下载到本地运行。" },
  }[lang] || {};

  const base = document.currentScript.src.replace(/demo\.js.*$/, "");
  let data = {};
  const ready = fetch(base + "demo-data.json").then((r) => r.json()).then((d) => (data = d)).catch(() => {});
  const realFetch = window.fetch.bind(window);
  const reply = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

  window.fetch = async (input, opts = {}) => {
    const u = new URL(typeof input === "string" ? input : input.url, location.href);
    const at = u.pathname.indexOf("/api/");
    if (at < 0) return realFetch(input, opts);
    await ready;
    if ((opts.method || "GET").toUpperCase() !== "GET") return reply({ error: T.err }, 400);
    const path = u.pathname.slice(at);
    let key = path;
    if (path === "/api/detail") key = `detail|${(u.searchParams.get("sym") || "").toUpperCase()}`;
    if (path === "/api/corr") key = `corr|${u.searchParams.get("days") || 60}`;
    if (path === "/api/backtest") key = `backtest|${(u.searchParams.get("sym") || "").toUpperCase()}|${u.searchParams.get("strategy") || "ma_cross"}`;  // 演示版只录了一个区间
    if (path === "/api/forecast") key = `forecast|${(u.searchParams.get("sym") || "").toUpperCase()}`;
    if (path === "/api/version") return reply({ ...data[key], started: Math.floor(Date.now() / 1000) }); // 不显示“代码已更新”提示条
    return key in data ? reply(data[key]) : reply({ error: T.err }, 400);
  };

  document.addEventListener("DOMContentLoaded", () => {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = base + "demo.css";
    document.head.appendChild(style);
    if (params.get("clean") === "1") return;
    const bar = document.createElement("div");
    bar.className = "demo-bar";
    bar.setAttribute("translate", "no"); // 文案已按界面语言给出，不再经过自动翻译
    bar.innerHTML = `<b>DEMO</b><span>${T.bar}</span><span class="demo-when"></span><a href="${REPO}" target="_blank" rel="noopener">${T.get}</a>`;
    document.body.append(bar);
    ready.then(() => { // 标出快照日期，免得把旧数据当成实时行情
      if (data.generated) bar.querySelector(".demo-when").textContent = "📅 " + new Date(data.generated * 1000).toISOString().slice(0, 10);
    });
  });
})();
