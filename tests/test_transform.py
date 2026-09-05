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
