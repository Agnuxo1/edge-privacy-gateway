"""Synthetic JupyterHealth-style bundle (fictional patient; no real data)."""
import base64, json
def att(omh): return {"contentType": "application/json", "data": base64.b64encode(json.dumps(omh).encode()).decode()}
bp = {"header": {"uuid": "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b", "schema_id": {"namespace": "omh", "name": "blood-pressure", "version": "4.0"},
                 "source_creation_date_time": "2026-10-20T07:42:00Z"},
      "body": {"systolic_blood_pressure": {"value": 162, "unit": "mmHg"}, "diastolic_blood_pressure": {"value": 98, "unit": "mmHg"},
               "effective_time_frame": {"date_time": "2026-10-20T07:40:00Z"}, "user_notes": "Felt dizzy after walking the dog with my neighbor Rosa Delgado. Took lisinopril 20 mg late."}}
glu = {"header": {"uuid": "0b9e8d7c-6a5f-4e3d-2c1b-0a9f8e7d6c5b", "schema_id": {"namespace": "omh", "name": "blood-glucose", "version": "3.0"}},
       "body": {"blood_glucose": {"value": 214, "unit": "mg/dL"}, "temporal_relationship_to_meal": "fasting",
                "effective_time_frame": {"date_time": "2026-10-21T06:55:00Z"}}}
bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
  {"resource": {"resourceType": "Patient", "id": "jhe-10457", "identifier": [{"system": "urn:ucsf:mrn", "value": "MRN-4471902"}],
                "name": [{"family": "Okafor", "given": ["Daniel"]}], "telecom": [{"system": "phone", "value": "+1 415 555 0142"}],
                "birthDate": "1957-03-14", "address": [{"line": ["1220 Valencia St"], "city": "San Francisco", "postalCode": "94110"}]}},
  {"resource": {"resourceType": "Observation", "status": "final", "subject": {"reference": "Patient/jhe-10457"},
                "code": {"coding": [{"system": "https://w3id.org/openmhealth", "code": "omh:blood-pressure:4.0"}]}, "valueAttachment": att(bp)}},
  {"resource": {"resourceType": "Observation", "status": "final", "subject": {"reference": "Patient/jhe-10457"},
                "code": {"coding": [{"system": "https://w3id.org/openmhealth", "code": "omh:blood-glucose:3.0"}]}, "valueAttachment": att(glu)}},
  {"resource": {"resourceType": "Communication", "status": "completed", "subject": {"reference": "Patient/jhe-10457"},
                "payload": [{"contentString": None}],
                "note": [{"text": "Message from daughter Grace Okafor (grace.okafor@example.org, 415-555-0199): Dad missed his 10/18/2026 follow-up with Dr. Lena Park; his SSN 512-44-9821 was on the clinic form. BP log attached, 162/98 mmHg this morning."}]}}]}
json.dump(bundle, open("sample_bundle.json", "w"), indent=1)
