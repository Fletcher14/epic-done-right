"""
Transform tests -- the contract this project actually promises.

Deliberately pure: transform_to_card() takes dicts and returns dicts, so these
run with no network and no running services. Every case below is either the
thesis (specificity survives, flag gets promoted) or a real failure observed
against hapi.fhir.org.
"""
import bridge


def _bundle(patient=None, allergies=None, flags=None, meds=None):
    return {
        "patient": patient or {"name": [{"family": "Doe", "given": ["Jane"]}]},
        "allergies": allergies or [],
        "flags": flags or [],
        "meds": meds or [],
    }


# --- the thesis -----------------------------------------------------------
def test_allergy_specificity_survives():
    """drug + reaction + severity + criticality all cross intact."""
    card = bridge.transform_to_card(_bundle(allergies=[{
        "code": {"text": "Penicillin"},
        "criticality": "high",
        "reaction": [{"manifestation": [{"text": "Anaphylaxis"}], "severity": "severe"}],
    }]))
    a = card["allergies"][0]
    assert a == {"substance": "Penicillin", "reaction": "Anaphylaxis",
                 "severity": "severe", "criticality": "high"}


def test_safety_flag_is_promoted():
    card = bridge.transform_to_card(_bundle(flags=[
        {"status": "active", "code": {"text": "History of violence toward staff"}}]))
    assert card["safety_alerts"] == ["History of violence toward staff"]


def test_inactive_flag_is_excluded():
    """An entered-in-error/resolved flag must not alarm the crew."""
    card = bridge.transform_to_card(_bundle(flags=[
        {"status": "inactive", "code": {"text": "Old flag"}}]))
    assert card["safety_alerts"] == []


# --- real-world messiness (each observed against hapi.fhir.org) ------------
def test_allergy_with_only_coding_keeps_substance():
    """CodeableConcept.text is optional. Falling back to 'unknown' would destroy
    the very specificity this project exists to preserve."""
    card = bridge.transform_to_card(_bundle(allergies=[{
        "code": {"coding": [{"display": "Cashew nuts", "code": "227493005"}]}}]))
    assert card["allergies"][0]["substance"] == "Cashew nuts"


def test_allergy_falls_back_to_code_when_no_display():
    card = bridge.transform_to_card(_bundle(allergies=[{
        "code": {"coding": [{"code": "227493005"}]}}]))
    assert card["allergies"][0]["substance"] == "227493005"


def test_medication_reference_choice_type():
    """medication[x] is a FHIR choice type -- Reference form raised KeyError."""
    card = bridge.transform_to_card(_bundle(meds=[{
        "status": "active",
        "medicationReference": {"reference": "Medication/123", "display": "Warfarin 5mg"}}]))
    assert card["medications"] == ["Warfarin 5mg"]


def test_inactive_medication_excluded():
    card = bridge.transform_to_card(_bundle(meds=[
        {"status": "stopped", "medicationCodeableConcept": {"text": "Aspirin"}}]))
    assert card["medications"] == []


def test_allergy_without_reaction_does_not_crash():
    card = bridge.transform_to_card(_bundle(allergies=[{"code": {"text": "Dust"}}]))
    assert card["allergies"][0]["substance"] == "Dust"
    assert card["allergies"][0]["reaction"] == ""


def test_patient_without_name_does_not_crash():
    card = bridge.transform_to_card(_bundle(patient={"birthDate": "1970-01-01"}))
    assert card["name"] == "Unknown patient"


def test_empty_identifier_list_does_not_index_error():
    card = bridge.transform_to_card(_bundle(
        patient={"name": [{"family": "Doe", "given": ["Jane"]}], "identifier": []}))
    assert card["mrn"] == ""


def test_all_given_names_preserved():
    """Dropping a middle name is the same class of data loss we're fixing."""
    card = bridge.transform_to_card(_bundle(
        patient={"name": [{"family": "Dwyer", "given": ["Margaret", "Anne"]}]}))
    assert card["name"] == "Margaret Anne Dwyer"


def test_empty_bundle_is_safe():
    card = bridge.transform_to_card({})
    assert card["name"] == "Unknown patient"
    assert card["allergies"] == [] and card["safety_alerts"] == []


# --- possible-duplicate detection: flag, never resolve -----------------------
SELF = {"id": "pt-001", "name": [{"family": "Dwyer", "given": ["Margaret", "Anne"]}],
        "birthDate": "1938-11-02", "identifier": [{"value": "MRN-448201"}]}
OTHER = {"id": "pt-004", "name": [{"family": "Dwyer", "given": ["Margaret"]}],
         "birthDate": "1938-11-02", "identifier": [{"value": "MRN-902715"}]}


def _fake_search(patients=(), allergies=(), flags=()):
    def _s(resource, **params):
        return {"Patient": list(patients), "AllergyIntolerance": list(allergies),
                "Flag": list(flags)}.get(resource, [])
    return _s


def test_duplicate_chart_is_flagged_with_its_hidden_allergies(monkeypatch):
    """The clinical point: the other chart carries an allergy this record doesn't."""
    monkeypatch.setattr(bridge, "_search", _fake_search(
        patients=[SELF, OTHER], allergies=[{"code": {"text": "Sulfa drugs"}}]))
    dupes = bridge.find_possible_duplicates(SELF, "pt-001")
    assert len(dupes) == 1
    assert dupes[0]["mrn"] == "MRN-902715"
    assert dupes[0]["allergy_count"] == 1
    assert dupes[0]["allergies"] == ["Sulfa drugs"]


def test_patient_is_never_flagged_as_their_own_duplicate(monkeypatch):
    monkeypatch.setattr(bridge, "_search", _fake_search(patients=[SELF]))
    assert bridge.find_possible_duplicates(SELF, "pt-001") == []


def test_no_birthdate_means_no_duplicate_claim(monkeypatch):
    """Without a DOB the match is too weak to even suggest -- stay silent."""
    called = []
    monkeypatch.setattr(bridge, "_search", lambda r, **k: called.append(r) or [])
    no_dob = {"id": "x", "name": [{"family": "Dwyer"}]}
    assert bridge.find_possible_duplicates(no_dob, "x") == []
    assert called == []


def test_card_carries_duplicates_through(monkeypatch):
    card = bridge.transform_to_card(_bundle() | {"duplicates": [{"mrn": "MRN-902715"}]})
    assert card["possible_duplicates"] == [{"mrn": "MRN-902715"}]


def test_card_defaults_to_no_duplicates():
    assert bridge.transform_to_card(_bundle())["possible_duplicates"] == []


# --- the return path: flat crew report -> FHIR --------------------------------
REPORT = {"heart_rate": "118", "bp_systolic": "88", "bp_diastolic": "54",
          "spo2": "94", "interventions": ["IV access established"]}


def _by_text(resources, text):
    return next(r for r in resources if r["code"]["text"] == text)


def test_vitals_become_loinc_coded_observations():
    res = bridge.transform_to_fhir("pt-001", REPORT)
    hr = _by_text(res, "Heart rate")
    assert hr["resourceType"] == "Observation"
    assert hr["code"]["coding"][0] == {"system": "http://loinc.org",
                                       "code": "8867-4", "display": "Heart rate"}
    assert hr["valueQuantity"]["value"] == 118
    assert hr["valueQuantity"]["code"] == "/min"
    assert hr["subject"]["reference"] == "Patient/pt-001"


def test_blood_pressure_is_one_observation_with_two_components():
    """The spec models BP as a panel with components -- not two Observations."""
    res = bridge.transform_to_fhir("pt-001", REPORT)
    bps = [r for r in res if r.get("component")]
    assert len(bps) == 1
    codes = [c["code"]["coding"][0]["code"] for c in bps[0]["component"]]
    assert codes == ["8480-6", "8462-4"]
    assert [c["valueQuantity"]["value"] for c in bps[0]["component"]] == [88, 54]


def test_interventions_become_procedures():
    res = bridge.transform_to_fhir("pt-001", REPORT)
    proc = _by_text(res, "IV access established")
    assert proc["resourceType"] == "Procedure"
    assert proc["status"] == "completed"
    assert proc["performer"][0]["actor"]["display"] == "MEDIC 4"


def test_blank_and_non_numeric_vitals_are_skipped():
    res = bridge.transform_to_fhir("pt-001", {"heart_rate": "", "spo2": None,
                                              "resp_rate": "abc", "gcs": "14"})
    assert [r["code"]["text"] for r in res] == ["Glasgow coma score"]


def test_half_a_blood_pressure_is_not_emitted():
    """Systolic without diastolic is not a blood pressure."""
    assert bridge.transform_to_fhir("pt-001", {"bp_systolic": "88"}) == []


def test_empty_report_produces_nothing():
    assert bridge.transform_to_fhir("pt-001", {}) == []


def test_whole_numbers_stay_whole():
    res = bridge.transform_to_fhir("pt-001", {"heart_rate": "118", "temperature": "36.8"})
    assert _by_text(res, "Heart rate")["valueQuantity"]["value"] == 118
    assert _by_text(res, "Temperature")["valueQuantity"]["value"] == 36.8


def test_glucose_unit_selects_the_correct_loinc_code():
    """mmol/L and mg/dL are different LOINC codes -- not a cosmetic label."""
    mmol = bridge.transform_to_fhir("p", {"glucose": "4", "glucose_unit": "mmol/L"})[0]
    mgdl = bridge.transform_to_fhir("p", {"glucose": "72", "glucose_unit": "mg/dL"})[0]
    assert mmol["code"]["coding"][0]["code"] == "15074-8"
    assert mmol["valueQuantity"] == {"value": 4, "unit": "mmol/L",
                                     "system": "http://unitsofmeasure.org", "code": "mmol/L"}
    assert mgdl["code"]["coding"][0]["code"] == "2339-0"


def test_glucose_defaults_to_mmol_when_unit_missing():
    obs = bridge.transform_to_fhir("p", {"glucose": "4"})[0]
    assert obs["code"]["coding"][0]["code"] == "15074-8"


# --- partial records: say what's missing rather than render confident blanks ----
def test_partial_record_reports_its_gaps():
    """Auto-populated records arrive with fields missing; the card names them."""
    card = bridge.transform_to_card(_bundle(
        patient={"name": [{"family": "Kavanagh", "given": ["J"]}], "gender": "male"}))
    assert card["record_gaps"] == ["date of birth", "MRN"]


def test_complete_record_reports_no_gaps():
    card = bridge.transform_to_card(_bundle(patient={
        "name": [{"family": "Dwyer", "given": ["Margaret"]}],
        "birthDate": "1938-11-02", "identifier": [{"value": "MRN-448201"}]}))
    assert card["record_gaps"] == []
