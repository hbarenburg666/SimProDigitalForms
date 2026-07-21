"""
Set decimal places on every decimal entry of a form, changing nothing else.

Doubles as the decisive experiment for the hybrid workflow: field coordinates
are not present in the API payload, so this POST either preserves the PDF
placement (server keys it to entry id) or wipes it. Deliberately minimal — ids,
guids, labels, types and order are all sent back byte-identical, so placement is
the only variable.

Usage:
    python fix_masks.py <form_id> [places]           # dry run
    python fix_masks.py <form_id> [places] --apply   # POST
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent
DECIMAL = 2


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    form_id = sys.argv[1]
    places = next((a for a in sys.argv[2:] if a.isdigit()), "2")
    apply_it = "--apply" in sys.argv

    client = connect()
    form = client.get_form(form_id, fmt="nested")
    payload = copy.deepcopy(form)

    changed = 0
    for section in payload.get("sections", []):
        for sheet in section["sheets"]:
            for entry in sheet["entries"]:
                if entry.get("original_type_id") == DECIMAL and entry.get("mask") != places:
                    print(f"    {entry['id']}  mask {entry.get('mask')!r} -> {places!r}"
                          f"   {(entry.get('label') or '')[:40]}")
                    entry["mask"] = places
                    changed += 1

    entries = [e for s in payload.get("sections", []) for sh in s["sheets"]
               for e in sh["entries"]]
    print(f"\n  {form['name']!r} (id {form['id']}, status {form['status']})")
    print(f"  {len(entries)} entries, {changed} decimal masks changed to {places} place(s)")

    # Every entry keeps its server id and guid — that is what the server would
    # need in order to reattach existing PDF coordinates.
    assert all(e.get("id") for e in entries), "an entry lost its id"
    assert all(e.get("guid") for e in entries), "an entry lost its guid"
    print("  all entry ids and guids preserved")

    payload["status"] = "pending" if form["status"] != "pending" else "new"
    print(f"  status transition: {form['status']} -> {payload['status']}")

    out = HERE / f"maskfix_payload_{form_id}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  payload -> {out}")

    if not apply_it:
        print("\n  DRY RUN — nothing sent. Re-run with --apply to POST.")
        return 0

    print(f"\n=== POST /forms/{form_id} ===")
    client.update_form(form_id, payload)

    check = client.get_form(form_id, fmt="nested")
    after = [e for s in check.get("sections", []) for sh in s["sheets"]
             for e in sh["entries"]]
    print(f"  read back: status {check['status']}, {len(after)} entries "
          f"(was {len(entries)})")
    print(f"  ids unchanged: {[e['id'] for e in after] == [e['id'] for e in entries]}")
    bad = [e["id"] for e in after if e["original_type_id"] == DECIMAL
           and e["mask"] != places]
    print(f"  decimals still not {places} place(s): {len(bad)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
