"""
Conservatively improve an autobuilt PDF-overlay form's metadata.

Autobuild names fields from OCR fragments: four fields called "FWHM", five
called "m/z", plus "QI", "Q1", "Mass", "%". Those are ambiguous on an OQ
document, and the API exposes no coordinates, so which mass each field belongs
to CANNOT be determined from the payload. This script therefore does not guess.

What it does:
  1. Prefixes every label with P<page>.<position> so each is unique and
     traceable to its spot on the page. The original text is preserved inside.
  2. Appends a spec limit ONLY where that limit holds for every field of that
     kind on the document — FWHM is 0.6-0.8 amu everywhere, transmission
     efficiency is >= 10.0 everywhere. Gas pressures differ per row, so they
     are left alone.
  3. Sets decimal entries to 2 decimal places (autobuild leaves mask "0",
     i.e. whole numbers only).

What it deliberately does NOT do: change field types, reorder, add or remove
entries, or set minimum/maximum.

Usage:
    python relabel.py <form_id>            # dry run
    python relabel.py <form_id> --apply    # POST
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent
DECIMAL = 2
DECIMAL_PLACES = "2"

# Spec suffixes that are safe because they hold for EVERY field of that kind in
# the API 4000 PM document, independent of mass or quadrupole.
UNIVERSAL_SPECS = [
    (re.compile(r"\bFWHM\b", re.I), "spec 0.6 - 0.8 amu"),
    (re.compile(r"transmission efficiency", re.I), "spec >= 10.0 %"),
]

PREFIX = re.compile(r"^P\d+\.\d+\s")


def page_number(description: str, fallback: int) -> int:
    m = re.search(r"(\d+)", description or "")
    return int(m.group(1)) if m else fallback


def new_label(raw: str, page: int, position: int) -> str:
    text = PREFIX.sub("", (raw or "").strip())
    for pattern, spec in UNIVERSAL_SPECS:
        if pattern.search(text) and spec.lower() not in text.lower():
            text = f"{text}  ({spec})"
            break
    return f"P{page}.{position:02d} {text}"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    form_id = sys.argv[1]
    apply_it = "--apply" in sys.argv

    client = connect()
    form = client.get_form(form_id, fmt="nested")
    payload = copy.deepcopy(form)

    backup = HERE / f"baseline_{form_id}.json"
    if not backup.exists():
        backup.write_text(json.dumps(form, indent=2), encoding="utf-8")
        print(f"  baseline saved -> {backup}")

    relabelled = remasked = 0
    for si, section in enumerate(payload.get("sections", []), start=1):
        page = page_number(section.get("description", ""), si)
        for sheet in section["sheets"]:
            for entry in sheet["entries"]:
                before = entry.get("label") or ""
                after = new_label(before, page, entry.get("position", 0))
                if after != before:
                    entry["label"] = after
                    relabelled += 1
                if entry.get("original_type_id") == DECIMAL \
                        and entry.get("mask") != DECIMAL_PLACES:
                    entry["mask"] = DECIMAL_PLACES
                    remasked += 1

    entries = [e for s in payload["sections"] for sh in s["sheets"] for e in sh["entries"]]
    labels = [e["label"] for e in entries]
    types_before = [e["original_type_id"] for s in form["sections"]
                    for sh in s["sheets"] for e in sh["entries"]]
    types_after = [e["original_type_id"] for e in entries]

    print(f"\n  {form['name']!r} (id {form['id']}, status {form['status']})")
    print(f"  {len(entries)} entries | {relabelled} relabelled | {remasked} masks -> "
          f"{DECIMAL_PLACES} places")
    print(f"  labels now unique: {len(set(labels)) == len(labels)} "
          f"({len(set(labels))} distinct)")
    print(f"  field types unchanged: {types_before == types_after}")
    print(f"  entry count unchanged: {len(entries) == len(types_before)}")

    print("\n  sample:")
    for e in entries[:3] + entries[60:64]:
        print(f"    {e['label'][:72]}")

    payload["status"] = "pending" if form["status"] != "pending" else "new"
    print(f"\n  status transition: {form['status']} -> {payload['status']}")

    if not apply_it:
        print("\n  DRY RUN — nothing sent. Re-run with --apply to POST.")
        return 0

    print(f"\n=== POST /forms/{form_id} ===")
    client.update_form(form_id, payload)
    check = client.get_form(form_id, fmt="nested")
    after_entries = [e for s in check["sections"] for sh in s["sheets"]
                     for e in sh["entries"]]
    print(f"  read back: {len(after_entries)} entries, status {check['status']}")
    print(f"  guids preserved: "
          f"{[e['guid'] for e in after_entries] == [e['guid'] for e in entries]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
