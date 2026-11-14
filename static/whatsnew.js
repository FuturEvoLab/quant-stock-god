// 更新公告：每个版本的发布时间（日本时间）和主要更新内容，三种语言各写一份（不走 i18n 词典，直接按当前语言显示）。
// 新版本时在 RELEASES 最前面加一条，并让 v 和 server.py 的 VERSION 一致（tests/test_core.py 会检查）。
// 完整的技术细节见 CHANGELOG.md。

const RELEASES = [
  {
    v: "1.5.3", date: "2026-11-14", time: "15:54",
    zh: ["新增「更新公告」：版本更新后自动弹出一次本次更新内容，侧栏和设置页可以随时查看全部版本记录。"],
    ja: ["「更新のお知らせ」を追加：アップデート後に一度だけ変更内容を表示します。サイドバーと設定ページからいつでも全バージョンの記録を見られます。"],
    en: ["New “What's new” panel: after an update it opens once with the changes, and the sidebar and Settings page list every release."],
  },
  {
    v: "1.5.2", date: "2026-11-14", time: "15:40",
    zh: [
      "英文名改为 Quantriel（中文「量化股神」、日文「クオンツ株神」不变），GitHub 仓库改名为 FuturEvoLab/quantriel，旧地址自动跳转。",
      "启动脚本改名为 Start-Quantriel；已经设置的开机自启不受影响，不用重装。",
      "导出的备份文件改名为 quantriel-backup-日期.json，旧备份仍可导入。",
      "在线演示改到 futurevolab.github.io/quantriel/（自定义域名 quantriel.futurevolab.com 准备中）。",
    ],
    ja: [
      "英語名を Quantriel に変更しました（日本語名「クオンツ株神」、中国語名「量化股神」はそのまま）。GitHub リポジトリも FuturEvoLab/quantriel に変わり、旧アドレスは自動で転送されます。",
      "起動スクリプトの名前を Start-Quantriel に変更。設定済みの自動起動はそのまま使え、再設定は不要です。",
      "書き出したバックアップのファイル名は quantriel-backup-日付.json に。以前のバックアップも読み込めます。",
      "オンラインデモは futurevolab.github.io/quantriel/ に移動しました（独自ドメイン quantriel.futurevolab.com は準備中）。",
    ],
    en: [
      "The English name is now Quantriel (Japanese クオンツ株神 and Chinese 量化股神 stay). The GitHub repository moved to FuturEvoLab/quantriel; old links redirect.",
      "Launchers are now Start-Quantriel. Autostart you already set up keeps working; no need to reinstall.",
      "Exported backups are named quantriel-backup-DATE.json; older backups still import.",
      "The online demo moved to futurevolab.github.io/quantriel/ (custom domain quantriel.futurevolab.com coming).",
    ],
  },
  {
    v: "1.5.1", date: "2026-11-14", time: "15:24",
    zh: [
      "合并 1.1–1.5 的全部新功能，并新增港股通南向资金卡片；日文名改为「クオンツ株神」。",
      "修复持仓金额：伦敦等按「便士」报价的股票，折算成美元时原来会大 100 倍。",
      "修复安全问题：被拒绝请求的请求体，不会再被当成下一个请求执行。",
      "回测区间完整：200 日均线的预热期不再占用你选的时间范围。",
      "每日摘要、导入、目标价提醒等多处细节修复；自动测试增加到 71 个。",
    ],
    ja: [
      "1.1〜1.5 の新機能をすべて統合し、香港ストックコネクト南向き資金のカードを追加。日本語名を「クオンツ株神」に変更しました。",
      "保有銘柄の金額を修正：ロンドンなどペンス建ての銘柄は、米ドル換算で 100 倍になっていました。",
      "セキュリティの修正：拒否したリクエストの本文が、次のリクエストとして実行されることはなくなりました。",
      "バックテストの期間を修正：200 日移動平均の準備期間が、選んだ期間を食わなくなりました。",
      "毎日のサマリー、インポート、目標価格通知などを細かく修正。自動テストは 71 件になりました。",
    ],
    en: [
      "Merged every feature from 1.1–1.5 and added the HK Stock Connect southbound flows card; the Japanese name is now クオンツ株神.",
      "Portfolio fix: stocks quoted in pence (London and others) were 100× too large after converting to US dollars.",
      "Security fix: the body of a rejected request can no longer run as the next request.",
      "Full backtest range: the 200-day moving-average warm-up no longer eats into the period you chose.",
      "Smaller fixes to the daily digest, import and target-price alerts; 71 automated tests.",
    ],
  },
  {
    v: "1.5.0", date: "2026-11-09",
    zh: [
      "量化实验室新增「预测检验」：历史相似情形、样本外模型、季节性，每一项都和基准并排对比。",
      "品种详情新增快捷按钮：量化实验室、添加到自选、记录持仓。",
      "同一品种的 10 年日线只请求一次，加载更快。",
    ],
    ja: [
      "クオンツラボに「予測の検証」を追加：過去の似た局面、サンプル外モデル、季節性を、すべてベースラインと並べて比較します。",
      "銘柄の詳細にショートカットを追加：クオンツラボ、ウォッチリストに追加、保有を記録。",
      "同じ銘柄の 10 年分の日足は 1 回だけ取得するので、読み込みが速くなりました。",
    ],
    en: [
      "Quant Lab adds a prediction check: similar past setups, an out-of-sample model and seasonality, each shown next to its baseline.",
      "Symbol details gain shortcuts: Quant Lab, add to watchlist, record a position.",
      "Ten years of daily prices are fetched once per symbol, so pages load faster.",
    ],
  },
  {
    v: "1.4.0", date: "2026-11-09",
    zh: [
      "新页面「量化实验室」：在 2 / 5 / 10 年历史上回测买入持有、均线交叉、200 日趋势、RSI 均值回归四种规则，并分前后两段检验是否稳定。",
      "统计区间：用波动率估算 5–60 个交易日后的价格区间和触及目标价的概率，并回看过去一年的实际覆盖率。",
    ],
    ja: [
      "新ページ「クオンツラボ」：2 / 5 / 10 年の履歴で、バイ・アンド・ホールド、移動平均のクロス、200 日トレンド、RSI 逆張りの 4 つのルールをバックテストし、前半と後半に分けて安定性も確かめます。",
      "統計レンジ：ボラティリティから 5〜60 営業日後の価格レンジと目標価格に届く確率を推定し、過去 1 年の実際のカバー率も確認します。",
    ],
    en: [
      "New Quant Lab page: backtest buy-and-hold, moving-average crossover, 200-day trend and RSI mean reversion over 2, 5 or 10 years, with the first and second halves checked separately.",
      "Statistical ranges: volatility-based price ranges 5–60 trading days ahead and the chance of reaching a target, checked against the past year's actual coverage.",
    ],
  },
  {
    v: "1.3.0", date: "2026-11-09",
    zh: [
      "新页面「持仓盈亏」：记录持仓，自动计算市值、累计盈亏和当日盈亏，非美元持仓按汇率折算。",
      "新增均线金叉 / 死叉提醒；顶栏可以直接输入代码查看详情（快捷键 /）。",
    ],
    ja: [
      "新ページ「ポートフォリオ」：保有銘柄を記録すると、評価額、累計損益、当日損益を自動で計算します。米ドル以外は為替レートで換算します。",
      "移動平均のゴールデンクロス / デッドクロス通知を追加。上部バーにコードを入力すると詳細を開けます（ショートカット /）。",
    ],
    en: [
      "New Portfolio page: record positions and see market value, total and daily P&L, with non-USD holdings converted at current rates.",
      "Moving-average golden / death cross alerts; type a symbol in the top bar to open its details (shortcut /).",
    ],
  },
  {
    v: "1.2.0", date: "2026-11-09",
    zh: [
      "每日摘要通知：每天定时推送主要指数、黄金、原油、情绪指数，以及自选里最强和最弱的品种。",
      "自选导出 / 导入（不含 API Key），可以备份或在多台电脑之间同步。",
      "自选表格可以按列排序，新增「相对标普 500」强弱列。",
      "API Key 改为单独存放在 data/secrets.json。",
    ],
    ja: [
      "毎日のサマリー通知：主要指数、金、原油、センチメント指数と、ウォッチリストで最も強い / 弱い銘柄を毎日決まった時刻に通知します。",
      "ウォッチリストの書き出し / 読み込み（API キーは含みません）。バックアップや複数の PC での同期に使えます。",
      "ウォッチリストの表を列ごとに並べ替えられるようになり、「S&P 500 比」の強弱列を追加しました。",
      "API キーは data/secrets.json に分けて保存するようになりました。",
    ],
    en: [
      "Daily digest notification: major indices, gold, oil, the sentiment index and your watchlist's strongest and weakest names, every day at a set time.",
      "Watchlist export / import (no API keys) for backups or syncing between computers.",
      "Sortable watchlist columns and a new relative-strength column versus the S&P 500.",
      "API keys now live separately in data/secrets.json.",
    ],
  },
  {
    v: "1.1.0", date: "2026-11-09",
    zh: [
      "目标价提醒：价格当天穿越你设的价位时推送通知。",
      "市场总览新增跨资产相关性热力图。",
      "加载更快：数据压缩传输、13F 关系图按需加载；多项安全加固。",
    ],
    ja: [
      "目標価格の通知：価格が設定した水準をその日に越えると通知します。",
      "マーケット概況に資産間の相関ヒートマップを追加しました。",
      "読み込みを高速化：データの圧縮転送、13F グラフの遅延読み込み。セキュリティも複数強化しました。",
    ],
    en: [
      "Target-price alerts: get notified when a price crosses your level that day.",
      "A cross-asset correlation heatmap on Market Overview.",
      "Faster loading with compressed transfers and an on-demand 13F graph, plus several security hardening fixes.",
    ],
  },
  {
    v: "1.0.0", date: "2026-11-02", time: "21:33",
    zh: ["首个公开版本：市场总览、自选监控与后台提醒、聪明钱（Form 4 / 13F）、商品持仓（COT / EIA）、新闻影响与事后验证、AI · 科技股新闻；日英中三语和三种配色。"],
    ja: ["最初の公開版：マーケット概況、ウォッチリストとバックグラウンド通知、スマートマネー（Form 4 / 13F）、商品ポジション（COT / EIA）、ニュース影響と事後検証、AI・テック株ニュース。日英中の 3 言語と 3 種類の配色。"],
    en: ["First public release: market overview, watchlist with background alerts, smart money (Form 4 / 13F), commodity positioning (COT / EIA), news impact with an after-the-fact check, and AI & tech news — in English, Japanese and Chinese with three color schemes."],
  },
];

const WN_SEEN = "qs-seen-version";
const verNum = (v) => v.split(".").map(Number).reduce((a, x) => a * 1000 + x, 0);
const wnItems = (r) => r[I18N.lang] || r.en;
const wnWhen = (r) => `${r.date}${r.time ? " " + r.time + " JST" : ""}`;

function releaseHtml(r, isNew) {
  return `<article class="wn-rel">
    <header><b class="mono" translate="no">v${r.v}</b><time class="mono muted" datetime="${r.date}" translate="no">${wnWhen(r)}</time>${isNew ? `<span class="badge wn-new" translate="no">NEW</span>` : ""}</header>
    <ul translate="no">${wnItems(r).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
  </article>`;
}

function seenVersion() {
  try { return localStorage.getItem(WN_SEEN); } catch { return null; }
}
function markSeen() {
  try { localStorage.setItem(WN_SEEN, RELEASES[0].v); } catch {}
  $("#wn-badge").hidden = true;
}
function unseenReleases() {
  const seen = seenVersion();
  return seen ? RELEASES.filter((r) => verNum(r.v) > verNum(seen)) : [];
}

// 设置页：全部版本
function renderWhatsNewList() {
  const unseen = new Set(unseenReleases().map((r) => r.v));
  $("#wn-list").innerHTML = RELEASES.map((r) => releaseHtml(r, unseen.has(r.v))).join("");
}

function openWhatsNew(list) {
  const rel = list && list.length ? list : RELEASES.slice(0, 3);
  $("#wn-body").innerHTML = rel.map((r) => releaseHtml(r, list && list.length)).join("");
  $("#wn-modal").hidden = false;
  $("#wn-close").focus();
}
function closeWhatsNew() {
  $("#wn-modal").hidden = true;
  markSeen();
  renderWhatsNewList();
}

$("#wn-open").addEventListener("click", () => openWhatsNew(unseenReleases()));
$("#wn-close").addEventListener("click", closeWhatsNew);
$("#wn-all").addEventListener("click", () => { closeWhatsNew(); switchTab("settings"); $("#wn-card").scrollIntoView({ block: "start" }); });
$("#wn-modal").addEventListener("click", (e) => { if (e.target.id === "wn-modal") closeWhatsNew(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#wn-modal").hidden) closeWhatsNew(); });
RERENDER.push(() => { renderWhatsNewList(); if (!$("#wn-modal").hidden) openWhatsNew(unseenReleases()); });

// 启动时：用过旧版本的人（有本工具的其他设置）在版本更新后自动弹出一次；第一次打开的新用户不弹，只记下当前版本
(function initWhatsNew() {
  let returning = false;
  try { returning = !!(localStorage.getItem("qs-tab") || localStorage.getItem("qs-lang") || localStorage.getItem("qs-theme")); } catch {}
  const seen = seenVersion();
  if (!seen && !returning) markSeen();
  else if (!seen) try { localStorage.setItem(WN_SEEN, RELEASES[1] ? RELEASES[1].v : "0.0.0"); } catch {}  // 公告功能上线前的老用户：当作看过上一版
  const unseen = unseenReleases();
  $("#wn-badge").hidden = !unseen.length;
  renderWhatsNewList();
  if (unseen.length) setTimeout(() => openWhatsNew(unseen), 1200);
})();
