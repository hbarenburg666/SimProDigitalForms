# Project State — Simpro Digital Forms

_Last updated: 2026-07-22_

## Goal
An ILS field service engineer fills a preventive-maintenance (PM) form on the
Simpro Digital Forms mobile app; the completed submission produces a
**professional PDF that looks like an ILS controlled document**. ILS services
20+ instrument models, each with its own PM procedure.

## Decision so far
**The solution must be Simpro-native.** An external code-generated PDF pipeline
was prototyped (`generate_pdf.py`) and looked good — branded, with spec-aware
PASS/FAIL colouring — but was set aside because it runs outside Simpro.

## What we learned (see FINDINGS.md for evidence)
- The v3 API can **create and edit form fields** but **cannot touch the PDF
  Designer, field placement, or branding** — those are UI-only.
- `POST /forms/{id}` rebuilds the form: section/sheet ids change every write;
  entry **guid** survives and is the durable identity. Every entry needs a
  unique guid or values bleed between fields.
- Writing into a form that already has populated sections destroys their ids —
  and, for a Basic (PDF-overlay) form, the uploaded PDF binding. Only write into
  an **empty** form.
- The **PDF Designer is a frozen layer**: it survives API edits, field *values*
  flow into it by guid, but label/add/remove changes do **not** auto-propagate.
  So: finalize fields first, then design once.
- **Templates** carry both form structure and PDF design to new forms.

## The native plan (agreed direction, not yet executed)
1. ~50% of every PM form is identical across models (Instrument ID, Customer
   Info, Sign Off, Results). Design that **once** in a master template.
2. Each new model starts from the master template → inherits branding + common
   design. Only the model-specific test sections need layout; Auto Layout gives
   a first pass.
3. Claude builds all forms via API with **identical structure and naming** so
   Auto Layout is clean and per-model design is minimal.

## Open question (blocks next step)
How do the 20+ instrument models group by shared PM procedure? Families (e.g.
API 4000 / 4500 / 5500) may share a template, cutting the design count well
below 20. Flagship/high-volume models get designed first; rare ones can ride the
plain **Standard PDF** (auto-adapts, carries the account logo, zero design).

## Key scripts
| File | Purpose | Status |
|---|---|---|
| `simpro_api.py` | Auth + GET/POST client, status guard, GET-only raw escape hatch | active |
| `build_api4000_pro.py` | Build the API 4000 PM field set into an empty form (`--into`/`--create`) | the good field build |
| `explore.py` | Read-only: /me, list forms, dump a form | active |
| `make_build_sheet.py` | CSV/HTML checklist of fields for manual UI building | active |
| `edit_form.py` | Test that API edits preserve the PDF design | test |
| `generate_pdf.py` | Non-native code-generated branded PDF | shelved (native-only) |
| `fill_pdf.py` | Non-native stamp onto original PDF | shelved |
| `FINDINGS.md` | Verified API behaviour, with evidence | reference |

## Housekeeping
Many spent test forms remain in the tenant (various "Harris ... Draft/Test/New
Form N", "PDFTEST", "DRAFT5") — delete when convenient. `.env`, token cache,
dumps, PDFs and payloads are gitignored. `1_1 API 4000 Harris New Form 2`
(5891462) was accidentally deleted via a verb probe; do not repeat — only GET is
safe to send speculatively.
