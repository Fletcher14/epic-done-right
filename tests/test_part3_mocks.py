"""
Part 3 mock data -- the additions for patient-lookup-portal.

Two jobs, in this order:
  1. prove the existing world is untouched: the original roster, the duplicate search
     continuity-layer and the pre-arrival board rely on, the field-submission endpoint,
     and the CAD board;
  2. prove the new data is internally consistent and actually poses the problems it's
     there to pose.

Read-only throughout: nothing here POSTs, so the submissions store is never written.
"""
import importlib.util
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hospital = _load("part3_hospital_app", "hospital/app.py")
epcr = _load("part3_epcr_app", "epcr/app.py")
H = hospital.app.test_client()
E = epcr.app.test_client()

ORIGINAL = ["pt-001", "pt-002", "pt-003", "pt-004", "pt-005"]


def entries(resp):
    assert resp.status_code == 200, resp.status_code
    return [e["resource"] for e in resp.get_json()["entry"]]


def ref_id(ref):
    return ((ref or {}).get("reference") or "").split("/")[-1]


# == 1. the existing world is untouched ==========================================================

def test_the_original_roster_is_exactly_what_it_was():
    """continuity-layer reads this list and expects these five."""
    assert H.get("/").get_json()["patients"] == ORIGINAL


def test_the_dwyer_duplicate_search_still_returns_exactly_two_charts():
    hits = entries(H.get("/fhir/Patient?family=Dwyer&birthdate=1938-11-02"))
    assert sorted(p["id"] for p in hits) == ["pt-001", "pt-004"]


def test_no_scenario_patient_could_raise_a_false_duplicate_on_the_existing_board():
    """The bridge flags possible duplicates by family name + birth date."""
    originals = {((r["Patient"]["name"][0].get("family") or "").lower(), r["Patient"].get("birthDate"))
                 for r in hospital._RECORDS.values()}
    for p in hospital._SCENARIO_PATIENTS.values():
        assert (p["name"][0]["family"].lower(), p["birthDate"]) not in originals


def test_procedure_by_patient_still_serves_only_field_submissions():
    """pt-001 has a hospital procedure now -- it must not appear on the return-path endpoint."""
    assert any(ref_id(p["subject"]) == "pt-001" for p in hospital._HOSPITAL_PROCEDURES)
    for p in entries(H.get("/fhir/Procedure?patient=pt-001")):
        assert p.get("meta", {}).get("source") == "#epcr-field-submission"


def test_original_patients_charts_still_render():
    for pid in ORIGINAL:
        assert H.get(f"/chart/{pid}").status_code == 200


def test_the_cad_board_is_unchanged():
    body = E.get("/").get_data(as_text=True)
    assert "10 active" in body
    assert len(epcr.CALLS) == 10


# == 2a. hospital outcomes ==========================================================================

def test_scenario_patients_resolve_by_id_and_by_search_but_unknown_ids_still_404():
    assert H.get("/fhir/Patient/pt-101").get_json()["name"][0]["family"] == "Walsh"
    assert [p["id"] for p in entries(H.get("/fhir/Patient?family=coady"))] == ["pt-102"]
    assert H.get("/fhir/Patient/pt-999").status_code == 404


def test_the_later_identified_patient_carries_the_temporary_mrn():
    ids = H.get("/fhir/Patient/pt-101").get_json()["identifier"]
    assert {"system": "urn:mrn", "value": "TEMP-7731", "use": "temp"} in ids


def test_unbounded_outcome_searches_return_nothing():
    for path in ("/fhir/Encounter", "/fhir/Condition", "/fhir/MedicationAdministration"):
        assert entries(H.get(path)) == []


def test_encounter_by_id_and_by_patient():
    assert H.get("/fhir/Encounter/enc-0421").get_json()["subject"]["reference"] == "Patient/pt-002"
    assert H.get("/fhir/Encounter/enc-nope").status_code == 404
    assert {e["id"] for e in entries(H.get("/fhir/Encounter?patient=pt-003"))} == {"enc-0430", "enc-0438", "enc-0802"}


def test_every_reference_in_the_outcome_data_resolves():
    patients = set(ORIGINAL) | set(hospital._SCENARIO_PATIENTS)
    conditions = {c["id"]: c for c in hospital._CONDITIONS}
    for e in hospital._ENCOUNTERS.values():
        assert ref_id(e["subject"]) in patients
        for d in e["diagnosis"]:
            cond = conditions[ref_id(d["condition"])]
            assert ref_id(cond["encounter"]) == e["id"]
    for r in hospital._HOSPITAL_PROCEDURES + hospital._MED_ADMINISTRATIONS:
        eid = ref_id(r.get("encounter") or r.get("context"))
        assert eid in hospital._ENCOUNTERS
        for reason in r["reasonReference"]:
            assert ref_id(conditions[ref_id(reason)]["encounter"]) == eid, "treatment reason on another visit"


def test_codes_come_from_the_real_fhir_value_sets():
    for e in hospital._ENCOUNTERS.values():
        assert e["class"]["code"] in {"EMER", "IMP"}
        assert e["status"] in {"in-progress", "finished"}
        for d in e["diagnosis"]:
            assert d["use"]["coding"][0]["code"] in {"CC", "AD", "DD", "CM", "billing"}
        disp = e.get("hospitalization", {}).get("dischargeDisposition")
        if disp:
            assert disp["coding"][0]["code"] in {"home", "alt-home", "other-hcf", "hosp", "long", "aadvice",
                                                 "exp", "psy", "rehab", "snf", "oth"}
    for c in hospital._CONDITIONS:
        assert c["verificationStatus"]["coding"][0]["code"] in {"confirmed", "provisional"}
        assert re.fullmatch(r"[A-Z]\d\d(\.\d+)?", c["code"]["coding"][0]["code"])


def test_the_mixed_sensitive_visit_really_poses_the_problem():
    """Overdose + opioid dependence, a treatment on each, and a psychiatric disposition."""
    conds = {c["id"]: c["code"]["coding"][0]["code"] for c in entries(H.get("/fhir/Condition?encounter=enc-0903"))}
    assert set(conds.values()) == {"T40.2", "F11.2"}
    reasons = {conds[ref_id(m["reasonReference"][0])] for m in entries(H.get("/fhir/MedicationAdministration?encounter=enc-0903"))}
    assert reasons == {"T40.2", "F11.2"}
    assert H.get("/fhir/Encounter/enc-0903").get_json()["hospitalization"]["dischargeDisposition"]["coding"][0]["code"] == "psy"


def test_hospital_procedures_are_served_by_encounter():
    procs = entries(H.get("/fhir/Procedure?encounter=enc-0421"))
    assert [p["code"]["text"] for p in procs] == ["Percutaneous coronary intervention"]


# == 2b. ePCR reports ==============================================================================

def test_practitioner_carries_the_license():
    p = E.get("/fhir/Practitioner/lic-10231").get_json()
    assert p["identifier"] == [{"system": "urn:mock:paramedic-license", "value": "LIC-10231"}]
    assert E.get("/fhir/Practitioner/lic-00000").status_code == 404


def test_every_attendant_resolves_to_a_practitioner():
    for r in epcr._REPORTS.values():
        for v in r["versions"]:
            for a in v["attendants"]:
                assert E.get(f"/fhir/Practitioner/{a['license'].lower()}").status_code == 200


def test_reports_on_the_cad_board_match_real_incidents():
    board = {c["incident"] for c in epcr.CALLS}
    for r in epcr._REPORTS.values():
        assert (r["incident"] in board) == r["on_cad_board"]


def test_a_composition_is_served_at_its_latest_version():
    c = E.get("/fhir/Composition/pcr-2026-0903-0212").get_json()
    assert c["meta"]["versionId"] == "2" and c["status"] == "final"
    assert c["section"][0]["title"] == "Field impression" and "Opioid overdose" in c["section"][0]["text"]["div"]


def test_history_holds_every_version_newest_first():
    hist = entries(E.get("/fhir/Composition/pcr-2026-0906-0105/_history"))
    assert [h["meta"]["versionId"] for h in hist] == ["2", "1"]
    assert [h["status"] for h in hist] == ["preliminary", "final"]


def test_provenance_signed_vs_unsigned():
    provs = entries(E.get("/fhir/Provenance?target=Composition/pcr-2026-0906-0105"))
    v1, v2 = sorted(provs, key=lambda p: p["id"])
    assert v1["signature"] and "signature" not in v2
    assert "Practitioner/lic-61120" in [a["who"]["reference"] for a in v2["agent"]]


def test_a_student_is_an_agent_but_never_a_signer():
    prov = entries(E.get("/fhir/Provenance?target=Composition/pcr-2026-0905-0417"))[0]
    roles = {a["who"]["reference"]: a["role"][0]["text"] for a in prov["agent"]}
    assert roles["Practitioner/stu-3001"] == "student"
    assert "Practitioner/stu-3001" not in [s["who"]["reference"] for s in prov["signature"]]


def test_attester_search_finds_reports_a_practitioner_was_amended_off():
    found = entries(E.get("/fhir/Composition?attester=Practitioner/lic-55310"))
    assert [c["identifier"]["value"] for c in found] == ["2026-0903-0212"]


def test_unbounded_composition_search_returns_nothing():
    assert entries(E.get("/fhir/Composition")) == []


def test_the_unidentified_patient_is_recorded_without_a_name():
    c = E.get("/fhir/Composition/pcr-2026-0906-0105").get_json()
    pt = c["contained"][0]
    assert "name" not in pt and pt["gender"] == "male"
    assert pt["identifier"] == [{"system": "urn:mrn", "value": "TEMP-7731"}]
    assert pt["extension"][0]["valueAge"]["value"] == 35


def test_field_impression_is_escaped():
    c = E.get("/fhir/Composition/pcr-2026-0905-0417").get_json()
    assert "<script" not in c["section"][0]["text"]["div"]
