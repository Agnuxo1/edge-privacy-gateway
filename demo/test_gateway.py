import base64, json, os
from gateway import Gateway


def test_missing_frozen_lexicon_fails_closed(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError, match="refusing silent privacy degradation"):
        Gateway(lexicon=str(tmp_path / "missing-lexicon.json"))

def test_roundtrip_and_no_hard_identifiers():
    g = Gateway(); b = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_bundle.json")))
    safe, s = g.deidentify(b)
    blob = json.dumps(safe) + "".join(base64.b64decode(e["resource"]["valueAttachment"]["data"]).decode()
                                      for e in safe["entry"] if "valueAttachment" in e["resource"])
    for leak in ["MRN-4471902", "512-44-9821", "grace.okafor@example.org", "415-555-0199", "+1 415 555 0142",
                 "1220 Valencia St", "94110", "1957-03-14", "Lena Park", "Delgado", "10/18/2026"]:
        assert leak not in blob, leak
    for keep in ["162/98 mmHg", "lisinopril 20 mg", '"value": 214']:
        assert keep in blob, keep
    note = safe["entry"][3]["resource"]["note"][0]["text"]
    assert g.reidentify(note, s) == b["entry"][3]["resource"]["note"][0]["text"]
    assert getattr(s, "date_shift_days") != 0
