// 量化股神 — 在页面渲染前应用主题 / 配色，避免闪烁（单独成文件：安全策略禁止内联脚本）
  // 尽早应用主题，避免闪烁；默认 HUD 深色主题
  let theme = "dark";
  try { theme = localStorage.getItem("qs-theme") || "dark"; } catch {}
  // 配色：blue（蓝色 HUD，默认）/ gold（黑金），只在深色主题下生效
  try { if (localStorage.getItem("qs-palette") === "gold") document.documentElement.dataset.palette = "gold"; } catch {}
  document.documentElement.dataset.theme = theme;
