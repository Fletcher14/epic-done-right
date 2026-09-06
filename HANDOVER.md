# Handover — Epic Done Right → Patient Continuity Layer

> For the next handler working with Manny on **i7-local**. This supersedes the
> original v1 handover. **v2 is COMPLETE — do not rebuild any of it.** Read
> `PROGRESS.md` for what shipped and `README.md` for the argument it makes.

---

## State

Complete and pushed to Gitea (`Manny/epic-done-right`). 11 commits, 34 tests, six
screenshots, `docker compose up` works, SMART Backend Services verified against the
reference sandbox. Everything on the original roadmap is done.

Running it: `docker compose up -d` → hospital :8001, EMS side :8002.
Reset the submission store: `docker exec edr-hospital sh -c 'echo "{\"resources\":[]}" > /app/state/submissions.json' && docker compose restart hospital`

## Domain facts Manny supplied — these are not in any documentation

These came from him working the job, and they shaped the whole project. A fresh
session cannot derive them and should not contradict them:

1. **The ePCR is completed *after* the call is cleared**, not during. That's why the
   EMS side is staged CAD → en-route → post-call rather than one screen.
2. **911 calls have no Epic↔Siren transmit at all**, either direction. Identity is
   established when the crew reaches the patient.
3. **Transfers/routines auto-populate demographics** via `transfer booking → iNetCAD →
   Siren ePCR`. It's frequently wrong — and the usual flavour is **a field or two
   missing or misaligned**, not the wrong human.
4. **Palliative patients are the one exception**: iNet is configured to link their
   palliative care chart. That is the *entire* list of connected clinical records.
   This is the strongest fact in the project — capability exists, deployed once.
5. **Glucose is mmol/L** in his practice. A form hardcoded to mg/dL stored `4` as a
   lethal value; units are now bound to distinct LOINC codes.
6. Context: he wrote a real Epic↔Siren proposal at work; it was killed pre-adoption
   with *"why would it help."* This project is that proposal made runnable.

## Design stances — preserve these, they are the point

- **Never resolve identity.** Flag duplicates, never merge, never score. With no DOB,
  decline to check and say so. A false merge is unrecoverable.
- **Append, never overwrite.** Provenance-tagged; hospital records mounted read-only.
- **Emit fully coded CodeableConcepts** (`coding` *and* `text`) on the way out.
- **Don't invent codes** you can't verify. Say so in limitations instead.
- **Degrade honestly** — name missing fields rather than render confident blanks.
- **Auth optional by default**, so the demo runs for anyone who clones it.

## Working style

Sysadmin brain, 12+ years self-taught, direct and terse. Verify-before-trust — probe a
feed and let it break rather than guessing what it returns. Prefers full-file rewrites
over patches, and paste-ready blocks. Wants to be talked *through* things, then does
them himself. Give honest reads and flag scope creep. He will correct domain errors —
he did so three times on the call board and was right every time; take the correction
and rebuild rather than defending the model.

He is pivoting to health IT and this is career-relevant, not a toy. Screenshots and the
README are the deliverable for a non-technical reader; treat them as first-class.

---

## Next: Patient Continuity Layer

Full spec is in `continuity-layer-BUILD-SPEC.md` (Manny has it). Many sources in →
one canonical record → many consumers out. Adapters normalize to FHIR, a matcher groups
by patient, a canonical store owns the truth, consumers read the layer not the sources.

**Already built here, do not redo:**

| Spec calls for | Status |
|---|---|
| Normalize to one FHIR model | ✅ `transform_to_card` / `transform_to_fhir` |
| Flag unsure matches, don't auto-merge | ✅ `find_possible_duplicates` + tests |
| Keep both + provenance on conflict | ✅ append-only store, `meta.source` |
| A FHIR source | ✅ `hospital/` |
| Consumers | ✅ pre-arrival card, EHR chart |

**Genuinely remaining:** a second source in a deliberately different format (CSV/JSON),
per-source adapters, the matcher generalised to cross-source grouping with canonical ids,
the canonical store, and a merged view showing per-fact provenance.

**Open decision for Manny — ask before building:** new repo, or extend this one?
Recommendation was a **new repo that reuses `hospital/`**, because this project currently
has a tight complete argument and bolting a hub onto it dilutes that; two finished focused
projects beat one sprawling one. He has not decided.

**Also open:** whether source B should be generic "dispatch", or modelled on the real
transfer-booking feed from fact 3 above — the latter would let the matcher chew on
genuinely messy demographics and connect to his lived example.

**Scope fence — the spec's own out-of-scope list, enforce it:** no fuzzy/probabilistic
matching at scale, no real HL7v2 parsing, no auth/DB/live servers, no conflict
auto-resolution beyond keep-both-with-provenance. Demo cut only until it runs end to end.
