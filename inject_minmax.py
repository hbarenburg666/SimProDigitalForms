"""
Phase 2 — the min/max experiment.

Adds three decimal entries carrying real spec ranges from the API 4000 PM
document to a target form, via POST /forms/{id}.

The point is to find out whether `minimum`/`maximum` — which the Basic Form UI
never exposes — are honoured by the mobile app when written through the API.

Usage:
    python inject_minmax.py <form_id>            # dry run, writes payload to disk
    python inject_minmax.py <form_id> --apply    # POST it

Learned the hard way about POST /forms/{id}:
  - `status` is REQUIRED in the payload (one of: new, pending, published,
    retired, archived) — omitting it returns 422.
  - It is treated as a state TRANSITION, not a value to echo back. Sending the
    form's current status returns 422 "Cannot transition form from 'new' to
    'new'". So an update necessarily changes the form's status.
  - It did NOT create a new version — the form stayed at version 1 and was
    mutated in place. Do not rely on versioning as an undo mechanism.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent

# original_type_id -> entry_type_id. Derived from observed forms: consistently
# original + 10 (text 0->10, decimal 2->12, date 3->13, checkbox 7->17,
# value list 5->15, sketch 8->18, signature 99->109).
DECIMAL = 2
ENTRY_TYPE_OFFSET = 10

SECTION_TYPE_ID = 10
SHEET_TYPE_ID = 11

# Specs transcribed from "1_1 API 4000 PM final.pdf".
#   p.7 3.0 POSITIVE ION MODE TEST  -> FWHM 0.6 - 0.8 amu
#   p.6 1.0 GAS PRESSURE           -> Gas 1 / Gas 2 100 - 105 psi
#
# `mask` controls decimal places. Every decimal in the tenant carries mask "0"
# (zero places), which is why existing forms only accept whole numbers. The
# valid vocabulary is unknown, so each probe entry carries a different mask and
# the same min/max. Typing 0.75 into each reveals which masks permit decimals;
# typing 0.9 into one that accepts decimals reveals whether max is enforced.
TEST_ENTRIES = [
    {"label": "A) mask=None  - type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": None},
    {"label": "B) mask='1'   - type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": "1"},
    {"label": "C) mask='2'   - type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": "2"},
    {"label": "D) mask='3'   - type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": "3"},
    {"label": "E) mask='0.0' - type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": "0.0"},
    {"label": "F) mask='0.00'- type 0.75 (spec 0.6-0.8)", "minimum": 0.6, "maximum": 0.8,
     "mask": "0.00"},
    # Real spec from the API 4000 document, p.6 GAS PRESSURE.
    {"label": "G) Gas 1 / Gas 2 psi - type 102 (spec 100-105)", "minimum": 100.0,
     "maximum": 105.0, "mask": "1"},
]


def new_guid() -> str:
    """40-char uppercase hex, matching the format of server-created entries.

    Entries created without a guid all share `null`, and the app keys field
    identity by guid — so a value typed into one null-guid field propagates to
    every other one. Every entry we create MUST have a unique guid.
    """
    return hashlib.sha1(uuid.uuid4().bytes).hexdigest().upper()


def build_entry(spec: dict, position: int) -> dict:
    return {
        "guid": new_guid(),
        "type": "entry",
        "label": spec["label"],
        "original_type_id": DECIMAL,
        "entry_type_id": DECIMAL + ENTRY_TYPE_OFFSET,
        "position": position,
        "required": False,
        "minimum": spec["minimum"],
        "maximum": spec["maximum"],
        "mask": spec.get("mask"),
        "visible": True,
        "read_only": False,
        "pdf_visibility": 0,
        "web_visibility": 0,
        "entry_values": [],
        "operations": [],
        "conditions": [],
    }


def build_section(position: int) -> dict:
    return {
        "type": "section",
        "description": "Min/Max Probe",
        "position": position,
        "section_type_id": SECTION_TYPE_ID,
        "hides_detailed_description": False,
        "sheets": [
            {
                "type": "sheet",
                "description": "Min/Max Probe",
                "position": 0,
                "sheet_type_id": SHEET_TYPE_ID,
                "show_sheet_name": True,
                "inserts_page_break_at_the_end": False,
                "style": 0,
                "integration_form": False,
                "conditions": [],
                "entries": [build_entry(s, i) for i, s in enumerate(TEST_ENTRIES)],
            }
        ],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    form_id = sys.argv[1]
    apply_it = "--apply" in sys.argv

    client = connect()
    form = client.get_form(form_id, fmt="nested")
    print(f"\n  target: {form['name']!r} (id {form['id']}, version {form['version']}, "
          f"status {form['status']})")
    print(f"  existing sections: {len(form.get('sections', []))}")

    payload = dict(form)
    # Drop any previous probe section so re-runs replace rather than duplicate.
    kept = [s for s in form.get("sections", []) if s.get("description") != "Min/Max Probe"]
    if len(kept) != len(form.get("sections", [])):
        print(f"  replacing {len(form['sections']) - len(kept)} existing probe section(s)")
    payload["sections"] = kept + [build_section(len(kept))]
    # `status` must be present AND must differ from the current status, or the
    # API rejects the update. Only new/pending are permitted (see
    # SimproClient.ALLOWED_WRITE_STATUSES), so ping-pong between them.
    payload["status"] = "pending" if form["status"] != "pending" else "new"
    print(f"  status transition: {form['status']} -> {payload['status']}")

    out = HERE / f"minmax_payload_{form_id}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  adding 1 section / 1 sheet / {len(TEST_ENTRIES)} decimal entries:")
    for s in TEST_ENTRIES:
        print(f"    min={s['minimum']:<7} max={s['maximum']:<7} {s['label']}")
    print(f"  payload -> {out}")

    if not apply_it:
        print("\n  DRY RUN — nothing sent. Re-run with --apply to POST.")
        return 0

    print(f"\n=== POST /forms/{form_id} ===")
    result = client.update_form(form_id, payload)
    (HERE / f"minmax_result_{form_id}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(f"  response keys: {sorted(result)[:12]}")
    print(f"  new version: {result.get('version')}  id: {result.get('id')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
