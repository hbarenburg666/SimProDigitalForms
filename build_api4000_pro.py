"""
Build the API 4000 PM form for a professional native Simpro PDF.

Differences from build_api4000.py, all aimed at the generated document:

* Sections follow the PROCEDURE's own numbering (1.0 Vacuum Pressure Check,
  2.0 Positive Ion Mode Test, ...) rather than PDF page numbers, so the PDF
  gets headings that read like the controlled document.
* `report_label` gives every field a short name in the PDF while the on-screen
  label stays verbose and carries the spec. The engineer sees
  "Q1 m/z 906.673 FWHM amu (spec 0.6 - 0.8)"; the PDF prints "FWHM" under the
  "Q1 m/z 906.673" heading.
* Page breaks are forced at the end of each major block so the output paginates
  like the paper procedure instead of running together.
* Guideline lines stay visible in the PDF — they are part of the controlled
  record. Only redundant on-screen helper text is hidden (pdf_visibility=1).
* No position prefixes in labels. Uniqueness comes from the mass and quadrupole.
* No minimum/maximum: an out-of-spec reading must be recordable.

Loop tables (sheet_type_id 15) are deliberately NOT used: they require
`multi_section` to reference a detail section by id, which cannot exist in a
single create, and they model variable row counts, whereas the masses here are
fixed.

Usage:
    python build_api4000_pro.py                 # dry run
    python build_api4000_pro.py --into <id>     # write into an empty form
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent

TEXT, DECIMAL, DATE, VALUE_LIST, CHECKBOX, SKETCH, STATIC, SIGNATURE = \
    0, 2, 3, 5, 7, 8, 9, 99
TYPE_OFFSET = 10
SECTION_TYPE_ID, SHEET_TYPE_ID = 10, 11
SHOW, HIDE = 0, 1          # pdf_visibility
DP1, DP2 = "1", "2"        # decimal places


def guid() -> str:
    return hashlib.sha1(uuid.uuid4().bytes).hexdigest().upper()


def E(label, t=TEXT, mask=None, required=False, report=None, pdf=SHOW,
      auto_name=False, auto_file=False, auto_subj=False, auto_body=False):
    """One entry. `report` is the short label printed in the PDF.

    The auto_* flags mirror how the tenant's mature forms (Part Request,
    Order Confirmation, Sciex 4500 IQ-OQ) tag their "Job ID" field:
      auto_name  -> names the submission from this field's value, instead of
                    the "No.: 00000" placeholder currently in the footer
      auto_file  -> names the emailed PDF file from this value
      auto_subj  -> builds the email subject from it
      auto_body  -> includes the field in the email body (set on several)
    """
    return {"label": label, "t": t, "mask": mask, "required": required,
            "report": report, "pdf": pdf, "auto_name": auto_name,
            "auto_file": auto_file, "auto_subj": auto_subj,
            "auto_body": auto_body}


def note(text):
    """Guideline text. Visible in the PDF — it is part of the record."""
    return E(text, STATIC)


def helper(text):
    """On-screen working instruction, suppressed from the PDF."""
    return E(text, STATIC, pdf=HIDE)


# --- reusable reading blocks -------------------------------------------------
def reading(mass_label, intensity_spec):
    """Intensity + FWHM for one mass. Intensity is text: values are like
    2.5x10^7 and will not fit a decimal field."""
    return [
        note(mass_label),
        E(f"{mass_label} Intensity  (spec {intensity_spec})",
          TEXT, report="Intensity"),
        E(f"{mass_label} FWHM amu  (spec 0.6 - 0.8)",
          DECIMAL, DP2, report="FWHM"),
    ]


def positive_ion():
    return [
        note("Guideline (10 Scans MCA):  Q1 m/z 906.673 >= 2.0x10^7  |  "
             "Q1 m/z 2242.6 >= 1.0x10^6  |  Q3 m/z 906.673 >= 2.0x10^7  |  "
             "Q3 m/z 2242.6 >= 8.0x10^5.  FWHM 0.6 - 0.8 amu throughout."),
        *reading("Q1 m/z 906.673", ">= 2.0x10^7"),
        *reading("Q1 m/z 2242.6", ">= 1.0x10^6"),
        *reading("Q3 m/z 906.673", ">= 2.0x10^7"),
        *reading("Q3 m/z 2242.6", ">= 8.0x10^5"),
    ]


def negative_ion():
    return [
        note("Guideline (10 Scans MCA):  Q1 m/z 933.636 >= 1.1x10^7  |  "
             "Q1 m/z 2037.4 >= 1.0x10^6  |  Q3 m/z 933.636 >= 9.0x10^6.  "
             "FWHM 0.6 - 0.8 amu throughout.  Q3 m/z 2037.4 is N/A."),
        *reading("Q1 m/z 933.636", ">= 1.1x10^7"),
        *reading("Q1 m/z 2037.4", ">= 1.0x10^6"),
        *reading("Q3 m/z 933.636", ">= 9.0x10^6"),
    ]


def reserpine():
    return [
        note("Guideline (10 Scans MCA):  MS/MS transmission efficiency "
             "(m/z 195.0 / attenuated m/z 609.3) x 100 >= 10.0 %"),
        helper("Use diluted reserpine 6:1 (0.16 pmol/ul). Printouts required."),
        *reading("Attenuated m/z 609.3", "record"),
        *reading("m/z 195.0", "record"),
        E("MS/MS Transmission Efficiency %  (spec >= 10.0)",
          DECIMAL, DP2, report="Transmission Efficiency %"),
    ]


def vacuum(prefix):
    return [
        note("Guideline:  CAD = 0  ->  <= 0.8x10-5 torr (0.08 V).   "
             "CAD = 12  ->  <= 5.5x10-5 torr (+/- 0.3x10-5)."),
        E(f"{prefix}Vacuum pressure at CAD = 0  (torr)",
          TEXT, report="Vacuum pressure, CAD = 0"),
        E(f"{prefix}Vacuum pressure at CAD = 12  (torr)",
          TEXT, report="Vacuum pressure, CAD = 12"),
    ]


PM_CHECKS = [
    "1. Check operation of the Turbo V ion source heaters",
    "2. Check lens voltages (Lens Power Supply module)",
    "3. Check RF tuning voltages (Q1 and Q3 QPS AMP module). "
    "Only if required, tune QPS AMPs.",
    "4. Check operation of the instrument cooling fans",
]
PM_CHECKS_2 = [
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
    "18. Clear computer temp files (Start / Search / Files and Folders -> "
    "*.tmp -> Local Hard Drive (C), (D) -> Search now -> "
    "Edit / Select All / Files / Delete / Empty Recycle Bin)",
]

# (section title, entries, page break after)
SECTIONS = [
    ("Instrument Identification", [
        note("INNOVATIVE LAB SERVICES LLC   -   API 4000 LC/MS/MS SYSTEM   -   "
             "PLANNED MAINTENANCE PROCEDURE   (Doc 1_1, Rev 1.1)"),
        # This field names the submission, the emailed PDF file and the email
        # subject — so a completed PM files itself under the instrument serial
        # instead of the "No.: 00000" placeholder.
        E("Instrument Serial #", TEXT, required=True, report="Instrument Serial #",
          auto_name=True, auto_file=True, auto_subj=True, auto_body=True),
        E("Instrument Name / INV #", TEXT, required=True,
          report="Instrument Name / INV #", auto_body=True),
    ], True),

    ("Customer Information", [
        E("Customer Site", TEXT, required=True, report="Customer Site",
          auto_body=True),
        E("Serial Number", TEXT, required=True, report="Serial Number"),
        E("Customer Name", TEXT, required=True, report="Customer Name",
          auto_body=True),
        E("Service Engineer", TEXT, required=True, report="Service Engineer",
          auto_body=True),
        E("Date", DATE, required=True, report="Date", auto_body=True),
        helper("All PM tests are run using Chemical Kit P/N 4406127. All Pre and "
               "Post tests use the Standard Turbo V Source. Printed copies of all "
               "test runs, method files and calibration runs are filed in the "
               "instrument IQ/OQ binder with a copy of this procedure."),
    ], False),

    ("Sign Off", [
        note("By signing this form you acknowledge that the planned maintenance "
             "was completely performed."),
        E("Customer signature", SIGNATURE, report="Customer"),
        E("Service Engineer signature", SIGNATURE, report="Service Engineer"),
    ], True),

    ("Pre-PM  1.0  Vacuum Pressure Check", [
        helper("Pre-PM tests do not need to pass specifications. Record Pre-PM "
               "performance."),
        *vacuum("Pre-PM "),
    ], False),

    ("Pre-PM  2.0  Positive Ion Mode Test (10 Scans MCA)", [
        helper("Printouts required. Use 50:1 diluted Standard PPG (2x10-6M)."),
        *positive_ion(),
    ], True),

    ("Pre-PM  3.0  Negative Ion Mode Test (10 Scans MCA)", [
        helper("Printouts required. Use PPG 3000 (2x10-4M) negative PPG "
               "solution, no dilution required."),
        *negative_ion(),
    ], False),

    ("Pre-PM  4.0  Reserpine MS/MS Test (10 Scans MCA)", reserpine(), True),

    ("PM Section  -  Maintenance and Cleaning", [
        *[E(c, CHECKBOX) for c in PM_CHECKS],
        E("5. Check operation of the detector. Record CEM voltage (V)",
          DECIMAL, DP1, report="CEM voltage (V)"),
        note("SHUTDOWN AND PERFORM MAINTENANCE / CLEANING"),
        E("6. Check AC input voltage. Record AC voltage (V)",
          DECIMAL, DP1, report="AC input voltage (V)"),
        *[E(c, CHECKBOX) for c in PM_CHECKS_2],
    ], True),

    ("Performance Verification  1.0  Gas Pressure", [
        note("Low Gas 1 / Gas 2 pressure can affect turbo spray and sensitivity. "
             "Source Exhaust pressure above 60 psi can cause exhaust valve "
             "failures."),
        note("Requirement:  Gas 1 / Gas 2  100 - 105 psi   |   "
             "Curtain / CAD Gas  60 psi   |   Source Exhaust Supply  55 - 60 psi"),
        E("Gas 1 / Gas 2 pressure, psi  (spec 100 - 105)",
          DECIMAL, DP1, report="Gas 1 / Gas 2 (psi)"),
        E("Curtain / CAD Gas pressure, psi  (spec 60)",
          DECIMAL, DP1, report="Curtain / CAD Gas (psi)"),
        E("Source Exhaust Supply pressure, psi  (spec 55 - 60)",
          DECIMAL, DP1, report="Source Exhaust Supply (psi)"),
    ], False),

    ("Performance Verification  2.0  Vacuum Pressure", [
        helper("Use Analyst software to set CAD gas values."),
        *vacuum(""),
    ], True),

    ("Performance Verification  3.0  Positive Ion Mode Test (10 Scans MCA)", [
        helper("Printouts required. Use 50:1 diluted Standard PPG (2x10^6M). "
               "See Appendix A."),
        *positive_ion(),
    ], True),

    ("Performance Verification  4.0  Negative Ion Mode Test (10 Scans MCA)", [
        helper("Printouts required. Use undiluted PPG 3000 (3x10^4M). "
               "See Appendix A."),
        *negative_ion(),
    ], True),

    ("Performance Verification  5.0  Reserpine MS/MS Test (10 Scans MCA)",
     reserpine(), False),

    ("6.0  Test Spectra and Comments", [
        E("Print and attach test spectra results", CHECKBOX,
          report="Test spectra printed and attached"),
        E("Comments or Observations", TEXT, report="Comments or Observations"),
        E("Additional annotation (sketch)", SKETCH, report="Annotation"),
    ], False),
]


# Simpro already starts each section on a fresh page in the generated PDF, so
# explicit breaks are redundant. Worse, setting the flag on BOTH a sheet and its
# last entry fires the break twice and emits a blank page — that is what turned
# a 14-section form into a 17-page PDF. Leave this off unless a specific block
# genuinely needs to be forced apart.
PAGE_BREAKS = False


def build_entry(spec: dict, position: int, page_break: bool) -> dict:
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
        "pdf_visibility": spec["pdf"],
        "web_visibility": 0,
        "report_label": spec["report"],
        "receipt_label": spec["report"],
        "export_label": spec["report"],
        "auto_submission_name": spec["auto_name"],
        "auto_email_filename": spec["auto_file"],
        "auto_email_subject": spec["auto_subj"],
        "auto_email_body": spec["auto_body"],
        "inserts_page_break_at_the_end": page_break,
        "entry_values": [],
        "operations": [],
        "conditions": [],
    }


def build_sections() -> list[dict]:
    out = []
    for i, (title, entries, wants_break) in enumerate(SECTIONS):
        page_break = PAGE_BREAKS and wants_break
        # Never on the entry as well as the sheet — that double-fires the break.
        built = [build_entry(e, j, False) for j, e in enumerate(entries)]
        out.append({
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
                "inserts_page_break_at_the_end": page_break,
                "style": 0,
                "integration_form": False,
                "conditions": [],
                "entries": built,
            }],
        })
    return out


def summarise(sections):
    entries = [e for s in sections for sh in s["sheets"] for e in sh["entries"]]
    names = {TEXT: "text", DECIMAL: "decimal", DATE: "date", CHECKBOX: "checkbox",
             SKETCH: "sketch", STATIC: "static", SIGNATURE: "signature"}
    counts: dict[int, int] = {}
    for e in entries:
        counts[e["original_type_id"]] = counts.get(e["original_type_id"], 0) + 1
    hidden = sum(1 for e in entries if e["pdf_visibility"] == HIDE)
    breaks = sum(1 for sh in (sh for s in sections for sh in s["sheets"])
                 if sh["inserts_page_break_at_the_end"])
    guids = [e["guid"] for e in entries]
    print(f"  {len(sections)} sections, {len(entries)} entries, "
          f"{len(set(guids))} unique guids")
    for s in sections:
        n = len(s["sheets"][0]["entries"])
        fill = sum(1 for e in s["sheets"][0]["entries"]
                   if e["original_type_id"] != STATIC)
        print(f"    {s['description'][:58]:<60} {n:>3} ({fill} fillable)")
    print("  types: " + ", ".join(f"{names.get(k, k)}={v}"
                                  for k, v in sorted(counts.items())))
    print(f"  hidden from PDF: {hidden} | page breaks: {breaks} | "
          f"report_labels: {sum(1 for e in entries if e['report_label'])}")
    assert len(set(guids)) == len(guids)
    return entries


def main() -> int:
    sections = build_sections()
    entries = summarise(sections)
    (HERE / "api4000_pro_payload.json").write_text(
        json.dumps(sections, indent=2), encoding="utf-8")

    if "--create" in sys.argv:
        # A standalone form needs no PDF upload, so it can be created outright.
        # POST /forms accepts status "new", which keeps the form editable —
        # unlike an update, which forces a transition into pending.
        name = sys.argv[sys.argv.index("--create") + 1]
        client = connect()
        payload = {
            "type": "form", "name": name, "status": "new",
            "description": "Generated from 1_1 API 4000 PM final.pdf.",
            "email_options": 2, "view_pdf_mobile": True, "web_form": False,
            "workflow_enabled": False, "dispatch_enabled": False,
            "sheet_style_enabled": True, "sections": sections,
        }
        result = client.create_form(payload)
        print(f"\n  created: {result.get('id')}  {name!r}  "
              f"status {result.get('status')}")
        return 0

    if "--into" not in sys.argv:
        print("\n  DRY RUN — nothing sent. Add --into <form_id> or "
              "--create <name>.")
        return 0

    form_id = sys.argv[sys.argv.index("--into") + 1]
    client = connect()
    existing = client.get_form(form_id, fmt="nested")
    if existing.get("sections"):
        print(f"\n  REFUSING: {existing['name']!r} already has "
              f"{len(existing['sections'])} section(s). Writing would destroy "
              "their ids and any PDF binding.")
        return 1

    payload = dict(existing)
    payload["sections"] = sections
    payload["status"] = "pending" if existing["status"] != "pending" else "new"
    print(f"\n  target: {existing['name']!r}  "
          f"({existing['status']} -> {payload['status']})")
    print(f"=== POST /forms/{form_id} ===")
    client.update_form(form_id, payload)

    check = client.get_form(form_id, fmt="nested")
    got = [e for s in check["sections"] for sh in s["sheets"] for e in sh["entries"]]
    print(f"  read back: {len(check['sections'])} sections, {len(got)} entries, "
          f"status {check['status']}")
    print(f"  report_labels kept: {sum(1 for e in got if e.get('report_label'))}")
    print(f"  hidden from PDF kept: "
          f"{sum(1 for e in got if e.get('pdf_visibility') == HIDE)}")
    print(f"  page breaks kept: "
          f"{sum(1 for e in got if e.get('inserts_page_break_at_the_end'))}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
