"""
Generate a build sheet for creating the API 4000 PM form by hand in the Simpro UI.

The API cannot edit a Basic (PDF overlay) form without detaching the PDF, so
field creation stays manual. This produces the list to work from, so names and
types are copied rather than retyped — which is where the errors come from.

Outputs:
    build_sheet.csv   — one row per field, for Excel / checking off
    build_sheet.html  — printable, grouped by page

Usage:
    python make_build_sheet.py
"""

from __future__ import annotations

import csv
import html
from pathlib import Path

from build_api4000 import (PAGES, TEXT, DECIMAL, DATE, CHECKBOX, SKETCH,
                           SIGNATURE, STATIC)

HERE = Path(__file__).resolve().parent

# What to pick in the Simpro field-type dropdown.
UI_TYPE = {
    TEXT: "Text",
    DECIMAL: "Number (decimal)",
    DATE: "Date",
    CHECKBOX: "Checkbox",
    SKETCH: "Sketch",
    SIGNATURE: "Signature",
    STATIC: "Static text (label only - not fillable)",
}


def rows():
    for page_index, (title, entries) in enumerate(PAGES, start=1):
        for position, spec in enumerate(entries):
            yield {
                "Page": title,
                "#": position + 1,
                "Field name": spec["label"],
                "Type": UI_TYPE.get(spec["t"], str(spec["t"])),
                "Decimal places": spec["mask"] or "",
                "Required": "Yes" if spec["required"] else "",
                "Fillable": "" if spec["t"] == STATIC else "Yes",
            }


def write_csv(data) -> Path:
    out = HERE / "build_sheet.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)
    return out


def write_html(data) -> Path:
    out = HERE / "build_sheet.html"
    pages: dict[str, list] = {}
    for row in data:
        pages.setdefault(row["Page"], []).append(row)

    fillable = sum(1 for r in data if r["Fillable"])
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>API 4000 PM - build sheet</title><style>",
        "body{font:13px/1.45 system-ui,sans-serif;margin:24px;color:#111}",
        "h1{font-size:19px;margin:0 0 2px}",
        "p.sub{color:#555;margin:0 0 18px}",
        "h2{font-size:15px;margin:22px 0 6px;padding-top:10px;border-top:2px solid #ddd}",
        "table{border-collapse:collapse;width:100%}",
        "th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}",
        "th{background:#f3f3f3;font-weight:600}",
        "tr.static td{color:#888;background:#fafafa}",
        "td.n{width:28px;text-align:right;color:#666}",
        "td.chk{width:26px}",
        "@media print{h2{page-break-after:avoid}tr{page-break-inside:avoid}}",
        "</style></head><body>",
        "<h1>API 4000 PM &mdash; field build sheet</h1>",
        f"<p class='sub'>Generated from <code>1_1 API 4000 PM final.pdf</code>. "
        f"{len(data)} rows, {fillable} fillable fields. "
        f"Greyed rows are printed text on the PDF &mdash; do not create a field "
        f"for them unless you want it editable.</p>",
    ]
    for page, items in pages.items():
        parts.append(f"<h2>{html.escape(page)}</h2><table>")
        parts.append("<tr><th></th><th>#</th><th>Field name</th><th>Type</th>"
                     "<th>Dec</th><th>Req</th></tr>")
        for r in items:
            cls = " class='static'" if not r["Fillable"] else ""
            parts.append(
                f"<tr{cls}><td class='chk'>{'&#9744;' if r['Fillable'] else ''}</td>"
                f"<td class='n'>{r['#']}</td>"
                f"<td>{html.escape(r['Field name'])}</td>"
                f"<td>{html.escape(r['Type'])}</td>"
                f"<td>{r['Decimal places']}</td><td>{r['Required']}</td></tr>"
            )
        parts.append("</table>")
    parts.append("</body></html>")
    out.write_text("".join(parts), encoding="utf-8")
    return out


def main() -> int:
    data = list(rows())
    csv_path = write_csv(data)
    html_path = write_html(data)
    fillable = sum(1 for r in data if r["Fillable"])
    print(f"  {len(data)} rows ({fillable} fillable, {len(data) - fillable} static)")
    for page, in {(r["Page"],) for r in data}:
        pass
    for title, entries in PAGES:
        n = sum(1 for e in entries if e["t"] != STATIC)
        print(f"    {title:<44} {len(entries):>3} rows, {n:>2} fillable")
    print(f"\n  {csv_path}")
    print(f"  {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
