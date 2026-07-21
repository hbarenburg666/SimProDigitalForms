# Simpro Digital Forms API v3 — verified findings

Everything below was tested against the live ILS tenant, not inferred from docs.
Base URL `https://digitalforms.simprogroup.com/api/v3` works directly; the
GoCanvas fallback was never needed. The docs host 301s to `api.gocanvas.com`.

## PDF overlay (Basic Forms) is not reachable from the API

**Conclusion: field placement cannot be automated. This is a hard limit.**

- `position` on an entry is an **ordinal** (0,1,2…) — the order fields appear in
  a list. There is no `x`, `y`, `page`, or bounding box anywhere in the schema.
- All 28 forms in the tenant return the **identical 17 form-level keys and 45
  entry-level keys**, including production PDF-overlay forms. No form carries
  extra layout data. `reference_image_id` is null on every entry in the tenant.
- 17 candidate endpoints probed — `/forms/{id}/pdf`, `/template`, `/templates`,
  `/layout`, `/attachments`, `/images`, `/reference_images`, `/background`,
  `/positions`, `/coordinates`, `/entries`, `/sheets`, `/versions`, and
  top-level `/templates`, `/images`, `/attachments`, `/reference_images` — all
  **404**.
- 8 `format=` values tried (`full`, `complete`, `detailed`, `pdf`, `layout`,
  `all`). Unknown values silently fall back to `nested`. Only `nested` (17 keys)
  and `minimal` (13 keys) are real.

Nothing in the API distinguishes a Basic form from an Advanced one.

**Untested and decisive:** does `POST /forms/{id}` on a PDF-attached form
preserve field placement, or wipe it? Coordinates are not in the payload, so the
server either keys them to entry ids or drops them. Test on a throwaway copy of
an overlay form before relying on any hybrid workflow.

## Writing forms

- `status` is **required** on `POST /forms/{id}`. Omitting it → 422.
- It is a **state transition**, not a value to echo. Sending the current status
  → `422 Cannot transition form from 'new' to 'new'`. Every write moves the form.
- `pending` → `new` is **rejected**. Transitions are directional.
- `retired` forms **cannot be modified at all** → `422 Cannot modify a retired
  form via this endpoint`. Retiring is a one-way door for API work.
- `POST /forms/{id}` mutates **in place**; it does not create a new version.
  There is no versioning-based undo.
- Net effect: you reliably get **one clean write per form**. Build correctly in a
  single `POST /forms` rather than iterating on an existing form.
- Entries survive status changes intact.

## Entry schema

- **`guid` is mandatory in practice.** Entries created with `guid: null` all
  collide — a value typed into one propagates to every other null-guid field.
  Generate a unique 40-char uppercase hex (SHA-1 shaped) per entry.
- `entry_type_id` = `original_type_id` + 10 consistently (text 0→10, decimal
  2→12, date 3→13, value list 5→15, checkbox 7→17, sketch 8→18, signature
  99→109).
- **`mask` is a decimal-place count**, as a string. Every decimal in the tenant
  carries `"0"` — zero places — which is why existing forms reject decimal
  readings. `"0.0"` is not valid and degrades to whole numbers.
  *(`"1"`/`"2"`/`"3"` believed to mean 1/2/3 places — still unconfirmed on device.)*
- `minimum`/`maximum` on a **value list** are not range validation. A 2-option
  dropdown carries `min 2.0 / max 5.0`; they act as a rendering hint.
- No numeric entry anywhere in the tenant has a real min/max, so whether the app
  enforces them on decimals remains unverified.

### Conditions (from `Part Request`, 21 working examples)

```json
{ "type": "condition", "entry_id": 770774922, "condition_type_id": 1,
  "value": "Job", "operator": 0, "sheet_id": null, "original_type_id": 0 }
```

`entry_id` is the **controlling** entry. `operator` 0 = equals, 1 = not-equals.
`sheet_type_id: 15` marks a repeatable/loop screen.

## Design note: do not set min/max on OQ readings

An OQ must be able to record an out-of-spec reading — that *is* the result.
Blocking entry would make a failing instrument unrecordable. Spec limits belong
in the field label (as the paper document prints them), with pass/fail
determined downstream from submissions.
