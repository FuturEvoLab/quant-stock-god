// 说明页面（关于 / 免责 / 隐私 / 日本法令）：按 ?lang=、应用里选的语言或浏览器语言显示对应段落，配色跟应用一致
(function () {
  const get = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
  const ok = ["ja", "zh", "en"];
  const q = new URLSearchParams(location.search).get("lang");
  const nav = (navigator.language || "").slice(0, 2);
  let lang = ok.includes(q) ? q : ok.includes(get("qs-lang")) ? get("qs-lang") : ok.includes(nav) ? nav : "en";
  const root = document.documentElement;
  if (get("qs-theme") === "light") root.dataset.theme = "light";
  if (get("qs-palette") === "gold") root.dataset.palette = "gold";
  function show(l) {
    lang = l;
    root.lang = l === "zh" ? "zh-CN" : l;
    document.querySelectorAll("article[data-lang]").forEach((a) => { a.hidden = a.dataset.lang !== l; });
    document.querySelectorAll("[data-set-lang]").forEach((b) => b.classList.toggle("on", b.dataset.setLang === l));
    // 页内链接带上语言，换页后保持同一种语言
    document.querySelectorAll("article a[href*='.html'], .legal-head a.brand, article .back a").forEach((a) => {
      const u = new URL(a.getAttribute("href"), location.href);
      u.searchParams.set("lang", l);
      a.href = (u.pathname.split("/").pop() || "./") + u.search;
    });
  }
  document.addEventListener("DOMContentLoaded", () => {
    show(lang);
    document.querySelectorAll("[data-set-lang]").forEach((b) => b.addEventListener("click", () => { set("qs-lang", b.dataset.setLang); show(b.dataset.setLang); }));
  });
})();
