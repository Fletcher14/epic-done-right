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

3. **Split charts hide safety data.** The same human registered twice means the
   crew reading one chart sees half the allergy list — and never knows it.

All three are already *in the hospital system*. The gap is delivery, not data.

## Screens

### The argument, in two images
Same patient, same moment. The hospital has held this data the whole time.

**Hospital chart (EHR side)** — the violence-toward-staff flag is a 12-pixel `⚑ 1` chip in the
banner, its detail behind the *Flags* tab:

![Hospital chart with the safety flag behind a tab](docs/screenshots/05-hospital-chart.png)

**Pre-arrival, en route (crew side)** — the same flag is the first thing on the screen, before
they reach the patient. Below it, a duplicate-chart warning notes an allergy that isn't on this
record at all:

![Pre-arrival card with safety alert and duplicate warning](docs/screenshots/02-pre-arrival.png)

### The call, screen by screen

**Dispatched — active calls.** 911 calls carry a linked hospital record; inter-facility
transfers and non-medical transports don't, which is exactly where patient matching gets hard:

![CAD active call board](docs/screenshots/01-cad-active-calls.png)

**ePCR — record completion, filed after the call is cleared:**

![ePCR vitals and treatments](docs/screenshots/03-epcr-report.png)

**Transmitted — the return path.** Vitals become LOINC-coded `Observation`s (blood pressure as a
single panel with two components), interventions become `Procedure`s, each appended with a
server-assigned id — nothing merged, nothing overwritten:

![Transmission result, 11 of 11 accepted](docs/screenshots/04-epcr-transmitted.png)

## Prior art — what already exists, and what doesn't
This isn't a novel idea, and novelty isn't the point: the point is demonstrating the
integration pattern end to end. What's actually on the market:

- **ESO Health Data Exchange** — the commercial product this project mirrors.
- **Siren Notification Board** (Medusa Medical, now an ESO product) — a web board that
  alerts a receiving facility in real time to inbound patients, colour-coded by priority.

Both are strongest in the **EMS → hospital** direction: *the crew is coming, here's what
we have.* That direction is commercially solved.

The direction this project leads with is the other one — **hospital → EMS, before
arrival.** The allergy specificity and the safety flag the hospital *already holds*,
pushed out to the crew while they're still en route. Even with a notification board fully
deployed, the crew still doesn't learn about the anaphylaxis or the violence-toward-staff
flag until they walk through the door.

One more thing worth saying plainly: this capability frequently exists in products a
service already licenses and simply isn't switched on. When that's the case the obstacle
isn't technical — it's that the seam between two organisations has no owner and no budget
line. The person who'd approve it carries all the downside risk and none of the credit.

## Identity: flagged, never resolved
Patient matching is the genuinely hard problem in EMS↔hospital exchange, and it is
**deliberately not solved here**. The bridge searches for other charts with the same
family name *and* birth date, and if it finds one it reports:

> ⚠ POSSIBLE DUPLICATE CHART — this patient may have 1 other chart on file.
> ↳ 1 allergy not on this record: Sulfa drugs
> *Not merged automatically — confirm identity with the patient or receiving facility.*

It never merges, never scores, never picks a winner. A wrong merge is unrecoverable
and the bridge is the worst-placed component in the system to make an identity call —
it has the least context of anyone in the chain. So it surfaces the ambiguity and
leaves the decision to a human, mirroring the "suggest, don't delete" behaviour of
mature EHRs rather than the last-write-wins pattern that silently discards data.

**This failure is already shipping.** On the system I use day to day, transfers and other
non-emergency calls **auto-populate patient demographics from the booking**, while 911 calls
don't — nobody knows who the patient is until contact. That auto-population is routinely
wrong, and the usual flavour isn't "wrong human": it's a field or two **missing or
misaligned**, so the crew starts from a record that *looks* populated and has been verified
by nobody.

That is this project's own thesis one layer over. Allergy specificity degrading between
hospital and crew; demographics degrading between booking and ePCR. The same data decay, at
the same kind of seam — one that no single system owns.

The demo reflects it rather than pretending otherwise. The call board marks 911 records
**✓ VERIFIED** (identity confirmed at patient contact) and transfer records **⚠ PARTIAL**
(auto-populated, unverified). Open the STAT transfer and the pre-arrival card states plainly
what didn't come across — and because there is no date of birth, **the bridge does not even
attempt a duplicate check**. Incomplete data in, honest degradation out, instead of a
confident-looking blank.

The demo also shows why it matters: `pt-001` carries *Penicillin / anaphylaxis*, its
duplicate `pt-004` carries *Sulfa / Stevens-Johnson*. A crew reading either chart
alone gets half the picture.

**Known trade-off:** detection costs up to three extra searches per candidate chart,
so it is measurably slower against a real server. Capped at three candidates. A
production version would push this to a proper MPI rather than doing it in the bridge.

## Architecture
```
  hospital/   Mock hospital (the "Epic" side)
              Serves synthetic patients as FHIR R4 resources over HTTP.
                :8001  /fhir/Patient/<id>, /fhir/AllergyIntolerance?patient=<id>,
                       /fhir/Flag?patient=<id>, /fhir/MedicationRequest?patient=<id>

  bridge/     The transform layer (the part that matters).
              FHIR resources in -> flat crew "pre-arrival card" out.
              Preserves allergy specificity; promotes safety Flags to top level.

  epcr/       Mock field system (the EMS side), modelled as three moments in one call:
                :8002  /                       CAD  — active call list      [DISPATCHED]
                       /dispatch/<id>          mobile — pre-arrival card    [EN ROUTE]
                       /dispatch/<id>/report   ePCR  — record completion    [ePCR, post-call]

  data/       patients.json    hospital's own records (FHIR-shaped, synthetic)
              calls.json       CAD/call context — EMS side only
              submissions.json append-only store of what the crew pushed back
```

Inbound:  **hospital → bridge → ePCR** (pre-arrival card)
Outbound: **ePCR → bridge → hospital** (`Observation` + `Procedure`)

## One call, three moments
Real field software splits this across modules — dispatch, in-field mobile, records —
and they are used at **different points in the call**. Collapsing them into one screen
is what makes a demo read wrong to anyone who has actually run a call, so the EMS side
is staged:

| Screen | When | What it does |
|---|---|---|
| **Active calls** | dispatched | incident #, MPDS determinant, priority, unit, destination |
| **Pre-arrival** | **en route** | the hospital's safety data arrives — *inbound payoff* |
| **ePCR** | **after the call is cleared** | vitals + interventions filed → *outbound payoff* |

A stage bar (`DISPATCHED → EN ROUTE → ON SCENE → TRANSPORT → AT HOSPITAL → ePCR`) runs
across the top of each so the sequence is legible at a glance. It matters because the
two integrations fire at opposite ends of the call: the pull happens *before* the crew
reaches the patient, the push happens *after* they have left the hospital.

Note the data separation: CAD context lives in `calls.json` on the EMS side. The
hospital has no idea which unit is responding or what the determinant was — it
shouldn't, and `patients.json` never carries it.

## The return path (ePCR → hospital)
The other half of a real bridge. The crew fills in vitals and interventions at
`/dispatch/<id>/report`; `transform_to_fhir()` — the mirror of `transform_to_card()` —
turns that flat form into proper FHIR and POSTs it back:

| Crew enters | Becomes |
|---|---|
| HR 118 | `Observation` · LOINC `8867-4` · `118 /min` |
| SpO₂ 94 | `Observation` · LOINC `59408-5` · `94 %` |
| BP 88/54 | **one** `Observation` · LOINC `85354-9` with components `8480-6` / `8462-4` |
| "IV access established" | `Procedure` · status `completed` · performer MEDIC 4 |

Blood pressure is modelled the way the spec actually calls for — a single panel
Observation with two components, not two separate Observations.

The outbound transform emits **fully coded** CodeableConcepts (`coding` *and* `text`).
Pushing bare text back would recreate, in the opposite direction, the exact
specificity loss this project exists to fix on the way in. LOINC codes are real;
interventions are deliberately left text-coded rather than inventing SNOMED codes
that couldn't be verified — a production version needs a real terminology binding.

**Append-only, by design.** Submissions land in a separate `data/submissions.json`
and are given server-assigned ids and `meta.source = "#epcr-field-submission"`.
Crew data never mutates the hospital's own record, nothing is overwritten and
nothing is merged — same stance as the duplicate flagging. Read it back with:

```bash
curl "localhost:8001/fhir/Observation?patient=pt-001"
curl "localhost:8001/fhir/Procedure?patient=pt-001"
```

## Run it

### Docker (recommended)
```bash
docker compose up --build
```
- hospital → <http://localhost:8001>  (EHR chart view at `/chart/pt-001`)
- EMS side → <http://localhost:8002>  ← **start here**

Two services off one image. The ePCR reaches the hospital by **service name**
(`FHIR_BASE=http://hospital:8001/fhir`), which is the same single knob you'd turn to
point the bridge at a real FHIR server. Runs as a non-root user; the hospital gets the
data volume read-write (it receives crew submissions), the crew side gets it read-only.

### Without Docker
```bash
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./run.sh                      # starts both, Ctrl-C stops both
```

Then open **<http://localhost:8002>** and pick a call. `pt-001` (Dwyer) is the one that
shows the severe allergy, the safety flag, *and* a possible duplicate chart. From the
pre-arrival card, **FILE PATIENT REPORT** exercises the return path.

Worth viewing side by side: the hospital's own chart at
**<http://localhost:8001/chart/pt-001>** carries the same safety flag as a small chip
behind a tab — it's the first thing on the screen in the truck.

Environment:

| var | default | notes |
|---|---|---|
| `FHIR_BASE` | `http://localhost:8001/fhir` | point the bridge anywhere R4 |
| `HOST` | `127.0.0.1` | `0.0.0.0` to expose on a LAN |
| `DEBUG` | off | `1` enables the Flask debugger — never in a deployment |

Test the transform alone, no services, no browser:
```bash
python bridge/bridge.py pt-001
FHIR_BASE=https://hapi.fhir.org/baseR4 python bridge/bridge.py 137206160
```

## FHIR resources used
`Patient`, `AllergyIntolerance`, `Flag`, `MedicationRequest` — all R4.

## Hardened against a real FHIR server
The bridge is server-agnostic — point it anywhere with an env var:

```bash
FHIR_BASE=https://hapi.fhir.org/baseR4 python bridge/bridge.py 137206160
```

It was run against the public HAPI test server, and **three real failure classes
surfaced that synthetic data never would have**:

| Found | Why it broke | Fix |
|---|---|---|
| `KeyError: medicationCodeableConcept` | `medication[x]` is a FHIR **choice type** — a `MedicationRequest` carries either `medicationCodeableConcept` *or* `medicationReference` | handle both forms |
| Allergies silently became `"unknown"` | `CodeableConcept.text` is **optional**; real records often carry only `coding[].display`. Defaulting to `"unknown"` destroyed the exact specificity this project exists to preserve | fall back `text → coding.display → coding.code` |
| `HTTPError 410 Gone` | Real servers expire and delete resources | raise `PatientNotFound`, return a clean 404 |

Also: one failing search (e.g. `Flag`) no longer takes the whole card down — the
crew keeps their allergy list even if another resource type is unavailable.

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```
Transform-level and pure — dicts in, dicts out, no network, no running services.
They assert the contract the project actually promises: allergy specificity survives,
safety flags get promoted, *inactive* flags don't alarm the crew, duplicates are
flagged but never resolved, and none of the real-world shapes above crash it.

## Deliberately out of scope
- **Patient matching / MPI.** Flagged, never resolved — see *Identity* above.
- **Auth / OAuth2 / SMART-on-FHIR.** Real Epic access is gated on it; a local demo isn't.
- **Audit logging and consent.** Both are mandatory in production, neither is here.
- **A database.** JSON on disk is enough to show the pattern.
- **Terminology binding for interventions.** Text-coded on purpose (see above).

## Roadmap
- ~~Return path: an ePCR form that POSTs `Observation` + `Procedure` back.~~ **Done**
- ~~Point the bridge at a live FHIR server and handle real-world messiness.~~ **Done**
- ~~Package it so a stranger can run it.~~ **Done** — `docker compose up`
- **SMART-on-FHIR** — the remaining gap between this and something deployable. Real Epic
  access is gated on it. This bridge would need **SMART Backend Services** (`client_credentials`
  with a signed JWT assertion and `system/*.read` scopes), not the App Launch flow — nothing is
  clicked by a clinician here; a unit gets dispatched and the bridge pulls on its own.
```
