#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
from pathlib import Path

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "A5-灵山小向导-部署与使用说明书.md"
OUTPUT = ROOT / "A5-灵山小向导-部署与使用说明书.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Markdown document as printable HTML")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--title", default="灵山小向导·灵曦——产品部署与使用说明书")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    markdown = source.read_text(encoding="utf-8")
    body = MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown)
    title = args.title
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --ink:#19352f; --jade:#276655; --red:#ad4939; --gold:#b27b2c; --muted:#63736d; --line:#d9d5ca; --paper:#fffdf7; }}
    @page {{ size:A4; margin:15mm 14mm 17mm; }}
    * {{ box-sizing:border-box; }}
    html {{ background:#ece9df; }}
    body {{ max-width:210mm; margin:0 auto; padding:17mm 15mm; background:var(--paper); color:#263b36; font:10.6pt/1.72 "Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
    h1,h2,h3 {{ color:var(--ink); page-break-after:avoid; break-after:avoid-page; }}
    h1 {{ margin:0; padding-top:8mm; text-align:center; font-size:28pt; letter-spacing:.08em; }}
    h1 + h2 {{ margin:3mm 0 9mm; padding:0 0 5mm; border-bottom:2px solid var(--jade); text-align:center; font-size:17pt; color:var(--red); }}
    h2 {{ margin:10mm 0 4mm; padding:0 0 2mm 4mm; border-left:4px solid var(--red); border-bottom:1px solid var(--line); font-size:17pt; }}
    h3 {{ margin:7mm 0 2mm; font-size:13pt; color:var(--jade); }}
    p {{ margin:2.1mm 0; orphans:3; widows:3; }}
    ul,ol {{ margin:2mm 0 3mm 6mm; padding-left:5mm; }}
    li {{ margin:1mm 0; }}
    table {{ width:100%; margin:3mm 0 5mm; border-collapse:collapse; break-inside:avoid; page-break-inside:avoid; font-size:9.3pt; }}
    th,td {{ padding:1.8mm 2.2mm; border:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ background:#e9efe9; color:var(--ink); font-weight:700; }}
    tbody tr:nth-child(even) {{ background:#f8f6ef; }}
    a {{ color:var(--jade); text-decoration:none; }}
    code {{ padding:.2mm 1mm; border-radius:2px; background:#f0eee6; color:#7c3b31; font-family:"DejaVu Sans Mono",monospace; font-size:9.4pt; }}
    pre {{ margin:3mm 0 5mm; padding:4mm; border-left:3px solid var(--gold); background:#f2efe7; white-space:pre-wrap; break-inside:avoid; page-break-inside:avoid; }}
    pre code {{ padding:0; background:none; color:#1f3d35; font-size:8.8pt; }}
    img {{ display:block; width:100%; max-height:168mm; margin:5mm auto 2mm; border:1px solid #d8d3c8; object-fit:contain; break-inside:avoid; page-break-inside:avoid; }}
    p:has(> img) {{ break-inside:avoid; page-break-inside:avoid; }}
    p > em:only-child {{ display:block; margin:0 0 5mm; text-align:center; color:var(--muted); font-size:9pt; }}
    strong {{ color:var(--ink); }}
    hr {{ border:0; border-top:1px solid var(--line); }}
    @media print {{
      html,body {{ background:#fff; }}
      body {{ max-width:none; margin:0; padding:0; }}
      a {{ color:inherit; }}
      h2 {{ break-before:auto; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
    output.write_text(document, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
