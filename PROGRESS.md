# Progress report

**Epic Done Right** — a bidirectional EMS↔hospital handoff bridge on FHIR R4.
Status: **v2 complete.** Everything on the original roadmap is built, tested and documented.

| | |
|---|---|
| Commits | 11 |
| Tests | 34, no network, no running services |
| Python | 1,691 lines across 9 modules |
| Endpoints | 15 (12 GET / 3 POST) |
| FHIR resources | Patient · AllergyIntolerance · Flag · MedicationRequest · Observation · Procedure |
| Docs | README ~2,950 words, 14 sections, 6 captioned screenshots |
| Packaging | `docker compose up` — two services, one image, non-root |

---

## What shipped, in order

**v1 (inherited).** One-directional pull: hospital FHIR → bridge → crew pre-arrival card.
Allergy specificity preserved; safety `Flag` promoted to a top-level alert.

**Hardening against a real server.** Pointed the bridge at the public HAPI test server, which
broke it three ways — none of them guessed:

- `medication[x]` is a **choice type**; assuming `medicationCodeableConcept` was a hard `KeyError`
- `CodeableConcept.text` is **optional**, so real allergies fell through to `"unknown"` — silently
  destroying the exact specificity the project exists to preserve
- expired resources return **410**, which surfaced as a 500 to the crew

**The return path.** `transform_to_fhir()` — the mirror of the inbound transform. Vitals become
LOINC-coded `Observation`s (blood pressure as a single panel with two components, per spec),
interventions become `Procedure`s, POSTed to an append-only store.

**Identity.** Duplicate charts flagged on family name + birth date, **never merged, never scored**.
With no birth date the bridge declines to check at all and says so.

**Units.** Glucose bound to terminology — `mmol/L` → LOINC `15074-8`, `mg/dL` → `2339-0`. Found by
typing `4` into a field hardcoded to mg/dL, which would have stored an unsurvivable value.

**Three scenes.** The EMS side restaged as CAD → en-route → post-call ePCR, because the ePCR is
completed *after* the call is cleared. Three vendors, three visual identities.

**Packaging.** Docker compose, non-root, healthcheck-gated startup, hospital records mounted
read-only so the append-only claim is enforced by the filesystem rather than asserted.

**SMART on FHIR.** Backend Services profile — RS384-signed JWT assertion, `client_credentials`,
token caching. Verified against the SMART reference sandbox including the negative case.

---

## Design stances (the decisions worth defending)

1. **Never resolve identity.** A false merge fuses two patients and is unrecoverable. The bridge
   is the worst-placed component in the chain to make that call — it has the least context of
   anyone. So it surfaces ambiguity and stops.
2. **Append, never overwrite.** Crew submissions get server-assigned ids and a provenance tag,
   and land in a store the hospital's own records are mounted read-only against.
3. **Emit fully coded concepts.** Outbound resources carry `coding` *and* `text`. Pushing bare
   text back would recreate, in the other direction, the specificity loss fixed on the way in.
4. **Don't invent codes.** LOINC is real; interventions are text-coded on purpose rather than
   guessing at SNOMED. Stated in the limitations rather than hidden.
5. **Degrade honestly.** Partial records name what's missing instead of rendering confident blanks.
6. **Auth optional by default.** SMART engages only when configured, so the demo stays runnable.

## Known limitations (stated, not hidden)

Patient matching / MPI · auth enforcement on reads (the sandbox serves FHIR open) · audit logging
· consent · terminology binding for interventions · a database. Synthetic data throughout.

## Next

A **patient continuity layer** — many sources in, one canonical record out, with the matching
stance above generalised across systems. See `HANDOVER.md`.
