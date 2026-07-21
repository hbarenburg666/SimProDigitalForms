"""
Phase 1 — read-only exploration of the Simpro Digital Forms API.

Usage:
    python explore.py              # /me + list all forms
    python explore.py <form_id>    # also dump that form's nested JSON + summarize it

Writes form_dump.json (pretty-printed). Makes no changes to anything.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from simpro_api import connect

DUMP_PATH = Path(__file__).resolve().parent / "form_dump.json"

TYPE_NAMES = {
    0: "text",
    1: "integer",
    2: "decimal",
    3: "date",
    4: "time",
    5: "value list",
    6: "image",
    7: "checkbox",
    8: "sketch",
    9: "static text",
    10: "gps",
    21: "calculation",
    99: "signature",
}


def show_me(client) -> None:
    print("\n=== GET /me ===")
    me = client.me()
    for key in ("id", "email", "name", "company_id", "company_name", "default_department_id"):
        if key in me:
            print(f"  {key:24} {me[key]}")
    unknown = [k for k in me if k not in ("id", "email", "name", "company_id",
                                          "company_name", "default_department_id")]
    if unknown:
        print(f"  (other keys: {', '.join(sorted(unknown))})")


def show_forms(client) -> None:
    print("\n=== GET /forms ===")
    forms = client.list_forms()
    print(f"  {len(forms)} form(s)\n")
    print(f"  {'id':<12} {'status':<12} {'ver':<5} name")
    print(f"  {'-'*12} {'-'*12} {'-'*5} {'-'*50}")
    for f in forms:
        print(
            f"  {str(f.get('id','?')):<12} {str(f.get('status','?')):<12} "
            f"{str(f.get('version', f.get('version_number','?'))):<5} {f.get('name','?')}"
        )
    if client.last_rate_limit:
        print(f"\n  rate limit: {client.last_rate_limit}")


def summarize_form(form: dict) -> None:
    print("\n=== Form structure ===")
    top = {k: v for k, v in form.items() if not isinstance(v, (list, dict))}
    for k, v in top.items():
        print(f"  {k:26} {v}")

    list_keys = [k for k, v in form.items() if isinstance(v, list)]
    print(f"\n  list-valued top-level keys: {list_keys}")

    sections = form.get("sections") or form.get("screens") or []
    print(f"\n  {len(sections)} section(s)")
    total_entries = 0
    for s in sections:
        sheets = s.get("sheets") or s.get("screens") or []
        print(f"\n  ── Section {s.get('id','?')}: {s.get('name') or s.get('label','(unnamed)')}"
              f"  [{len(sheets)} sheet(s)]")
        for sh in sheets:
            entries = sh.get("entries", [])
            total_entries += len(entries)
            print(f"     Sheet {sh.get('id','?')}: {sh.get('name') or sh.get('label','(unnamed)')}"
                  f"  [{len(entries)} entries]")
            for e in entries:
                tid = e.get("original_type_id")
                flags = []
                if e.get("required"):
                    flags.append("required")
                if e.get("minimum") not in (None, ""):
                    flags.append(f"min={e['minimum']}")
                if e.get("maximum") not in (None, ""):
                    flags.append(f"max={e['maximum']}")
                if e.get("conditions"):
                    flags.append(f"conditions={len(e['conditions'])}")
                if e.get("operations"):
                    flags.append(f"operations={len(e['operations'])}")
                if e.get("mask"):
                    flags.append(f"mask={e['mask']}")
                label = (e.get("label") or "")[:44]
                print(f"        {str(e.get('id','?')):<10} "
                      f"{TYPE_NAMES.get(tid, tid):<12} {label:<46} {' '.join(flags)}")
    print(f"\n  total entries: {total_entries}")

    # What does a Basic (PDF-overlay) form look like? Surface any PDF-ish keys.
    pdf_keys = [k for k in form if "pdf" in k.lower() or "template" in k.lower()]
    print(f"  PDF/template-related top-level keys: {pdf_keys or 'none'}")


def main() -> int:
    client = connect()
    show_me(client)
    show_forms(client)

    form_id = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SIMPRO_PM_FORM_ID")
    if not form_id:
        print("\nNo form id given. Re-run as:  python explore.py <form_id>")
        print("(or set SIMPRO_PM_FORM_ID in .env)")
        return 0

    print(f"\n=== GET /forms/{form_id}?format=nested ===")
    form = client.get_form(form_id, fmt="nested")
    DUMP_PATH.write_text(json.dumps(form, indent=2, sort_keys=False), encoding="utf-8")
    print(f"  saved -> {DUMP_PATH}  ({DUMP_PATH.stat().st_size:,} bytes)")

    summarize_form(form)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — top-level CLI guard
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
