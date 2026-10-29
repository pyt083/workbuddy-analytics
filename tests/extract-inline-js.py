#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 index.html 中抽取所有内联 <script>（无 src 属性）代码块，合并写入目标 JS 文件。

用途：对单文件看板的内联 JS 做 `node --check` 语法校验，避免「只看代码不实跑」。

用法：
    python3 tests/extract-inline-js.py [输入的 index.html] [输出的 .js]
默认输入 <repo>/index.html，输出 <repo>/.tmp-inline.js
"""
from __future__ import annotations

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent


SCRIPT_RE = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def extract_inline_scripts(html: str) -> list[tuple[int, str]]:
    """返回 [(起始行号, 代码内容)]，仅包含没有 src 属性的内联脚本。"""
    blocks: list[tuple[int, str]] = []
    for match in SCRIPT_RE.finditer(html):
        attrs = match.group("attrs") or ""
        if re.search(r"\bsrc\s*=", attrs, re.IGNORECASE):
            continue
        start_line = html.count("\n", 0, match.start()) + 1
        blocks.append((start_line, match.group("body")))
    return blocks


def main() -> int:
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "index.html"
    dst = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".tmp-inline.js"

    if not src.is_file():
        print(f"FAIL 找不到输入文件: {src}")
        return 1

    html = src.read_text(encoding="utf-8")
    blocks = extract_inline_scripts(html)
    if not blocks:
        print(f"FAIL 未在 {src.name} 中找到内联 script")
        return 1

    parts: list[str] = []
    for start_line, body in blocks:
        parts.append(f"/* ==== inline script @ line {start_line} ==== */\n{body}\n")
    dst.write_text("".join(parts), encoding="utf-8")

    total_lines = sum(b.count("\n") + 1 for _, b in blocks)
    print(f"OK 抽取 {len(blocks)} 段内联 JS，共 {total_lines} 行 -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
