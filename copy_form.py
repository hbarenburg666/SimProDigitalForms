"""
Phase 2, step 1 — prove we can CREATE a form via the API.

Copies an existing form: GET nested JSON, strip server-assigned identifiers,
rename to "{name} - Harris Barenburg Draft - API TEST", POST to /forms as a
brand-new form.

Naming rule: everything this project creates in the shared ILS tenant must carry
"Harris Barenburg" and "Draft" in the title, so it can never be mistaken for a
controlled QMS document. Enforced by name_for_created_form() below.

The source form is never modified. Dry-run by default.

Usage:
    python copy_form.py <form_id>            # dry run: build payload, save it, POST nothing
    python copy_form.py <form_id> --create   # actually POST /forms
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from simpro_api import connect

HERE = Path(__file__).resolve().parent
PAYLOAD_PATH = HERE / "copy_payload.json"
RESULT_PATH = HERE / "copy_result.json"

# Keys that identify an existing form/version on the server. If we send these
# back to POST /forms we risk updating the original instead of creating a copy,
# so they are stripped at every level of the tree.
ID_KEYS = {
    "id", "guid", "form_id", "version", "version_number", "version_id",
    "created_at", "updated_at", "published_at", "reference_id",
}
# Nested containers we recurse into.
CHILD_KEYS = ("sections", "sheets", "screens", "entries", "entry_values",
              "conditions", "operations")


# Required substrings in the title of anything we create in the shared tenant.
REQUIRED_TITLE_PARTS = ("Harris Barenburg", "Draft")


def name_for_created_form(source_name: str, tag: str = "API TEST") -> str:
    """Build a compliant title, without duplicating parts already present."""
    name = source_name
    for part in REQUIRED_TITLE_PARTS:
        if part.lower() not in name.lower():
            name = f"{name} - {part}"
    if tag and tag.lower() not in name.lower():
        name = f"{name} - {tag}"
    return name


def assert_compliant_title(name: str) -> None:
    """Hard stop before any POST: refuse to create an unattributed form."""
    missing = [p for p in REQUIRED_TITLE_PARTS if p.lower() not in name.lower()]
    if missing:
        raise SystemExit(
            f"Refusing to create form {name!r}: title must contain {missing}. "
            "Everything created in the shared ILS tenant must be attributed and "
            "marked as a draft."
        )


def strip_ids(node, depth=0, stats=None):
    """Recursively drop server-assigned keys. Returns a cleaned deep copy."""
    if stats is None:
        stats = {}
    if isinstance(node, list):
        return [strip_ids(n, depth + 1, stats) for n in node]
    if not isinstance(node, dict):
        return node

    out = {}
    for key, val in node.items():
        if key in ID_KEYS:
            stats[key] = stats.get(key, 0) + 1
            continue
        out[key] = strip_ids(val, depth + 1, stats) if key in CHILD_KEYS else val
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    form_id = sys.argv[1]
    do_create = "--create" in sys.argv

    client = connect()

    print(f"\n=== GET /forms/{form_id}?format=nested ===")
    original = client.get_form(form_id, fmt="nested")
    name = original.get("name", "(unnamed)")
    print(f"  source form: {name!r}")

    stats: dict[str, int] = {}
    payload = strip_ids(copy.deepcopy(original), stats=stats)
    payload["name"] = name_for_created_form(name)
    assert_compliant_title(payload["name"])

    PAYLOAD_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  stripped server-assigned keys: {stats or 'none found'}")
    print(f"  new name: {payload['name']!r}")
    print(f"  payload  -> {PAYLOAD_PATH} ({PAYLOAD_PATH.stat().st_size:,} bytes)")

    if not do_create:
        print("\n  DRY RUN — nothing was created. Re-run with --create to POST it.")
        return 0

    print("\n=== POST /forms ===")
    result = client.create_form(payload)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    new_id = result.get("id", "?")
    print(f"  created form id: {new_id}")
    print(f"  response -> {RESULT_PATH}")
    print(f"\n  Verify in the UI, then check the copy round-trips:")
    print(f"    python explore.py {new_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — top-level CLI guard
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
