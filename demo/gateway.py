"""NAVAJO Edge Privacy Gateway for JupyterHealth (prototype).

Sits between JupyterHealth Exchange (FHIR R5 Observations whose valueAttachment
carries base64 Open mHealth JSON) and any AI/analytics consumer:

  deidentify(bundle) -> (safe_bundle, session)   # runs on a clinic laptop / home hub, no GPU, no network
  ... safe_bundle goes to an LLM or analytics notebook ...
  reidentify(text, session) -> text for the clinician
  session.destroy()                               # ephemeral key, nothing stored

Free text (symptom diaries, caregiver messages, notes) goes through the NAVAJO-v2
detector with reversible placeholders; structured identifiers (Patient name,
identifier, telecom, address, birthDate) are pseudonymised; clinical values are kept;
dates are shifted by a per-session random offset so intervals stay intact.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import os
import re
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bench"))
sys.path.insert(0, os.path.join(HERE, "..", "vendor"))
from navajo_egp.session import EGPSession  # noqa: E402
from navajo_v2 import NavajoV2  # noqa: E402

LEXICON = os.path.join(HERE, "..", "assets", "lexicon_train.json")
TEXT_KEYS = {"text", "note", "valueString", "comment", "description", "free_text", "user_notes", "message"}
DROP_KEYS = {"telecom", "address", "photo", "contact"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$")


class Gateway:
    def __init__(self, lexicon=LEXICON):
        if not os.path.isfile(lexicon):
            raise FileNotFoundError("Frozen train lexicon required; refusing silent privacy degradation")
        self.detector = NavajoV2(lexicon)

    # ---------------- free text ----------------
    def mask_text(self, text, session, counter):
        out, last = [], 0
        for s, e in self.detector.detect(text):
            orig = text[s:e]
            ph = session.get_placeholder(orig)
            if ph is None:
                counter[0] += 1
                ph = f"[PHI_{counter[0]}]"
                session.add(orig, ph)
            out.append(text[last:s] + ph)
            last = e
        out.append(text[last:])
        return "".join(out)

    @staticmethod
    def reidentify(text, session):
        for ph, orig in sorted(session.reverse.items(), key=lambda x: -len(x[0])):
            text = text.replace(ph, orig)
        return text

    # ---------------- structured ----------------
    def _shift(self, value, days):
        try:
            if len(value) == 10:
                return (dt.date.fromisoformat(value) + dt.timedelta(days=days)).isoformat()
            v = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) + dt.timedelta(days=days)
            return v.isoformat().replace("+00:00", "Z")
        except ValueError:
            return value

    def _walk(self, node, session, counter, days):
        if isinstance(node, dict):
            for k in list(node):
                v = node[k]
                if k in DROP_KEYS:
                    del node[k]
                elif k == "name" and isinstance(v, list):  # HumanName
                    node[k] = [{"text": self._pseudo(json.dumps(v, sort_keys=True), session, counter, "NAME")}]
                elif k == "identifier":
                    node[k] = [{"value": self._pseudo(json.dumps(v, sort_keys=True), session, counter, "ID")}]
                elif k == "birthDate" and isinstance(v, str):
                    node[k] = v[:4]  # Safe Harbor keeps the year (ages > 89 need aggregation)
                elif k == "valueAttachment" and isinstance(v, dict) and "data" in v:
                    omh = json.loads(base64.b64decode(v["data"]))
                    self._walk(omh, session, counter, days)
                    v["data"] = base64.b64encode(json.dumps(omh).encode()).decode()
                elif k in TEXT_KEYS and isinstance(v, str):
                    node[k] = self.mask_text(v, session, counter)
                elif isinstance(v, str) and ISO.match(v):
                    node[k] = self._shift(v, days)
                else:
                    self._walk(v, session, counter, days)
        elif isinstance(node, list):
            for x in node:
                self._walk(x, session, counter, days)

    @staticmethod
    def _pseudo(orig, session, counter, kind):
        ph = session.get_placeholder(orig)
        if ph is None:
            counter[0] += 1
            ph = f"[{kind}_{counter[0]}]"
            session.add(orig, ph)
        return ph

    def deidentify(self, bundle):
        session = EGPSession()
        days = secrets.choice([d for d in range(-180, 181) if d])
        session.date_shift_days = days  # kept only in the ephemeral session, never in the output
        safe = copy.deepcopy(bundle)
        self._walk(safe, session, [0], days)
        return safe, session
