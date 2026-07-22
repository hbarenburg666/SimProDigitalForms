"""
Generate a professional, branded PM report PDF from a submission — in code.

This is the scalable alternative to designing a PDF per instrument model in
Simpro. ONE generator serves every model: it reads the form definition (section
structure, field labels, embedded spec limits) and the submission values, both
from the API, and lays out a branded document. A new instrument model needs no
new design — the generator adapts to whatever fields the form has.

It also does what Simpro's PDFs cannot: parse the spec printed in each field
label and colour the recorded value PASS (green) / FAIL (red).

Usage:
    python generate_pdf.py <submission_id>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, Image as RLImage)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from simpro_api import connect

HERE = Path(__file__).resolve().parent
LOGO = HERE / "pdfs" / "_logo_0.png"

ILS_BLUE = colors.HexColor("#2E6E8E")
PASS_GREEN = colors.HexColor("#1B7A3D")
FAIL_RED = colors.HexColor("#C0281F")
LIGHT = colors.HexColor("#EDF2F5")

STATIC, CHECKBOX, SIGNATURE, SKETCH = 9, 7, 99, 8


def parse_spec(label: str):
    """Extract a numeric spec from a field label. Returns (kind, lo, hi) or None."""
    m = re.search(r"spec\s+([\d.]+)\s*-\s*([\d.]+)", label, re.I)
    if m:
        return ("range", float(m.group(1)), float(m.group(2)))
    m = re.search(r"spec\s*>=\s*([\d.]+)", label, re.I)
    if m:
        return ("min", float(m.group(1)), None)
    return None


def verdict(spec, value):
    try:
        v = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    kind, lo, hi = spec
    if kind == "range":
        return lo <= v <= hi
    return v >= lo


def clean_label(label: str) -> str:
    return re.sub(r"\s*\(spec[^)]*\)", "", label).strip()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    submission_id = sys.argv[1]

    client = connect()
    sub = client.get_submission(submission_id)
    form = client.get_form(sub["form_id"], fmt="nested")
    values = {r["entry_id"]: r.get("value") for r in sub["responses"]}

    styles = getSampleStyleSheet()
    h_sec = ParagraphStyle("sec", parent=styles["Heading2"], textColor=colors.white,
                           fontSize=11, spaceBefore=0, spaceAfter=0, leading=15)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12)
    note = ParagraphStyle("note", parent=styles["Normal"], fontSize=8,
                          textColor=colors.HexColor("#555555"), leading=10)

    story = []

    def header(canvas, doc):
        canvas.saveState()
        if LOGO.exists():
            canvas.drawImage(str(LOGO), 0.6 * inch, 10.15 * inch,
                             width=2.0 * inch, height=0.29 * inch,
                             preserveAspectRatio=True, mask="auto")
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawRightString(7.9 * inch, 10.35 * inch, "API 4000 LC/MS/MS System")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(7.9 * inch, 10.2 * inch,
                               "Planned Maintenance Procedure  -  Doc 1_1, Rev 1.1")
        canvas.setStrokeColor(ILS_BLUE)
        canvas.setLineWidth(1.5)
        canvas.line(0.6 * inch, 10.05 * inch, 7.9 * inch, 10.05 * inch)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(0.6 * inch, 0.4 * inch,
                          f"Submission {submission_id}  -  generated from Simpro Digital Forms")
        canvas.drawRightString(7.9 * inch, 0.4 * inch, f"Page {doc.page}")
        canvas.restoreState()

    def section_bar(title):
        t = Table([[Paragraph(title.upper(), h_sec)]], colWidths=[7.3 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ILS_BLUE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    passed = failed = 0

    for section in form["sections"]:
        entries = [e for sh in section["sheets"] for e in sh["entries"]]
        story.append(section_bar(section["description"]))
        story.append(Spacer(1, 4))

        rows, styflags = [], []
        for e in entries:
            t = e["original_type_id"]
            label = e.get("label") or ""
            val = values.get(e["id"])
            if t == STATIC:
                if val is None:
                    story.append(_flush(rows, styflags))
                    rows, styflags = [], []
                    story.append(Paragraph(clean_label(label), note))
                continue
            spec = parse_spec(label)
            disp = "" if val in (None, "") else str(val)
            if val == "True":
                disp = "Yes"
            elif val == "False":
                disp = "No"
            elif val == "Binary data is not displayed":
                disp = "[signed]"
            result = ""
            if spec and disp:
                ok = verdict(spec, val)
                if ok is True:
                    result, passed = "PASS", passed + 1
                    styflags.append(("row_pass", len(rows)))
                elif ok is False:
                    result, failed = "FAIL", failed + 1
                    styflags.append(("row_fail", len(rows)))
            spec_txt = ""
            if spec:
                spec_txt = (f"{spec[1]} - {spec[2]}" if spec[0] == "range"
                            else f">= {spec[1]}")
            rows.append([Paragraph(clean_label(label), body), spec_txt, disp, result])
        story.append(_flush(rows, styflags))
        story.append(Spacer(1, 8))

    # Result banner at top.
    banner = f"{passed} readings within spec"
    if failed:
        banner += f"    -    {failed} OUT OF SPEC"
    story.insert(0, Spacer(1, 6))
    story.insert(0, Paragraph(
        f"<b>Result summary:</b> {banner}",
        ParagraphStyle("sum", parent=body, fontSize=10,
                       textColor=FAIL_RED if failed else PASS_GREEN)))

    out = HERE / "pdfs" / f"REPORT_{submission_id}.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=1.1 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    doc.build(story, onFirstPage=header, onLaterPages=header)
    print(f"  {passed} pass / {failed} fail")
    print(f"  wrote -> {out}")
    return 0


def _flush(rows, styflags):
    """Build a readings table from accumulated rows."""
    if not rows:
        return Spacer(0, 0)
    data = [["Measurement", "Specification", "Recorded", "Result"]] + rows
    t = Table(data, colWidths=[3.5 * inch, 1.5 * inch, 1.3 * inch, 0.7 * inch],
              repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for kind, i in styflags:
        r = i + 1
        if kind == "row_pass":
            style.append(("TEXTCOLOR", (3, r), (3, r), PASS_GREEN))
            style.append(("FONT", (3, r), (3, r), "Helvetica-Bold", 9))
        else:
            style.append(("TEXTCOLOR", (3, r), (3, r), FAIL_RED))
            style.append(("FONT", (3, r), (3, r), "Helvetica-Bold", 9))
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#FBEAE8")))
    t.setStyle(TableStyle(style))
    return t


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
