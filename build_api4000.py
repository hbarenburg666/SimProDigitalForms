"""
Build the complete API 4000 PM form from "1_1 API 4000 PM final.pdf".

Design decisions, and why:

* NO minimum/maximum are set. An OQ must be able to record an out-of-spec
  reading — that IS the result. Blocking entry would make a failing instrument
  unrecordable. Spec limits live in the field label instead, exactly as the
  paper document prints them next to each recorded-value box, so the engineer
  sees the guideline while typing. Pass/fail determination belongs downstream
  (Phase 4), not in the keyboard.

* Every entry gets a UNIQUE guid. Entries created with guid=null all collide,
  and a value typed into one propagates to the others.

* Intensity and vacuum-pressure readings are TEXT, not decimal: real values are
  scientific notation ("2.5x10^7", "1.3x10-5 torr") which a decimal field
  cannot hold. FWHM, pressures, voltages and percentages are decimal.

* One clean write per form. POST /forms/{id} rejects no-op transitions and
  pending->new, so this script CREATES a form rather than updating one.

Usage:
    python build_api4000.py            # dry run, writes payload to disk
    python build_api4000.py --create   # POST /forms
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent
FORM_NAME = "API 4000 PM - Harris Barenburg Draft"

TEXT, DECIMAL, DATE, VALUE_LIST, CHECKBOX, SKETCH, SIGNATURE = 0, 2, 3, 5, 7, 8, 99
STATIC = 9
TYPE_OFFSET = 10
SECTION_TYPE_ID, SHEET_TYPE_ID = 10, 11

# Decimal places. "0" (the only value in the tenant) means whole numbers, which
# is why existing forms reject decimal readings. FWHM needs two.
DP2, DP1 = "2", "1"


def guid() -> str:
    return hashlib.sha1(uuid.uuid4().bytes).hexdigest().upper()


def E(label, t=TEXT, mask=None, required=False, values=None):
    """One entry. Kept terse — this file is mostly data."""
    return {"label": label, "t": t, "mask": mask, "required": required, "values": values}


def intensity(mass, spec):
    return E(f"{mass} Intensity  (spec {spec})")


def fwhm(mass):
    return E(f"{mass} FWHM amu  (spec 0.6 - 0.8)", DECIMAL, DP2)


# --- ion-mode test blocks, reused between Pre-PM and Performance Verification --
def positive_block():
    return [
        E("Q1 - m/z 906.673", STATIC),
        intensity("Q1 m/z 906.673", ">= 2.0x10^7"), fwhm("Q1 m/z 906.673"),
        E("Q1 - m/z 2242.6", STATIC),
        intensity("Q1 m/z 2242.6", ">= 1.0x10^6"), fwhm("Q1 m/z 2242.6"),
        E("Q3 - m/z 906.673", STATIC),
        intensity("Q3 m/z 906.673", ">= 2.0x10^7"), fwhm("Q3 m/z 906.673"),
        E("Q3 - m/z 2242.6", STATIC),
        intensity("Q3 m/z 2242.6", ">= 8.0x10^5"), fwhm("Q3 m/z 2242.6"),
    ]


def negative_block():
    return [
        E("Q1 - m/z 933.636", STATIC),
        intensity("Q1 m/z 933.636", ">= 1.1x10^7"), fwhm("Q1 m/z 933.636"),
        E("Q1 - m/z 2037.4", STATIC),
        intensity("Q1 m/z 2037.4", ">= 1.0x10^6"), fwhm("Q1 m/z 2037.4"),
        E("Q3 - m/z 933.636", STATIC),
        intensity("Q3 m/z 933.636", ">= 9.0x10^6"), fwhm("Q3 m/z 933.636"),
        E("Q3 - m/z 2037.4 is N/A per the procedure", STATIC),
    ]


def reserpine_block():
    return [
        E("Use diluted reserpine 6:1 (0.16 pmol/ul). Printouts required.", STATIC),
        E("Attenuated m/z 609.3", STATIC),
        intensity("Attenuated m/z 609.3", "record"),
        fwhm("Attenuated m/z 609.3"),
        E("m/z 195.0", STATIC),
        intensity("m/z 195.0", "record"),
        fwhm("m/z 195.0"),
        E("MS/MS Transmission Efficiency %  (m/z 195.0 / attenuated m/z 609.3) x 100"
          "  (spec >= 10.0)", DECIMAL, DP2),
    ]


def vacuum_block(heading):
    return [
        E(heading, STATIC),
        E("Guideline:  CAD = 0  ->  <= 0.8x10-5 torr (0.08 V)", STATIC),
        E("Recorded vacuum pressure, CAD = 0"),
        E("Guideline:  CAD = 12  ->  <= 5.5x10-5 torr (+/- 0.3x10-5)", STATIC),
        E("Recorded vacuum pressure, CAD = 12"),
    ]


PM_CHECKS = [
    "1. Check operation of the Turbo V ion source heaters",
    "2. Check lens voltages (Lens Power Supply module)",
    "3. Check RF tuning voltages (Q1 and Q3 QPS AMP module). Only if required, tune QPS AMPs.",
    "4. Check operation of the instrument cooling fans",
    "7. Inspect gas tubing for breakage (CAD gas, interface gas tubes, etc)",
    "8. Remove and clean the curtain plate",
    "9. If necessary, remove and clean the orifice plate",
    "10. If necessary, clean the front end of Q0",
    "11. Replace the air filter",
    "12. Replace the roughing pumps oil",
    "13. Inspect the oil return systems and if necessary replace the oil filter",
    "14. If applicable, perform PM on Peak Scientific gas generator",
    "15. Reinstall all covers and pump down",
    "16. Re-check operation of the instrument cooling fans",
    "17. If necessary, perform Turbo V ion source maintenance",
    "18. Clear computer temp files (Start/Search/Files and Folders -> *.tmp -> "
    "Local Hard Drive (C), (D) -> Search now -> Edit/Select All/Files/Delete/Empty Recycle Bin)",
]

# --------------------------- the document, page by page ---------------------
PAGES = [
    ("Page 1 - Cover", [
        E("INNOVATIVE LAB SERVICES LLC - API 4000 LC/MS/MS SYSTEM - "
          "PLANNED MAINTENANCE PROCEDURE", STATIC),
        E("Instrument Serial #", TEXT, required=True),
        E("Instrument Name / INV #", TEXT, required=True),
    ]),
    ("Page 2 - Customer & Sign Off", [
        E("ANALYST SOFTWARE LC/MS/MS SYSTEM", STATIC),
        E("Customer Site", TEXT, required=True),
        E("Serial Number", TEXT, required=True),
        E("Customer Name", TEXT, required=True),
        E("Service Engineer", TEXT, required=True),
        E("Date", DATE, required=True),
        E("All PM tests are run using Chemical Kit P/N 4406127. All Pre and Post tests use "
          "the Standard Turbo V Source. Printed copies of all test runs, method files and "
          "calibration runs are filed in the instrument IQ/OQ binder with a copy of this "
          "procedure.", STATIC),
        E("SIGN OFF - By signing this form you acknowledge that the planned maintenance "
          "was completely performed.", STATIC),
        E("Customer signature", SIGNATURE),
        E("Service Engineer signature", SIGNATURE),
    ]),
    ("Page 3 - Pre-PM: Vacuum & Positive Ion", [
        E("PRE-PM SECTION. Pre-PM tests do not need to pass specifications. "
          "Record Pre-PM performance.", STATIC),
        *vacuum_block("1.0  VACUUM PRESSURE CHECK"),
        E("2.0  POSITIVE ION MODE TEST - Printouts required. "
          "Use 50:1 diluted Standard PPG (2x10-6M). Guideline: 10 Scans MCA.", STATIC),
        *positive_block(),
    ]),
    ("Page 4 - Pre-PM: Negative Ion & Reserpine", [
        E("3.0  NEGATIVE ION MODE TEST (10 SCANS MCA) - Printouts required. "
          "Use PPG 3000 (2x10-4M) negative PPG solution, no dilution required.", STATIC),
        *negative_block(),
        E("4.0  RESERPINE MS/MS TEST (10 SCANS MCA)", STATIC),
        *reserpine_block(),
    ]),
    ("Page 5 - PM Section", [
        E("PM SECTION", STATIC),
        *[E(c, CHECKBOX) for c in PM_CHECKS[:4]],
        E("5. Check operation of the detector. Record CEM voltage:", DECIMAL, DP1),
        E("SHUTDOWN AND PERFORM MAINTENANCE / CLEANING", STATIC),
        E("6. Check AC input voltage. Record AC voltage:", DECIMAL, DP1),
        *[E(c, CHECKBOX) for c in PM_CHECKS[4:]],
    ]),
    ("Page 6 - Gas & Vacuum Pressure", [
        E("PERFORMANCE VERIFICATION AND DATA LOG", STATIC),
        E("1.0  GAS PRESSURE. Low Gas 1 / Gas 2 pressure can affect turbo spray and "
          "sensitivity. Source Exhaust pressure above 60 psi can cause exhaust valve "
          "failures.", STATIC),
        E("Gas 1 / Gas 2 pressure, psi  (spec 100 - 105)", DECIMAL, DP1),
        E("Curtain / CAD Gas pressure, psi  (spec 60)", DECIMAL, DP1),
        E("Source Exhaust Supply pressure, psi  (spec 55 - 60)", DECIMAL, DP1),
        *vacuum_block("2.0  VACUUM PRESSURE. Use Analyst software to set CAD gas values."),
    ]),
    ("Page 7 - Positive & Negative Ion Mode", [
        E("3.0  POSITIVE ION MODE TEST (10 SCANS MCA) - Printouts required. "
          "Use 50:1 diluted Standard PPG (2x10^6M). See Appendix A.", STATIC),
        *positive_block(),
        E("4.0  NEGATIVE ION MODE TEST (10 SCANS MCA) - Printouts required. "
          "Use undiluted PPG 3000 (3x10^4M). See Appendix A.", STATIC),
        *negative_block(),
    ]),
    ("Page 8 - Reserpine, Spectra & Comments", [
        E("5.0  RESERPINE MS/MS TEST (10 SCANS MCA)", STATIC),
        *reserpine_block(),
        E("6.0  PRINT AND ATTACH TESTS SPECTRA RESULTS", CHECKBOX),
        E("Comments or Observations", TEXT),
        E("Additional comments (sketch/annotate)", SKETCH),
    ]),
]


def build_entry(spec: dict, position: int) -> dict:
    return {
        "guid": guid(),
        "type": "entry",
        "label": spec["label"],
        "original_type_id": spec["t"],
        "entry_type_id": spec["t"] + TYPE_OFFSET,
        "position": position,
        "required": spec["required"],
        "minimum": None,
        "maximum": None,
        "mask": spec["mask"],
        "visible": True,
        "read_only": False,
        "pdf_visibility": 0,
        "web_visibility": 0,
        "entry_values": [
            {"type": "entry_value", "text": v, "position": i}
            for i, v in enumerate(spec["values"] or [])
        ],
        "operations": [],
        "conditions": [],
    }


def build_payload() -> dict:
    sections = []
    for i, (title, entries) in enumerate(PAGES):
        sections.append({
            "type": "section",
            "description": title,
            "position": i,
            "section_type_id": SECTION_TYPE_ID,
            "hides_detailed_description": False,
            "sheets": [{
                "type": "sheet",
                "description": title,
                "position": 0,
                "sheet_type_id": SHEET_TYPE_ID,
                "show_sheet_name": True,
                "inserts_page_break_at_the_end": False,
                "style": 0,
                "integration_form": False,
                "conditions": [],
                "entries": [build_entry(e, j) for j, e in enumerate(entries)],
            }],
        })
    return {
        "type": "form",
        "name": FORM_NAME,
        "description": "Generated from 1_1 API 4000 PM final.pdf. Spec limits appear in "
                       "field labels; out-of-spec values are recordable by design.",
        "status": "new",
        "email_options": 2,
        "view_pdf_mobile": True,
        "web_form": False,
        "workflow_enabled": False,
        "dispatch_enabled": False,
        "sheet_style_enabled": True,
        "sections": sections,
    }


def main() -> int:
    payload = build_payload()
    entries = [e for s in payload["sections"] for sh in s["sheets"] for e in sh["entries"]]
    guids = [e["guid"] for e in entries]
    assert len(set(guids)) == len(guids), "duplicate guids"

    counts: dict[int, int] = {}
    for e in entries:
        counts[e["original_type_id"]] = counts.get(e["original_type_id"], 0) + 1
    names = {TEXT: "text", DECIMAL: "decimal", DATE: "date", CHECKBOX: "checkbox",
             STATIC: "static", SKETCH: "sketch", SIGNATURE: "signature"}

    print(f"\n  {FORM_NAME}")
    print(f"  {len(payload['sections'])} sections, {len(entries)} entries, "
          f"{len(set(guids))} unique guids")
    for s in payload["sections"]:
        n = len(s["sheets"][0]["entries"])
        fillable = sum(1 for e in s["sheets"][0]["entries"]
                       if e["original_type_id"] != STATIC)
        print(f"    {s['description']:<44} {n:>3} entries ({fillable} fillable)")
    print("  types: " + ", ".join(f"{names.get(k, k)}={v}" for k, v in sorted(counts.items())))

    out = HERE / "api4000_payload.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  payload -> {out} ({out.stat().st_size:,} bytes)")

    # --into <form_id> writes the generated sections into an EXISTING form,
    # rather than creating a new one. Intended for a "Basic - build from
    # scratch" form: PDF uploaded, zero sections. A form with no sections has
    # no section ids for the server to destroy, so the PDF binding may survive
    # a write that would otherwise break an autobuilt form.
    into = None
    if "--into" in sys.argv:
        into = sys.argv[sys.argv.index("--into") + 1]

    if "--create" not in sys.argv and not into:
        print("\n  DRY RUN — nothing sent. Add --create (new form) or "
              "--into <form_id> (existing).")
        return 0

    client = connect()

    if into:
        existing = client.get_form(into, fmt="nested")
        n = len(existing.get("sections", []))
        print(f"\n  target: {existing['name']!r} (status {existing['status']}, "
              f"{n} existing sections)")
        if n:
            print("  REFUSING: target already has sections. Writing would destroy "
                  "their ids and with them any PDF page binding.")
            return 1
        merged = dict(existing)
        merged["sections"] = payload["sections"]
        merged["status"] = "pending" if existing["status"] != "pending" else "new"
        print(f"  status transition: {existing['status']} -> {merged['status']}")
        print(f"\n=== POST /forms/{into} ===")
        client.update_form(into, merged)
        check = client.get_form(into, fmt="nested")
        got = [e for s in check["sections"] for sh in s["sheets"] for e in sh["entries"]]
        print(f"  read back: {len(check['sections'])} sections, {len(got)} entries, "
              f"status {check['status']}")
        return 0

    print("\n=== POST /forms ===")
    result = client.create_form(payload)
    print(f"  created id: {result.get('id')}  status: {result.get('status')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
