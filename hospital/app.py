"""
Mock Hospital (the 'Epic' side).

Serves synthetic patient data as FHIR R4 resources over HTTP, mirroring
the endpoints a real Epic FHIR API exposes. This is the system that, in
real life, already HAS the allergy specificity and the safety Flag — the
data just never reaches the crew before arrival.

Endpoints (FHIR-style):
    GET /fhir/Patient/<id>                       -> Patient resource
    GET /fhir/AllergyIntolerance?patient=<id>    -> Bundle of allergies
    GET /fhir/Flag?patient=<id>                  -> Bundle of safety flags
    GET /fhir/MedicationRequest?patient=<id>     -> Bundle of meds
    GET /fhir/Patient?name=<family>              -> Bundle (patient lookup)

Run:  python hospital/app.py    (listens on :8001)
"""
import json
import os
from flask import Flask, jsonify, request, abort, render_template_string

app = Flask(__name__)

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "patients.json")
with open(DATA_PATH) as f:
    _RECORDS = {p["id"]: p for p in json.load(f)["patients"]}


def _bundle(resources):
    """Wrap a list of resources in a minimal FHIR searchset Bundle."""
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": r} for r in resources],
    }


@app.get("/fhir/Patient/<pid>")
def get_patient(pid):
    rec = _RECORDS.get(pid)
    if not rec:
        abort(404)
    return jsonify(rec["Patient"])


@app.get("/fhir/Patient")
def search_patient():
    name = request.args.get("name", "").lower()
    hits = [r["Patient"] for r in _RECORDS.values()
            if name in r["Patient"]["name"][0]["family"].lower()]
    return jsonify(_bundle(hits))


@app.get("/fhir/AllergyIntolerance")
def get_allergies():
    pid = request.args.get("patient")
    rec = _RECORDS.get(pid)
    if not rec:
        abort(404)
    return jsonify(_bundle(rec["AllergyIntolerance"]))


@app.get("/fhir/Flag")
def get_flags():
    pid = request.args.get("patient")
    rec = _RECORDS.get(pid)
    if not rec:
        abort(404)
    return jsonify(_bundle(rec["Flag"]))


@app.get("/fhir/MedicationRequest")
def get_meds():
    pid = request.args.get("patient")
    rec = _RECORDS.get(pid)
    if not rec:
        abort(404)
    return jsonify(_bundle(rec["MedicationRequest"]))


@app.get("/")
def index():
    return jsonify({
        "service": "mock-hospital (Epic side)",
        "fhir_version": "R4",
        "patients": list(_RECORDS.keys()),
    })


CHART_PAGE = """
<!doctype html><html><head><title>Chart — {{p.name[0].family}}, {{p.name[0].given[0]}}</title>
<style>
 *{box-sizing:border-box}
 body{font-family:"Segoe UI",system-ui,sans-serif;background:#eef1f5;color:#1c2530;margin:0;font-size:13px}
 .banner{background:linear-gradient(#0b5f8a,#08496b);color:#fff;padding:.55rem 1rem;display:flex;
         align-items:center;gap:1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.3)}
 .pt{font-size:1.05rem;font-weight:700;letter-spacing:.2px}
 .demo{font-size:.78rem;color:#bcd9ea}
 .demo b{color:#fff;font-weight:600}
 .chip{margin-left:auto;display:flex;gap:.4rem}
 .flagchip{background:#8a1c1c;border:1px solid #b33;color:#ffd9d9;font-size:.68rem;font-weight:700;
           padding:.15rem .45rem;border-radius:3px}
 .algchip{background:#7a4a00;border:1px solid #b8791d;color:#ffe6bf;font-size:.68rem;font-weight:700;
          padding:.15rem .45rem;border-radius:3px}
 .tabs{background:#dde4ec;border-bottom:1px solid #b9c4d0;display:flex;padding:0 .5rem}
 .tab{padding:.4rem .85rem;font-size:.78rem;color:#40566b;border:1px solid transparent;border-bottom:none}
 .tab.on{background:#eef1f5;border-color:#b9c4d0;border-radius:3px 3px 0 0;font-weight:600;color:#0b5f8a;
         position:relative;top:1px}
 .wrap{padding:.9rem;display:grid;grid-template-columns:1fr 1fr;gap:.9rem;max-width:1000px}
 .panel{background:#fff;border:1px solid #c6cfda;border-radius:3px}
 .ph{background:#f5f7fa;border-bottom:1px solid #c6cfda;padding:.35rem .6rem;font-size:.72rem;
     font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#40566b}
 .pb{padding:.5rem .6rem}
 table{width:100%;border-collapse:collapse;font-size:.79rem}
 th{text-align:left;color:#6b7c8f;font-weight:600;border-bottom:1px solid #dde4ec;padding:.25rem .2rem;font-size:.72rem}
 td{padding:.28rem .2rem;border-bottom:1px solid #f0f3f7}
 .sev{color:#a11;font-weight:700}
 .muted{color:#8b98a6;font-style:italic}
 .buried{grid-column:1 / -1;background:#fff;border:1px dashed #c6cfda;border-radius:3px;padding:.5rem .6rem;
         font-size:.75rem;color:#6b7c8f}
 .buried b{color:#a11}
 .foot{padding:.5rem 1rem;color:#8b98a6;font-size:.7rem;border-top:1px solid #dde4ec;margin-top:.5rem}
</style></head><body>
 <div class="banner">
   <span class="pt">{{p.name[0].family|upper}}, {{p.name[0].given|join(" ")}}</span>
   <span class="demo"><b>{{p.gender|capitalize}}</b> · DOB <b>{{p.birthDate}}</b> · MRN <b>{{mrn}}</b></span>
   <span class="chip">
     {% if allergies %}<span class="algchip">ALLERGIES {{allergies|length}}</span>{% endif %}
     {% if flags %}<span class="flagchip">⚑ {{flags|length}}</span>{% endif %}
   </span>
 </div>
 <div class="tabs">
   <div class="tab on">Snapshot</div><div class="tab">Chart Review</div>
   <div class="tab">Orders</div><div class="tab">MAR</div>
   <div class="tab">Notes</div><div class="tab">Flags</div>
 </div>
 <div class="wrap">
   <div class="panel"><div class="ph">Allergies &amp; Intolerances</div><div class="pb">
     {% if allergies %}<table><tr><th>Substance</th><th>Reaction</th><th>Severity</th><th>Crit.</th></tr>
     {% for a in allergies %}<tr>
       <td><b>{{a.code.text}}</b></td>
       <td>{% if a.reaction %}{{a.reaction[0].manifestation[0].text}}{% else %}—{% endif %}</td>
       <td class="{% if a.reaction and a.reaction[0].severity=='severe' %}sev{% endif %}">
           {% if a.reaction %}{{a.reaction[0].severity}}{% else %}—{% endif %}</td>
       <td>{{a.criticality}}</td></tr>{% endfor %}</table>
     {% else %}<span class="muted">No known allergies</span>{% endif %}
   </div></div>

   <div class="panel"><div class="ph">Active Medications</div><div class="pb">
     {% if meds %}<table><tr><th>Medication</th><th>Status</th></tr>
     {% for m in meds %}<tr><td>{{m.medicationCodeableConcept.text}}</td><td>{{m.status}}</td></tr>{% endfor %}</table>
     {% else %}<span class="muted">None on file</span>{% endif %}
   </div></div>

   {% if flags %}
   <div class="buried">
     ⚑ <b>{{flags|length}} patient safety flag on file</b> — visible under the <i>Flags</i> tab.
     Present in the chart, but not pushed anywhere the responding crew can see it before arrival.
   </div>
   {% endif %}
 </div>
 <div class="foot">MOCK EHR — synthetic data. FHIR R4 API: <code>/fhir/Patient/{{pid}}</code></div>
</body></html>
"""


@app.get("/chart/<pid>")
def chart(pid):
    rec = _RECORDS.get(pid)
    if not rec:
        abort(404)
    p = rec["Patient"]
    mrn = (p.get("identifier") or [{}])[0].get("value", "")
    return render_template_string(
        CHART_PAGE, p=p, pid=pid, mrn=mrn,
        allergies=rec.get("AllergyIntolerance", []),
        flags=[f for f in rec.get("Flag", []) if f.get("status") == "active"],
        meds=[m for m in rec.get("MedicationRequest", []) if m.get("status") == "active"])


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=8001, debug=True)
