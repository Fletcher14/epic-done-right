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

    return {
        "name": _patient_name(p),
        "mrn": _mrn(p),
        "dob": p.get("birthDate", ""),
        "gender": p.get("gender", ""),
        "safety_alerts": safety_alerts,   # <-- the gap this project closes
        "allergies": allergies,           # <-- specificity that usually gets lost
        "medications": meds,
    }


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
