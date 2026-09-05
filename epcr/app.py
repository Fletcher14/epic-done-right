"""
Mock ePCR (the 'Siren / iNet' side — the crew-facing app).

On dispatch to a patient, it calls the bridge, gets the pre-arrival card,
and renders it the way you'd want it in the truck: safety alert first,
allergies with real specificity, meds. The thing that doesn't exist today.

Run:  python epcr/app.py    (listens on :8002, open in a browser)
Requires the hospital app to be running on :8001.
"""
import sys
import os
from flask import Flask, render_template_string, abort
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))
import bridge  # noqa: E402

app = Flask(__name__)

PAGE = """
<!doctype html><html><head><title>ePCR — Pre-Arrival</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#080a0d;color:#f2f5f8;
      margin:0;padding:0;font-size:17px;-webkit-font-smoothing:antialiased}
 .bar{background:#12171f;border-bottom:2px solid #1f2732;padding:.7rem 1rem;display:flex;
      align-items:center;gap:.75rem;position:sticky;top:0}
 .unit{font-weight:800;letter-spacing:.08em;color:#4da3ff;font-size:.85rem}
 .mode{background:#1c2634;color:#8fb8e8;font-size:.7rem;font-weight:700;letter-spacing:.1em;
       padding:.2rem .5rem;border-radius:3px}
 .eta{margin-left:auto;font-family:ui-monospace,monospace;color:#7d8b9c;font-size:.8rem}
 .wrap{max-width:760px;margin:0 auto;padding:1rem}
 .safety{background:#7f0f0f;border:2px solid #ff4444;border-radius:8px;padding:1rem 1.1rem;
         margin-bottom:1rem;box-shadow:0 0 24px rgba(255,40,40,.28)}
 .safety .lbl{font-size:.72rem;font-weight:800;letter-spacing:.14em;color:#ffb3b3}
 .safety .txt{font-size:1.35rem;font-weight:800;color:#fff;line-height:1.2;margin-top:.2rem}
 .name{font-size:2rem;font-weight:800;letter-spacing:-.02em;margin:.2rem 0 .1rem}
 .demo{color:#8b98a8;font-family:ui-monospace,monospace;font-size:.9rem;margin-bottom:1.1rem}
 h2{font-size:.72rem;text-transform:uppercase;letter-spacing:.14em;color:#6f7d8f;
    margin:1.4rem 0 .5rem;border-bottom:1px solid #1f2732;padding-bottom:.35rem}
 .alg{background:#241014;border-left:6px solid #d98a00;border-radius:6px;padding:.75rem .9rem;margin:.5rem 0}
 .alg.sev{border-left-color:#ff3b3b;background:#2b0e0e}
 .sub{font-size:1.25rem;font-weight:800}
 .rx{color:#e8c9c9;margin-top:.15rem;font-size:.98rem}
 .pill{display:inline-block;background:#ff3b3b;color:#fff;font-size:.68rem;font-weight:800;
       letter-spacing:.09em;padding:.16rem .48rem;border-radius:3px;margin-left:.4rem;vertical-align:middle}
 .pill.mod{background:#d98a00}
 .med{background:#11161e;border:1px solid #1f2732;border-radius:6px;padding:.6rem .9rem;margin:.4rem 0;
      font-size:1.02rem;font-weight:600}
 .none{color:#5c6874;font-style:italic}
 .foot{color:#4e5865;font-size:.72rem;text-align:center;padding:1.5rem 1rem 2rem}
</style></head><body>
 <div class="bar">
   <span class="unit">MEDIC 4</span><span class="mode">PRE-ARRIVAL</span>
   <span class="eta">INBOUND · SYNTHETIC DATA</span>
 </div>
 <div class="wrap">
  {% for alert in c.safety_alerts %}
    <div class="safety"><div class="lbl">⚠ SAFETY ALERT</div><div class="txt">{{alert}}</div></div>
  {% endfor %}

  <div class="name">{{c.name}}</div>
  <div class="demo">{{c.gender|upper}} · DOB {{c.dob}} · {{c.mrn}}</div>

  <h2>Allergies</h2>
  {% if c.allergies %}
    {% for a in c.allergies %}
      <div class="alg {% if a.severity=='severe' %}sev{% endif %}">
        <div class="sub">{{a.substance}}
          {% if a.severity %}<span class="pill {% if a.severity!='severe' %}mod{% endif %}">{{a.severity|upper}}</span>{% endif %}
        </div>
        {% if a.reaction %}<div class="rx">{{a.reaction}}{% if a.criticality %} · {{a.criticality}} criticality{% endif %}</div>{% endif %}
      </div>
    {% endfor %}
  {% else %}<div class="none">No known allergies</div>{% endif %}

  <h2>Current Medications</h2>
  {% if c.medications %}{% for m in c.medications %}<div class="med">{{m}}</div>{% endfor %}
  {% else %}<div class="none">None on file</div>{% endif %}
 </div>
 <div class="foot">MOCK ePCR — synthetic data · received via FHIR bridge</div>
</body></html>
"""


@app.get("/dispatch/<pid>")
def dispatch(pid):
    try:
        card = bridge.pre_arrival_card(pid)
    except bridge.PatientNotFound:
        abort(404)
    except requests.HTTPError:
        abort(502)
    except requests.ConnectionError:
        return "Hospital FHIR service unreachable — is hospital/app.py running on :8001?", 503
    return render_template_string(PAGE, c=card)


@app.get("/")
def index():
    return ('<h2>Mock ePCR</h2><p>Dispatch to a patient:</p><ul>'
            '<li><a href="/dispatch/pt-001">pt-001 (Dwyer — allergy + safety flag)</a></li>'
            '<li><a href="/dispatch/pt-002">pt-002 (Osei — clean)</a></li>'
            '<li><a href="/dispatch/pt-003">pt-003 (Reilly — mild allergy)</a></li></ul>')


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=8002, debug=True)
