"""
Stamp a completed submission's values onto the ORIGINAL ILS PDF.

This is the alternative to Simpro's generated PDF: instead of accepting Simpro's
layout, we take the field values from a submission and print them onto
"1_1 API 4000 PM final.pdf" at coordinates anchored to the document's own label
text. The output is the real controlled document, filled in.

Each value is positioned by finding an anchor word on the page (via pdfplumber,
which gives reliable coordinates) and offsetting from it. Anchors are defined in
FIELD_MAP. Coordinates are the one genuinely manual part and are refined by eye
against a render; this file is where that tuning lives.

Usage:
    python fill_pdf.py <submission_id>
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from simpro_api import connect

HERE = Path(__file__).resolve().parent
SRC = HERE / "pdfs" / "1_1 API 4000 PM final.pdf"

# Each field: match text (substring of the submission label) -> where to print.
#   page:   0-based page index of the source PDF
#   anchor: word(s) to locate on that page
#   dx, dy: offset in points from the anchor's baseline-left (dy up is positive)
#   which:  if the anchor text appears more than once, which occurrence (0-based)
FIELD_MAP = [
    # Page 1 — identification. Values go on the ____ line after the colon.
    ("Instrument Serial #",      dict(page=0, anchor="Instrument Serial", dx=118, dy=0)),
    ("Instrument Name / INV #",  dict(page=0, anchor="Instrument Name",   dx=118, dy=0)),
    # Page 2 — customer block.
    ("Customer Site",            dict(page=1, anchor="Customer Site",     dx=78,  dy=0)),
    ("Serial Number",            dict(page=1, anchor="Serial Number",     dx=82,  dy=0)),
    ("Customer Name",            dict(page=1, anchor="Customer Name",     dx=90,  dy=0)),
    ("Service Engineer",         dict(page=1, anchor="Service Engineer",  dx=95,  dy=0, which=0)),
    ("Date",                     dict(page=1, anchor="Date:",             dx=34,  dy=0)),
    # Page 3 — Pre-PM vacuum + first positive-ion readings.
    ("Pre-PM Vacuum pressure at CAD = 0",  dict(page=2, anchor="CAD = 0", dx=120, dy=0, which=1)),
    # Page 5 — PM checklist voltages.
    ("Record CEM voltage",       dict(page=4, anchor="Record CEM",        dx=150, dy=0)),
    ("Record AC voltage",        dict(page=4, anchor="Record AC",         dx=150, dy=0)),
    # Page 6 — gas pressures.
    ("Curtain / CAD Gas pressure", dict(page=5, anchor="Curtain / CAD Gas", dx=120, dy=0)),
    # Page 8 — comments.
    ("Comments or Observations", dict(page=7, anchor="Comments or Observations", dx=0, dy=-16)),
]

# Numbered PM checklist items on page 5 → print an X to the right when checked.
CHECK_PAGE = 4
CHECK_ITEMS = {f"{n}.": None for n in range(1, 19)}


def value_for(responses, needle):
    for r in responses:
        if needle.lower() in (r.get("label") or "").lower():
            return r.get("value")
    return None


def anchor_xy(words, anchor, which=0, page_height=792):
    """Locate a (possibly multi-word) anchor by grouping words into lines.

    Returns (x, y) at the right edge of the anchor text, baseline-up, for the
    `which`-th occurrence. Robust to the space-splitting done by extract_words.
    """
    # Group words into lines by their vertical position.
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"] / 2) * 2, []).append(w)

    hits = []
    for top in sorted(lines):
        row = sorted(lines[top], key=lambda w: w["x0"])
        joined = " ".join(w["text"] for w in row).lower()
        idx = joined.find(anchor.lower())
        if idx == -1:
            continue
        # Find the last word whose text falls within the matched span.
        end = idx + len(anchor)
        cursor, right_edge, bottom = 0, row[0]["x1"], row[0]["bottom"]
        for w in row:
            seg = len(w["text"]) + 1
            if cursor < end:
                right_edge, bottom = w["x1"], w["bottom"]
            cursor += seg
        hits.append((right_edge, page_height - bottom))

    return hits[which] if which < len(hits) else None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    submission_id = sys.argv[1]

    client = connect()
    sub = client.get_submission(submission_id)
    responses = sub["responses"]
    filled = sum(1 for r in responses if str(r.get("value") or "").strip())
    print(f"  submission {submission_id}: {filled} filled values")

    src = PdfReader(str(SRC))
    plumber = pdfplumber.open(str(SRC))
    writer = PdfWriter()

    placed = 0
    # Build a per-page overlay of text, then merge onto the original page.
    overlays: dict[int, list] = {}

    for needle, spec in FIELD_MAP:
        val = value_for(responses, needle)
        if not val or val in ("Binary data is not displayed",) or val == "None":
            continue
        page = spec["page"]
        pg = plumber.pages[page]
        xy = anchor_xy(pg.extract_words(), spec["anchor"],
                       spec.get("which", 0), pg.height)
        if not xy:
            print(f"    [no anchor] {needle!r} (anchor {spec['anchor']!r} p{page+1})")
            continue
        x, y = xy
        overlays.setdefault(page, []).append(
            (x + spec["dx"], y + spec["dy"], str(val)))
        placed += 1

    # Checkboxes on page 5.
    pg = plumber.pages[CHECK_PAGE]
    words = pg.extract_words()
    for item in CHECK_ITEMS:
        val = None
        for r in responses:
            lbl = (r.get("label") or "").strip()
            if lbl.startswith(item):
                val = r.get("value")
                break
        if val == "True":
            xy = anchor_xy(words, item, 0, pg.height)
            if xy:
                overlays.setdefault(CHECK_PAGE, []).append((465, xy[1], "X"))
                placed += 1

    for i, page in enumerate(src.pages):
        if i in overlays:
            buf = io.BytesIO()
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            c = canvas.Canvas(buf, pagesize=(w, h))
            c.setFont("Helvetica-Bold", 10)
            for x, y, text in overlays[i]:
                c.drawString(x, y, text)
            c.save()
            buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        writer.add_page(page)

    out = HERE / "pdfs" / f"FILLED_1_1_API_4000_{submission_id}.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    print(f"  placed {placed} values")
    print(f"  wrote -> {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
