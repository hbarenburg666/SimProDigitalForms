"""
Test edit: rename, remove and add fields on a form, preserving every unchanged
entry's guid.

Purpose: find out whether an API field-edit preserves a PDF Designer layout.
Unchanged entries keep their exact guid, so if the design maps fields by guid it
survives; if it maps by section/sheet id (which the server always regenerates)
it will not. Added fields get fresh guids; removed fields are dropped.

Usage:
    python edit_form.py <form_id>            # dry run — shows the diff
    python edit_form.py <form_id> --apply    # POST it
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import uuid
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent
TEXT, DATE, VALUE_LIST = 0, 3, 5
TYPE_OFFSET = 10


def guid() -> str:
    return hashlib.sha1(uuid.uuid4().bytes).hexdigest().upper()


# --- the edits, by label match -------------------------------------------
RENAME = {"Instrument Serial #": "Instrument Serial Number"}
REMOVE = ["Additional annotation (sketch)", "Print and attach test spectra results"]
# Added to the final section. Genuinely useful PM close-out fields.
ADD = [
    dict(label="PM Completion Date", t=DATE, required=True, report="PM Completion Date"),
    dict(label="Overall PM Result", t=VALUE_LIST, report="Overall PM Result",
         values=["Pass", "Fail", "Conditional"]),
    dict(label="Recommendations / Follow-up", t=TEXT, report="Recommendations"),
]


def new_entry(spec, position):
    return {
        "guid": guid(), "type": "entry", "label": spec["label"],
        "original_type_id": spec["t"], "entry_type_id": spec["t"] + TYPE_OFFSET,
        "position": position, "required": spec.get("required", False),
        "minimum": None, "maximum": None, "mask": None, "visible": True,
        "read_only": False, "pdf_visibility": 0, "web_visibility": 0,
        "report_label": spec["report"], "receipt_label": spec["report"],
        "export_label": spec["report"],
        "entry_values": [{"type": "entry_value", "text": v, "position": i}
                         for i, v in enumerate(spec.get("values", []))],
        "operations": [], "conditions": [],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    form_id = sys.argv[1]
    apply_it = "--apply" in sys.argv

    client = connect()
    form = client.get_form(form_id, fmt="nested")
    (HERE / f"baseline_{form_id}.json").write_text(
        json.dumps(form, indent=2), encoding="utf-8")
    payload = copy.deepcopy(form)

    renamed = removed = added = 0
    for section in payload["sections"]:
        for sheet in section["sheets"]:
            kept = []
            for e in sheet["entries"]:
                label = e.get("label") or ""
                if any(r in label for r in REMOVE):
                    removed += 1
                    continue
                if label in RENAME:
                    e["label"] = RENAME[label]
                    e["report_label"] = RENAME[label]
                    renamed += 1
                kept.append(e)
            sheet["entries"] = kept
            for i, e in enumerate(sheet["entries"]):
                e["position"] = i

    last = payload["sections"][-1]["sheets"][0]
    base = len(last["entries"])
    for j, spec in enumerate(ADD):
        last["entries"].append(new_entry(spec, base + j))
        added += 1

    entries = [e for s in payload["sections"] for sh in s["sheets"] for e in sh["entries"]]
    guids = [e["guid"] for e in entries]
    orig_guids = {e["guid"] for s in form["sections"] for sh in s["sheets"]
                  for e in sh["entries"]}
    preserved = sum(1 for g in guids if g in orig_guids)

    print(f"\n  {form['name']!r} (id {form['id']}, status {form['status']})")
    print(f"  renamed {renamed}, removed {removed}, added {added}")
    print(f"  entries: {len(form['sections'][0]['sheets'][0]['entries'])}... "
          f"now {len(entries)} total")
    print(f"  guids preserved on unchanged fields: {preserved} "
          f"(of {len(orig_guids)} original)")
    print(f"  all guids unique: {len(set(guids)) == len(guids)}")

    payload["status"] = "pending" if form["status"] != "pending" else "new"
    print(f"  status transition: {form['status']} -> {payload['status']}")

    if not apply_it:
        print("\n  DRY RUN — nothing sent. Re-run with --apply.")
        return 0

    print(f"\n=== POST /forms/{form_id} ===")
    client.update_form(form_id, payload)
    check = client.get_form(form_id, fmt="nested")
    after = [e for s in check["sections"] for sh in s["sheets"] for e in sh["entries"]]
    print(f"  read back: {len(after)} entries, status {check['status']}")
    print(f"  rename applied: "
          f"{any('Instrument Serial Number' == (e.get('label') or '') for e in after)}")
    print(f"  new fields present: "
          f"{sum(1 for e in after if (e.get('label') or '') in [a['label'] for a in ADD])}")
    print("\n  >>> Now open the form's PDF Designer and check if your design survived. <<<")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
