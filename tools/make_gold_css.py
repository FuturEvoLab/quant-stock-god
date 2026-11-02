#!/usr/bin/env python3
"""从 HUD 主题（hud.css / nav.css / market.css）生成“黑金”配色覆盖层 static/gold.css。

做法：挑出所有写死了青色（0, 229, 255 / #00e5ff 等）的规则，把颜色换成金色，
选择器加上 [data-palette="gold"] 限定。改了 HUD 主题的颜色后重新运行：python3 tools/make_gold_css.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = ["hud.css", "nav.css", "market.css"]
COLOR_MAP = [  # 青色系 → 金色系
    ("0, 229, 255", "255, 201, 60"), ("0,229,255", "255,201,60"),
    ("#00e5ff", "#ffc93c"), ("#7fdcea", "#e9cf86"), ("#3b7584", "#7d6a3e"), ("#9fd6e6", "#e3cf9c"),
    ("#dff8ff", "#fff6df"), ("#3aa7bf", "#c9a24a"), ("#5a8796", "#8c7a52"), ("#001218", "#1a1200"),
]
CYAN = re.compile("|".join(re.escape(a) for a, _ in COLOR_MAP), re.I)


def recolor(text):
    for a, b in COLOR_MAP:
        text = re.sub(re.escape(a), b, text, flags=re.I)
    return text


def scope(selector):
    out = []
    for part in selector.split(","):
        part = part.strip()
        if not part:
            continue
        # 以 :root / [data-theme] 开头的选择器作用在 <html> 上，限定条件要直接拼在同一个元素上
        m = re.match(r"^(:root)?((?:\[data-theme=\"(?:dark|light)\"\])?)(.*)$", part, re.S)
        root, theme, rest = m.group(1) or "", m.group(2), m.group(3)
        if root or theme:
            out.append(f':root{theme}[data-palette="gold"]{rest}')
        else:
            out.append(f':root[data-palette="gold"] {part}')
    return ", ".join(out)


def blocks(css):
    """按顶层花括号切分：返回 (头部, 内容)；@media 的内容再递归处理"""
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            return
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        yield head, css[j + 1:k - 1]
        i = k


def convert(css, skipped):
    out = []
    for head, body in blocks(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        if head.startswith("@media"):
            inner = convert(body, skipped)
            if inner:
                out.append(f"{head} {{\n{inner}}}\n")
        elif head.startswith("@keyframes"):
            if CYAN.search(body):
                skipped.append(head)
        elif CYAN.search(body):
            decls = [d.strip() for d in body.split(";") if d.strip() and CYAN.search(d)]
            out.append(f"{scope(head)} {{ {'; '.join(recolor(d) for d in decls)}; }}\n")
    return "".join(out)


def main():
    skipped, parts = [], []
    for name in SRC:
        with open(os.path.join(ROOT, "static", name), encoding="utf-8") as f:
            parts.append(f"/* ---- 来自 {name} ---- */\n" + convert(f.read(), skipped))
    header = ("/* 量化股神 — 黑金配色覆盖层（由 tools/make_gold_css.py 从 HUD 主题自动生成，请勿手改；手写部分在 quant.css）*/\n"
              + (f"/* 未转换的 @keyframes：{', '.join(skipped)} */\n" if skipped else ""))
    with open(os.path.join(ROOT, "static", "gold.css"), "w", encoding="utf-8") as f:
        f.write(header + "\n".join(parts))
    print("gold.css written; keyframes left cyan:", skipped or "none")


if __name__ == "__main__":
    main()
