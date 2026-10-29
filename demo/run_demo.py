"""Demo: de-identify a JupyterHealth bundle at the edge, let an 'AI' summarise it, re-identify for the clinician."""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gateway import Gateway
g = Gateway(); b = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_bundle.json")))
t = time.perf_counter(); safe, sess = g.deidentify(b); ms = (time.perf_counter() - t) * 1000
obs = [e["resource"] for e in safe["entry"] if e["resource"]["resourceType"] == "Observation"]
omh = [json.loads(base64.b64decode(o["valueAttachment"]["data"])) for o in obs]
note = safe["entry"][3]["resource"]["note"][0]["text"]
print("=== what leaves the device (excerpt) ===")
print(json.dumps(safe["entry"][0]["resource"], indent=1)); print(json.dumps(omh[0]["body"], indent=1)); print(note)
# Stand-in for an LLM/analytics step: it only ever sees placeholders and clinical values.
summary = (f"Alert: BP {omh[0]['body']['systolic_blood_pressure']['value']}/{omh[0]['body']['diastolic_blood_pressure']['value']} mmHg "
           f"and fasting glucose {omh[1]['body']['blood_glucose']['value']} mg/dL. Caregiver note: {note}")
print("\n=== clinician view after re-identification ===")
print(g.reidentify(summary, sess))
print(f"\nde-identification time {ms:.1f} ms; placeholders {len(sess.reverse)}; date shift kept only in session")
sess.destroy()
