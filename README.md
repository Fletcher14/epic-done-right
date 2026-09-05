# Epic Done Right — a pre-arrival handoff bridge (FHIR R4)

A small, working demonstration of the EMS↔hospital data handoff that most
real deployments still don't close: pushing the hospital's existing patient
safety information **out to the crew before they arrive**, instead of leaving
it trapped in the EHR.

Built as a learning/portfolio project against synthetic data only. It mirrors
the core loop of commercial products like ESO Health Data Exchange — not to
replace them, but to prove the integration pattern end to end.

## The problem it demonstrates
At handoff, two failures happen constantly:
1. **Allergy specificity is lost.** The hospital knows "Penicillin — anaphylaxis
   (high criticality)." The crew record often shows only "PCN allergy."
2. **Safety flags don't reach the crew in time.** The EHR carries a documented
   violence-toward-staff flag. The crew finds out on arrival, not before.

Both are already *in the hospital system*. The gap is delivery, not data.

## Architecture
```
  hospital/   Mock hospital (the "Epic" side)
              Serves synthetic patients as FHIR R4 resources over HTTP.
                :8001  /fhir/Patient/<id>, /fhir/AllergyIntolerance?patient=<id>,
                       /fhir/Flag?patient=<id>, /fhir/MedicationRequest?patient=<id>

  bridge/     The transform layer (the part that matters).
              FHIR resources in -> flat crew "pre-arrival card" out.
              Preserves allergy specificity; promotes safety Flags to top level.

  epcr/       Mock ePCR (the "Siren/iNet" side, crew-facing).
                :8002  /dispatch/<id>  -> renders the pre-arrival card in a browser

  data/       Synthetic, hand-authored, FHIR-shaped patient records.
```

Data flow (one direction for v1): **hospital → bridge → ePCR**.

## Run it
Two terminals (the ePCR calls the hospital):

```bash
# terminal 1 — the hospital FHIR API
python hospital/app.py          # http://localhost:8001

# terminal 2 — the crew ePCR view
python epcr/app.py              # http://localhost:8002
```

Then open **http://localhost:8002** and dispatch to a patient.
`pt-001` (Dwyer) is the one that shows both the severe allergy and the safety flag.

Test the transform alone, no browser:
```bash
python bridge/bridge.py pt-001
```

## FHIR resources used
`Patient`, `AllergyIntolerance`, `Flag`, `MedicationRequest` — all R4.
The resource shapes match the real spec, so the same bridge logic points at a
real FHIR server with only a base-URL change. To prove that, aim `HOSPITAL_BASE`
in `bridge/bridge.py` at the public HAPI test server:
`https://hapi.fhir.org/baseR4` (read-only, synthetic data, no auth).

## Deliberately out of scope for v1
- **Reverse direction** (ePCR → hospital: vitals, interventions, narrative pushed
  back). This is v2 and is the other half of a real bidirectional bridge.
- Auth / OAuth2 / SMART-on-FHIR. Real Epic needs it; a local demo doesn't.
- A database. JSON on disk is enough to show the pattern.

## v2 roadmap (when v1 feels solid)
1. Add the return path: an ePCR form that POSTs an `Observation` (vitals) and
   `Procedure` (interventions) back to the hospital as FHIR.
2. Point the bridge at the live HAPI server and handle real-world messiness
   (missing fields, unexpected shapes).
3. Add SMART-on-FHIR OAuth2 against a sandbox to make it deployment-shaped.
```
```
