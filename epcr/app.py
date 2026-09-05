"""
Mock field system (the EMS side).

Modelled as three moments in one call, because that is how real public-safety
software is actually split -- dispatch, in-field mobile, records -- and they are
used at different points:

    /                       CAD   -- active call list          [DISPATCHED]
    /dispatch/<id>          mobile -- pre-arrival card         [EN ROUTE]
    /dispatch/<id>/report   ePCR  -- record completion         [ePCR, post-call]

The pre-arrival pull happens before the crew reaches the patient; the ePCR push
happens after the call is cleared. Collapsing them into one screen is what makes
a demo read wrong to anyone who has run a call.

Run:  python epcr/app.py    (listens on :8002)
Requires the hospital app on :8001.
"""
import json
import sys
import os
from flask import Flask, render_template_string, abort, request
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))
import bridge  # noqa: E402

app = Flask(__name__)

CALLS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "calls.json")
try:
    with open(CALLS_PATH) as _fh:
        CALLS = json.load(_fh).get("calls", [])
except (FileNotFoundError, ValueError):
    CALLS = []


def call_for(pid):
    """Not every call has a hospital record behind it -- transfers and
    non-medical transports usually don't, which is why the linked ones matter."""
    return next((c for c in CALLS if c.get("patient") == pid), {})

STAGES = ["DISPATCHED", "EN ROUTE", "ON SCENE", "TRANSPORT", "AT HOSPITAL", "ePCR"]

INTERVENTIONS = ["IV access established", "12-lead ECG acquired", "Oxygen administered",
                 "Cardiac monitor applied", "Spinal motion restriction", "Medication administered"]


def stage_bar(active):
    cells = []
    for i, name in enumerate(STAGES):
        cls = "st on" if i == active else ("st done" if i < active else "st")
        cells.append(f'<span class="{cls}">{name}</span>')
    return '<div class="stages">' + "".join(cells) + "</div>"


# Light, dense, utilitarian -- the idiom of public-safety software. Deliberately
# a different palette from the hospital side: two vendors, not one system.
CSS = """
 *{box-sizing:border-box}
 body{font-family:"Segoe UI",system-ui,-apple-system,sans-serif;background:#eef1f5;color:#1b2530;
      margin:0;font-size:13px}
 a{color:#1f6bb8;text-decoration:none}
 .topbar{background:#1c2a3a;color:#fff;padding:.45rem .8rem;display:flex;align-items:center;gap:.7rem}
 .brand{font-weight:800;letter-spacing:.09em;font-size:.82rem;color:#7fb4ea}
 .mode{background:#2b7cd3;font-size:.64rem;font-weight:700;letter-spacing:.11em;padding:.16rem .5rem;border-radius:2px}
 .right{margin-left:auto;font-family:ui-monospace,monospace;font-size:.74rem;color:#9fb3c8}
 .stages{display:flex;gap:2px;background:#243444;padding:0 .5rem}
 .st{font-size:.6rem;font-weight:700;letter-spacing:.09em;padding:.3rem .6rem;color:#6a8098}
 .st{color:#6a8098}
 .st.done{color:#9fb3c8}
 .st.on{background:#eef1f5;color:#1c2a3a}
 .wrap{padding:.6rem}
 .banner{padding:.55rem .8rem;font-weight:700;display:flex;align-items:baseline;gap:.6rem;
         border:1px solid;border-radius:2px;margin-bottom:.5rem}
 .b-red{background:#fde8e8;border-color:#c0392b;color:#7e1c14}
 .b-amber{background:#fdf4e3;border-color:#c98a13;color:#7a520a}
 .banner .tag{font-size:.62rem;font-weight:800;letter-spacing:.11em;padding:.1rem .35rem;border-radius:2px;color:#fff}
 .b-red .tag{background:#c0392b}
 .b-amber .tag{background:#c98a13}
 .banner .txt{font-size:.95rem}
 .banner .sub{font-weight:400;font-size:.76rem;font-family:ui-monospace,monospace}
 .idstrip{background:#fff;border:1px solid #c6cfda;border-radius:2px;padding:.45rem .7rem;
          display:flex;align-items:baseline;gap:.9rem;flex-wrap:wrap;margin-bottom:.5rem}
 .idstrip .nm{font-size:1.05rem;font-weight:700}
 .idstrip .dm{color:#5c6d80;font-family:ui-monospace,monospace;font-size:.76rem}
 .idstrip .inc{margin-left:auto;font-family:ui-monospace,monospace;font-size:.74rem;color:#5c6d80}
 .cols{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
 @media(max-width:860px){.cols{grid-template-columns:1fr}}
 .panel{background:#fff;border:1px solid #c6cfda;border-radius:2px}
 .ph{background:#f5f7fa;border-bottom:1px solid #c6cfda;padding:.3rem .6rem;font-size:.66rem;
     font-weight:800;text-transform:uppercase;letter-spacing:.09em;color:#48607a;display:flex;gap:.5rem}
 .ph .n{margin-left:auto;color:#8496a8}
 .pb{padding:.4rem .6rem}
 table{width:100%;border-collapse:collapse;font-size:.79rem}
 th{text-align:left;color:#6b7c8f;font-weight:700;border-bottom:1px solid #dde4ec;padding:.2rem;font-size:.66rem;
    text-transform:uppercase;letter-spacing:.05em}
 td{padding:.26rem .2rem;border-bottom:1px solid #f0f3f7}
 tr:last-child td{border-bottom:none}
 .sev{color:#b3261e;font-weight:800}
 .muted{color:#8496a8;font-style:italic}
 .pri{font-size:.62rem;font-weight:800;letter-spacing:.07em;padding:.1rem .4rem;border-radius:2px;color:#fff;
      font-family:ui-monospace,monospace}
 .pri.DELTA{background:#c0392b}.pri.CHARLIE{background:#c46a10}.pri.BRAVO{background:#a08800}
 .pri.ALPHA{background:#2b7a4b}.pri.ECHO{background:#8e1b1b}
 .pri.STAT{background:#a5161f}.pri.URGENT{background:#c46a10}
 .pri.ROUTINE{background:#5a6b7d}.pri.SCHEDULED{background:#7d8894}
 .typ{font-size:.6rem;font-weight:800;letter-spacing:.06em;padding:.08rem .32rem;border-radius:2px;
      font-family:ui-monospace,monospace;border:1px solid}
 .typ.t911{background:#fdeaea;border-color:#d98080;color:#8e1b1b}
 .typ.tIFT{background:#eef2f8;border-color:#9fb3cc;color:#2c4a70}
 .typ.tNMT{background:#f1f3f5;border-color:#c0c7ce;color:#5a6b7d}
 .nolink{color:#a8b4be;font-family:ui-monospace,monospace;font-size:.72rem}
 .calls tr.dead:hover{background:transparent;cursor:default}
 .calls td{padding:.34rem .3rem;font-size:.8rem}
 .calls tr:hover{background:#f5f8fc;cursor:pointer}
 .calls .nat{font-weight:700}
 .mono{font-family:ui-monospace,monospace;font-size:.76rem;color:#5c6d80}
 .linked{background:#e6f4ea;border:1px solid #86c79b;color:#1d6b38;font-size:.6rem;font-weight:700;
         padding:.06rem .3rem;border-radius:2px;white-space:nowrap}
 .btn{display:inline-block;background:#2b7cd3;border:1px solid #1f6bb8;color:#fff;font-weight:700;
      letter-spacing:.05em;font-size:.78rem;padding:.45rem .9rem;border-radius:2px;cursor:pointer}
 .btn:hover{background:#1f6bb8}
 .btn.wide{display:block;width:100%;text-align:center;padding:.6rem;font-size:.85rem}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:.4rem}
 label.f{display:block;font-size:.62rem;letter-spacing:.07em;text-transform:uppercase;color:#6b7c8f;margin-bottom:.12rem}
 input[type=number],input[type=text],select{width:100%;background:#fff;border:1px solid #c6cfda;color:#1b2530;
   border-radius:2px;padding:.32rem .4rem;font-size:.88rem;font-family:ui-monospace,monospace}
 input:focus,select:focus{outline:none;border-color:#2b7cd3}
 .ivs{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.25rem}
 .chk{display:flex;align-items:center;gap:.45rem;font-size:.79rem;padding:.22rem .3rem;border:1px solid #dde4ec;
      border-radius:2px;background:#fbfcfe;cursor:pointer}
 .chk input{width:15px;height:15px;accent-color:#2b7cd3}
 .ok{background:#e6f4ea;border:1px solid #86c79b;color:#14532d;padding:.35rem .6rem;border-radius:2px;margin:.2rem 0;font-size:.8rem}
 .bad{background:#fde8e8;border:1px solid #d98080;color:#7e1c14;padding:.35rem .6rem;border-radius:2px;margin:.2rem 0;font-size:.8rem}
 .foot{color:#8496a8;font-size:.68rem;padding:.7rem .8rem}
"""


# ---------------------------------------------------------------------------
# The ePCR is a DIFFERENT VENDOR from the CAD/mobile side, so it gets its own
# look. Idiom taken from what the product family documents about itself: rugged
# tablet, offline-capable, and navigation that "follows the logic flow that
# clinicians are trained to assess and treat" -- i.e. clinical section tabs,
# not one flat form. Three systems, three looks, none of them talking to each
# other: that is the problem this project is about.
# ---------------------------------------------------------------------------
SIREN_CSS = """
 *{box-sizing:border-box}
 body{font-family:"Segoe UI",system-ui,-apple-system,sans-serif;background:#f2f5f4;color:#14201d;
      margin:0;font-size:13.5px}
 a{color:#0f6e64;text-decoration:none}
 .sbar{background:#0f6e64;color:#fff;padding:.5rem .85rem;display:flex;align-items:center;gap:.7rem}
 .sbar .b{font-weight:800;letter-spacing:.08em;font-size:.85rem}
 .sbar .m{background:#0b544c;font-size:.64rem;font-weight:700;letter-spacing:.11em;padding:.16rem .5rem;border-radius:2px}
 .sync{margin-left:auto;display:flex;align-items:center;gap:.4rem;font-size:.7rem;
       font-family:ui-monospace,monospace;color:#bfe3dd}
 .dot{width:8px;height:8px;border-radius:50%;background:#7ee2a8;display:inline-block}
 .tabs{background:#dfe9e7;border-bottom:1px solid #b9cbc7;display:flex;padding:0 .5rem;overflow-x:auto}
 .tb{padding:.42rem .8rem;font-size:.76rem;color:#456;white-space:nowrap;border:1px solid transparent;border-bottom:none}
 .tb.on{background:#f2f5f4;border-color:#b9cbc7;border-radius:3px 3px 0 0;font-weight:700;color:#0f6e64;
        position:relative;top:1px}
 .tb.off{color:#8aa19c}
 .swrap{padding:.6rem}
 .sid{background:#fff;border:1px solid #c3d5d1;border-radius:2px;padding:.45rem .7rem;display:flex;
      align-items:baseline;gap:.9rem;flex-wrap:wrap;margin-bottom:.5rem}
 .sid .nm{font-size:1.05rem;font-weight:700}
 .sid .dm{color:#5b706b;font-family:ui-monospace,monospace;font-size:.76rem}
 .sid .rt{margin-left:auto;font-size:.74rem;color:#5b706b}
 .sec{background:#fff;border:1px solid #c3d5d1;border-radius:2px;margin-bottom:.5rem}
 .sech{background:#eef4f3;border-bottom:1px solid #c3d5d1;padding:.32rem .65rem;font-size:.68rem;
       font-weight:800;text-transform:uppercase;letter-spacing:.09em;color:#2c564f;display:flex;gap:.5rem}
 .sech .n{margin-left:auto;color:#7d968f;font-weight:600}
 .secb{padding:.45rem .65rem}
 .vgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:.4rem}
 label.sf{display:block;font-size:.62rem;letter-spacing:.07em;text-transform:uppercase;color:#5b706b;margin-bottom:.12rem}
 input[type=number],input[type=text],select{width:100%;background:#fff;border:1px solid #c3d5d1;color:#14201d;
   border-radius:2px;padding:.34rem .42rem;font-size:.9rem;font-family:ui-monospace,monospace}
 input:focus,select:focus{outline:none;border-color:#0f6e64;box-shadow:0 0 0 2px #cdeae5}
 .tgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.25rem}
 .tchk{display:flex;align-items:center;gap:.45rem;font-size:.8rem;padding:.28rem .35rem;border:1px solid #d5e3e0;
       border-radius:2px;background:#fbfdfc;cursor:pointer}
 .tchk input{width:16px;height:16px;accent-color:#0f6e64}
 .sbtn{display:block;width:100%;text-align:center;background:#0f6e64;border:1px solid #0b544c;color:#fff;
       font-weight:800;letter-spacing:.06em;font-size:.88rem;padding:.6rem;border-radius:2px;cursor:pointer}
 .sbtn:hover{background:#0b544c}
 .sok{background:#e6f4ee;border:1px solid #7cc3a5;color:#14532d;padding:.35rem .6rem;border-radius:2px;margin:.2rem 0;font-size:.8rem}
 .sbad{background:#fdeaea;border:1px solid #d98080;color:#7e1c14;padding:.35rem .6rem;border-radius:2px;margin:.2rem 0;font-size:.8rem}
 .mono{font-family:ui-monospace,monospace;font-size:.76rem;color:#5b706b}
 .muted{color:#7d968f;font-style:italic}
 .sfoot{color:#7d968f;font-size:.68rem;padding:.7rem .85rem}
"""

SECTIONS = ["Patient", "History", "Assessment", "Vitals", "Treatments", "Narrative", "Disposition"]


def section_tabs(active):
    out = []
    for name in SECTIONS:
        cls = "tb on" if name == active else "tb off"
        out.append(f'<span class="{cls}">{name}</span>')
    return '<div class="tabs">' + "".join(out) + "</div>"


SIREN_SHELL = """
<!doctype html><html><head><title>{{title}}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>""" + SIREN_CSS + """</style></head><body>
<div class="sbar"><span class="b">{{brand}}</span><span class="m">{{mode}}</span>
  <span class="sync"><span class="dot"></span>OFFLINE CAPABLE · SYNCED</span></div>
{{ tabs|safe }}
<div class="swrap">
"""
SIREN_FOOT = """</div><div class="sfoot">MOCK ePCR — synthetic data · not affiliated with any product</div>
</body></html>"""

SHELL = """
<!doctype html><html><head><title>{{title}}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>""" + CSS + """</style></head><body>
<div class="topbar"><span class="brand">{{brand}}</span><span class="mode">{{mode}}</span>
  <span class="right">{{right}}</span></div>
{{ stages|safe }}
<div class="wrap">
"""
FOOT = """</div><div class="foot">MOCK SYSTEM — synthetic data · not affiliated with any product</div>
</body></html>"""

CALLS_PAGE = SHELL + """
 <div class="panel">
  <div class="ph">Active calls <span class="n">{{calls|length}} active</span></div>
  <table class="calls">
    <tr><th>Incident</th><th>Type</th><th>Pri</th><th>Nature</th><th>Unit</th><th>Location</th>
        <th>Disp</th><th>ETA</th><th>Destination</th><th>Record</th></tr>
    {% for c in calls %}
    <tr {% if c.patient %}onclick="location='/dispatch/{{c.patient}}'"{% else %}class="dead"{% endif %}>
      <td class="mono">{{c.incident}}</td>
      <td><span class="typ t{{c.type}}">{{c.type}}</span></td>
      <td><span class="pri {{c.priority}}">{{c.priority}}{% if c.determinant %} {{c.determinant}}{% endif %}</span></td>
      <td class="nat">{{c.nature}}</td>
      <td class="mono">{{c.unit}}</td>
      <td>{{c.address}}</td>
      <td class="mono">{{c.dispatched}}</td>
      <td class="mono">{{c.eta}}</td>
      <td>{{c.destination}}</td>
      <td>{% if c.patient %}<span class="linked">✓ REC LINKED</span>
          {% else %}<span class="nolink">— no match</span>{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
 </div>
""" + FOOT

PAGE = SHELL + """
  {% for alert in c.safety_alerts %}
    <div class="banner b-red"><span class="tag">SAFETY</span><span class="txt">{{alert}}</span></div>
  {% endfor %}
  {% if c.possible_duplicates %}
    <div class="banner b-amber"><span class="tag">IDENTITY</span>
      <span class="txt">Possible duplicate chart — allergy list may be incomplete</span>
      <span class="sub">
      {%- for d in c.possible_duplicates %}{{d.mrn or d.id}}
        {%- if d.allergy_count %} · not on this record: {{d.allergies|join(", ")}}{% endif %}
      {%- endfor %} · not merged, confirm identity</span></div>
  {% endif %}

  <div class="idstrip">
    <span class="nm">{{c.name}}</span>
    <span class="dm">{{c.gender|upper}} · DOB {{c.dob}} · {{c.mrn}}</span>
    {% if call %}<span class="inc">INC {{call.incident}} · {{call.nature}} · {{call.address}}
      · enr {{call.enroute}} → {{call.destination}}</span>{% endif %}
  </div>

  <div class="cols">
    <div class="panel"><div class="ph">Allergies &amp; intolerances <span class="n">{{c.allergies|length}}</span></div><div class="pb">
      {% if c.allergies %}<table><tr><th>Substance</th><th>Reaction</th><th>Severity</th><th>Crit.</th></tr>
      {% for a in c.allergies %}<tr><td><b>{{a.substance}}</b></td><td>{{a.reaction or "—"}}</td>
        <td class="{% if a.severity=='severe' %}sev{% endif %}">{{a.severity or "—"}}</td>
        <td>{{a.criticality or "—"}}</td></tr>{% endfor %}</table>
      {% else %}<span class="muted">No known allergies</span>{% endif %}
    </div></div>
    <div class="panel"><div class="ph">Current medications <span class="n">{{c.medications|length}}</span></div><div class="pb">
      {% if c.medications %}<table>{% for m in c.medications %}<tr><td>{{m}}</td></tr>{% endfor %}</table>
      {% else %}<span class="muted">None on file</span>{% endif %}
    </div></div>
  </div>
  <div style="margin-top:.5rem"><a class="btn wide" href="/dispatch/{{pid}}/report">FILE PATIENT REPORT →</a></div>
""" + FOOT

FORM_PAGE = SIREN_SHELL + """
 <div class="sid"><span class="nm">{{c.name}}</span>
   <span class="dm">{{c.gender|upper}} · DOB {{c.dob}} · {{c.mrn}}</span>
   <span class="rt">INC {{call.incident or '—'}} · {{call.unit or ''}} · record completed after call cleared</span></div>
 <form method="post">
  <div class="sec"><div class="sech">Vitals <span class="n">time of assessment</span></div><div class="secb">
   <div class="vgrid">
    <div><label class="sf">Heart rate</label><input type="number" name="heart_rate" placeholder="bpm"></div>
    <div><label class="sf">Resp rate</label><input type="number" name="resp_rate" placeholder="/min"></div>
    <div><label class="sf">SpO₂</label><input type="number" name="spo2" placeholder="%"></div>
    <div><label class="sf">BP systolic</label><input type="number" name="bp_systolic" placeholder="mmHg"></div>
    <div><label class="sf">BP diastolic</label><input type="number" name="bp_diastolic" placeholder="mmHg"></div>
    <div><label class="sf">Temp</label><input type="number" step="0.1" name="temperature" placeholder="°C"></div>
    <div><label class="sf">GCS</label><input type="number" name="gcs" placeholder="3-15"></div>
    <div><label class="sf">Blood glucose</label><div style="display:flex;gap:.2rem">
      <input type="number" step="0.1" name="glucose" placeholder="value">
      <select name="glucose_unit"><option value="mmol/L">mmol/L</option><option value="mg/dL">mg/dL</option></select>
    </div></div>
   </div>
  </div></div>
  <div class="sec"><div class="sech">Treatments &amp; interventions</div><div class="secb">
   <div class="tgrid">
    {% for i in interventions %}<label class="tchk"><input type="checkbox" name="intervention" value="{{i}}">{{i}}</label>{% endfor %}
   </div>
   <div style="margin-top:.45rem"><label class="sf">Other / narrative note</label>
     <input type="text" name="other" placeholder="free text"></div>
  </div></div>
  <button class="sbtn" type="submit">TRANSMIT TO RECEIVING FACILITY →</button>
 </form>
 <div style="margin-top:.5rem"><a href="/dispatch/{{pid}}">← back to pre-arrival</a></div>
""" + SIREN_FOOT

RESULT_PAGE = SIREN_SHELL + """
 <div class="sec"><div class="sech">Transmission result
   <span class="n">{{ results|selectattr('ok')|list|length }} of {{results|length}} accepted</span></div><div class="secb">
  {% if not results %}<div class="sbad">Nothing to send — no vitals or interventions entered.</div>{% endif %}
  {% for r in results %}
    <div class="{{ 'sok' if r.ok else 'sbad' }}">{{ '✓' if r.ok else '✗' }}
      <b>{{r.resourceType}}</b> — {{r.label}}
      <span class="mono">{% if r.ok %}· {{r.id}} · HTTP {{r.status}}{% else %}· {{r.error or r.status}}{% endif %}</span></div>
  {% endfor %}
  <div class="muted" style="margin-top:.4rem">Appended to the receiving facility's record as FHIR. Nothing overwritten.</div>
 </div></div>
 <div style="margin-top:.5rem"><a href="/dispatch/{{pid}}">← back to pre-arrival</a></div>
""" + SIREN_FOOT


@app.get("/")
def index():
    return render_template_string(CALLS_PAGE, calls=CALLS, stages=stage_bar(0),
                                  title="CAD — Active Calls", brand="MOCK CAD",
                                  mode="ACTIVE CALLS", right=f"{len(CALLS)} active")


@app.get("/dispatch/<pid>")
def dispatch(pid):
    call = call_for(pid)
    try:
        card = bridge.pre_arrival_card(pid)
    except bridge.PatientNotFound:
        abort(404)
    except requests.HTTPError:
        abort(502)
    except requests.ConnectionError:
        return "Hospital FHIR service unreachable — is hospital/app.py running on :8001?", 503
    return render_template_string(PAGE, c=card, pid=pid, call=call, stages=stage_bar(1),
                                  title="Pre-Arrival", brand=call.get("unit", "MEDIC 4"),
                                  mode="EN ROUTE", right=f"ETA {call.get('eta','—')} · PRE-ARRIVAL")


@app.get("/dispatch/<pid>/report")
def report_form(pid):
    call = call_for(pid)
    try:
        card = bridge.pre_arrival_card(pid)
    except bridge.PatientNotFound:
        abort(404)
    except requests.ConnectionError:
        return "Hospital FHIR service unreachable", 503
    return render_template_string(FORM_PAGE, c=card, pid=pid, call=call,
                                  interventions=INTERVENTIONS, tabs=section_tabs("Vitals"),
                                  title="ePCR — Patient Report", brand="MOCK ePCR",
                                  mode="POST-CALL RECORD")


@app.post("/dispatch/<pid>/report")
def report_submit(pid):
    call = call_for(pid)
    f = request.form
    interventions = list(f.getlist("intervention"))
    other = (f.get("other") or "").strip()
    if other:
        interventions.append(other)
    report = {k: f.get(k) for k in ("heart_rate", "resp_rate", "spo2", "bp_systolic",
                                    "bp_diastolic", "temperature", "gcs", "glucose")}
    report["glucose_unit"] = f.get("glucose_unit") or "mmol/L"
    report["interventions"] = interventions
    results = bridge.push_report(pid, report, unit=call.get("unit", "MEDIC 4"))
    return render_template_string(RESULT_PAGE, results=results, pid=pid, call=call,
                                  tabs=section_tabs("Disposition"), title="ePCR — Transmitted",
                                  brand="MOCK ePCR", mode="TRANSMITTED")


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=8002,
            debug=os.environ.get("DEBUG") == "1")
