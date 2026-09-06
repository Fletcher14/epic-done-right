"""
The bridge  (this is the part that matters -- the HDE core loop).

Given a patient id, it queries a FHIR server, then TRANSFORMS those FHIR
resources into a flat 'pre-arrival card' shaped for the crew.

The whole point of the project lives in transform_to_card():
  - allergy SPECIFICITY survives the crossing (drug + reaction + severity),
    instead of collapsing to "PCN allergy"
  - the safety Flag is promoted to a top-level, impossible-to-miss field,
    because the crew needs it BEFORE arrival, not buried in a chart tab

Set FHIR_BASE to point at any R4 server:
    FHIR_BASE=https://hapi.fhir.org/baseR4 python bridge/bridge.py 137204448

HARDENING NOTES (found by actually running this against hapi.fhir.org, not guessed):
  * medication[x] is a FHIR CHOICE TYPE -- MedicationRequest carries either
    medicationCodeableConcept OR medicationReference. Assuming the first
    raised KeyError on real records.
  * CodeableConcept.text is OPTIONAL. Real allergies often carry only
    coding[].display. Defaulting to "unknown" silently destroyed the exact
    specificity this project exists to preserve, so we fall back through
    text -> coding.display -> coding.code.
  * Servers return 404/410 for missing or expired resources. A patient read
    that fails should say "not found", and one failing search (e.g. Flag)
    must not take the whole card down with it.
"""
import datetime as dt
import os

import requests

HOSPITAL_BASE = os.environ.get("FHIR_BASE", "http://localhost:8001/fhir")
TIMEOUT = 15


class PatientNotFound(Exception):
    """The FHIR server has no readable Patient with that id (404/410)."""


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _get(path, **params):
    r = requests.get(f"{HOSPITAL_BASE}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _search(resource, **params):
    """A search that degrades to [] instead of taking the card down.

    Not every server exposes every resource type, and a missing Flag search
    must not cost the crew their allergy list.
    """
    try:
        return _entries(_get(resource, **params))
    except (requests.HTTPError, requests.RequestException, ValueError):
        return []


def _entries(bundle):
    return [e["resource"] for e in (bundle or {}).get("entry", []) if "resource" in e]


# --------------------------------------------------------------------------
# FHIR shape helpers -- where real-world messiness gets absorbed
# --------------------------------------------------------------------------
def _cc_text(cc):
    """CodeableConcept -> best available human string.

    text is optional in R4; plenty of real records only carry coding[].
    Falling straight to "unknown" is how allergy specificity gets lost.
    """
    if not isinstance(cc, dict):
        return ""
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding") or []:
        if c.get("display"):
            return c["display"]
        if c.get("code"):
            return c["code"]
    return ""


def _med_name(m):
    """MedicationRequest.medication[x] is a choice type: CodeableConcept OR Reference."""
    if m.get("medicationCodeableConcept"):
        return _cc_text(m["medicationCodeableConcept"])
    ref = m.get("medicationReference") or {}
    return ref.get("display") or ref.get("reference") or ""


def _patient_name(p):
    names = p.get("name") or []
    if not names:
        return "Unknown patient"
    n = names[0]
    if n.get("text"):
        return n["text"]
    given = " ".join(n.get("given") or [])
    full = f"{given} {n.get('family', '')}".strip()
    return full or "Unknown patient"


def _mrn(p):
    """identifier can be absent OR an empty list -- [0] on [] is an IndexError."""
    for ident in p.get("identifier") or []:
        if ident.get("value"):
            return ident["value"]
    return ""


def _family(p):
    return ((p.get("name") or [{}])[0].get("family") or "").strip()


def find_possible_duplicates(patient, pid, max_candidates=3):
    """Surface other charts that MAY be the same human. We never merge or score.

    Deliberately conservative: exact family name + exact birthDate. Identity
    resolution is a human decision made with context the bridge does not have,
    and a wrong merge is unrecoverable -- so we only report that another chart
    exists and what safety-relevant data is sitting on it. Split charts are a
    common way allergies go missing between systems.
    """
    fam, dob = _family(patient), patient.get("birthDate")
    if not fam or not dob:
        return []
    out = []
    for c in _search("Patient", family=fam, birthdate=dob):
        cid = c.get("id")
        if not cid or str(cid) == str(pid):
            continue
        allergies = _search("AllergyIntolerance", patient=cid)
        flags = [f for f in _search("Flag", patient=cid) if f.get("status") == "active"]
        out.append({
            "id": cid,
            "mrn": _mrn(c),
            "name": _patient_name(c),
            "dob": c.get("birthDate", ""),
            "allergy_count": len(allergies),
            "flag_count": len(flags),
            "allergies": [_cc_text(a.get("code")) or "unknown" for a in allergies],
        })
        if len(out) >= max_candidates:
            break
    return out


# --------------------------------------------------------------------------
# fetch + transform
# --------------------------------------------------------------------------
def fetch_patient_bundle(pid):
    """Pull every resource we care about for one patient."""
    try:
        patient = _get(f"Patient/{pid}")
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            raise PatientNotFound(f"No readable Patient/{pid} ({code})") from e
        raise
    return {
        "patient": patient,
        "allergies": _search("AllergyIntolerance", patient=pid),
        "flags": _search("Flag", patient=pid),
        "meds": _search("MedicationRequest", patient=pid),
        "duplicates": find_possible_duplicates(patient, pid),
    }


def transform_to_card(bundle):
    """FHIR resources -> flat crew pre-arrival card. The core of the project."""
    p = bundle.get("patient") or {}

    # Allergy specificity preserved -- drug, reaction, severity all carried across.
    allergies = []
    for a in bundle.get("allergies") or []:
        reaction, sev = "", ""
        reactions = a.get("reaction") or []
        if reactions:
            manifestations = reactions[0].get("manifestation") or []
            if manifestations:
                reaction = _cc_text(manifestations[0])
            sev = reactions[0].get("severity", "") or ""
        allergies.append({
            "substance": _cc_text(a.get("code")) or "unknown",
            "reaction": reaction,
            "severity": sev,
            "criticality": a.get("criticality", "") or "",
        })

    # Safety flags promoted to a top-level field the crew sees first.
    safety_alerts = [_cc_text(f.get("code")) or "Safety flag"
                     for f in bundle.get("flags") or []
                     if f.get("status") == "active"]

    meds = [name for name in (_med_name(m) for m in bundle.get("meds") or []
                              if m.get("status") == "active") if name]

    # Auto-populated records routinely arrive partly filled -- a field or two
    # missing or misaligned. Say so rather than rendering confident-looking blanks:
    # without a birth date the duplicate check below cannot even run.
    gaps = []
    if not p.get("birthDate"):
        gaps.append("date of birth")
    if not _mrn(p):
        gaps.append("MRN")

    return {
        "name": _patient_name(p),
        "record_gaps": gaps,
        "mrn": _mrn(p),
        "dob": p.get("birthDate", ""),
        "gender": p.get("gender", ""),
        "safety_alerts": safety_alerts,   # <-- the gap this project closes
        "allergies": allergies,           # <-- specificity that usually gets lost
        "medications": meds,
        # Flagged, never resolved: a second chart may exist for this human.
        "possible_duplicates": bundle.get("duplicates") or [],
    }


# --------------------------------------------------------------------------
# THE RETURN PATH  (ePCR -> hospital)
#
# The mirror of transform_to_card(). Flat crew report in, FHIR out.
#
# These emit FULLY CODED CodeableConcepts -- coding AND text. Pushing bare text
# back would recreate, in the opposite direction, the exact specificity loss
# this project exists to fix on the way in.
#
# LOINC codes below are real. Interventions are deliberately left text-coded:
# inventing SNOMED codes we cannot verify would be worse than honestly saying
# "this needs a terminology binding in production".
# --------------------------------------------------------------------------
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"

# (code, official LOINC display, unit label, UCUM code, human text)
# display stays the official LOINC term; text is what a clinician actually reads.
VITALS = {
    "heart_rate":  ("8867-4",  "Heart rate",             "beats/min",   "/min",    "Heart rate"),
    "resp_rate":   ("9279-1",  "Respiratory rate",       "breaths/min", "/min",    "Respiratory rate"),
    "spo2":        ("59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry",
                    "%", "%", "SpO\u2082"),
    "temperature": ("8310-5",  "Body temperature",       "\u00b0C",      "Cel",     "Temperature"),
    "gcs":         ("9269-2",  "Glasgow coma score total", "",          "{score}", "Glasgow coma score"),
}


# Glucose is reported in mmol/L in Canada/UK and mg/dL in the US. These are
# DIFFERENT LOINC codes, not the same code with a different label -- sending 4
# under the mg/dL code describes an unsurvivable patient. Units are part of the
# terminology binding.
GLUCOSE = {
    "mmol/L": ("15074-8", "Glucose [Moles/volume] in Blood", "mmol/L", "mmol/L"),
    "mg/dL":  ("2339-0",  "Glucose [Mass/volume] in Blood",  "mg/dL",  "mg/dL"),
}


def _loinc(code, display, text=None):
    """text is the human rendering; display stays the official LOINC term."""
    return {"coding": [{"system": LOINC, "code": code, "display": display}],
            "text": text or display}


def _qty(value, unit, ucum):
    """Quantity.unit is the human display and is optional -- GCS has no unit
    worth printing, and rendering '14 score' reads wrong on a chart."""
    q = {"value": value, "system": UCUM, "code": ucum}
    if unit:
        q["unit"] = unit
    return q


def _vital_category():
    return [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                         "code": "vital-signs", "display": "Vital Signs"}]}]


def _num(v):
    """Numeric, but keep whole numbers whole -- a BP of 88.0 reads wrong."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def transform_to_fhir(pid, report, unit="MEDIC 4", when=None):
    """Flat crew report -> list of FHIR Observation / Procedure resources."""
    when = when or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    subject = {"reference": f"Patient/{pid}"}
    performer = [{"display": unit}]
    out = []

    for key, (code, display, unit_txt, ucum, text) in VITALS.items():
        val = _num(report.get(key))
        if val is None:
            continue
        out.append({
            "resourceType": "Observation", "status": "final",
            "category": _vital_category(), "code": _loinc(code, display, text=text),
            "subject": subject, "effectiveDateTime": when, "performer": performer,
            "valueQuantity": _qty(val, unit_txt, ucum),
        })

    glu = _num(report.get("glucose"))
    if glu is not None:
        code, display, unit_txt, ucum = GLUCOSE.get(report.get("glucose_unit"), GLUCOSE["mmol/L"])
        out.append({
            "resourceType": "Observation", "status": "final",
            "category": _vital_category(), "code": _loinc(code, display, text="Blood glucose"),
            "subject": subject, "effectiveDateTime": when, "performer": performer,
            "valueQuantity": _qty(glu, unit_txt, ucum),
        })

    # Blood pressure is ONE Observation with two components -- not two
    # Observations. This is the shape the spec actually calls for.
    sys_v, dia_v = _num(report.get("bp_systolic")), _num(report.get("bp_diastolic"))
    if sys_v is not None and dia_v is not None:
        out.append({
            "resourceType": "Observation", "status": "final",
            "category": _vital_category(),
            "code": _loinc("85354-9", "Blood pressure panel with all children optional",
                           text="Blood pressure"),
            "subject": subject, "effectiveDateTime": when, "performer": performer,
            "component": [
                {"code": _loinc("8480-6", "Systolic blood pressure"),
                 "valueQuantity": _qty(sys_v, "mmHg", "mm[Hg]")},
                {"code": _loinc("8462-4", "Diastolic blood pressure"),
                 "valueQuantity": _qty(dia_v, "mmHg", "mm[Hg]")},
            ],
        })

    for text in report.get("interventions") or []:
        text = (text or "").strip()
        if not text:
            continue
        out.append({
            "resourceType": "Procedure", "status": "completed",
            "code": {"text": text},          # text-only, on purpose -- see note above
            "subject": subject, "performedDateTime": when,
            "performer": [{"actor": {"display": unit}}],
        })
    return out


def push_report(pid, report, unit="MEDIC 4"):
    """Transform a crew report and POST it to the hospital. Returns per-resource results."""
    results = []
    for res in transform_to_fhir(pid, report, unit=unit):
        rtype = res["resourceType"]
        label = _cc_text(res.get("code")) or rtype
        try:
            r = requests.post(f"{HOSPITAL_BASE}/{rtype}", json=res, timeout=TIMEOUT)
            ok = r.status_code in (200, 201)
            rid = r.json().get("id") if ok else None
            results.append({"resourceType": rtype, "label": label, "ok": ok,
                            "status": r.status_code, "id": rid})
        except requests.RequestException as e:
            results.append({"resourceType": rtype, "label": label, "ok": False,
                            "status": None, "id": None, "error": type(e).__name__})
    return results


def pre_arrival_card(pid):
    return transform_to_card(fetch_patient_bundle(pid))


if __name__ == "__main__":
    import sys, json
    pid = sys.argv[1] if len(sys.argv) > 1 else "pt-001"
    try:
        print(json.dumps(pre_arrival_card(pid), indent=2))
    except PatientNotFound as e:
        print(f"not found: {e}")
        sys.exit(1)
